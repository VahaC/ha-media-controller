"""The rules that decide whether a panel has a newer firmware to install.

A paired ESP32 panel is updated over the air by Home Assistant, and two
questions have to be answered before a single byte moves:

* **is there a newer build, and can this integration talk to it?** A firmware
  that speaks a contract this integration does not know would install
  perfectly and then sit there ignoring half of what it is sent. The release
  index therefore carries a contract version per build, and a build is
  offered only when this integration is at least that new.
* **may this request have the binary?** The panel cannot authenticate the
  download itself — see `panel_firmware.py` for why — so the manifest call,
  which *is* authenticated, hands out a single-use nonce and the binary route
  accepts nothing else.

Both are rules rather than plumbing, so they live here, with no Home
Assistant imports, and are tested without a runtime. The endpoints that use
them are in `panel_firmware.py`, exactly as `pairing.py` stands behind
`provision.py`.

Nothing here fetches anything. The document this module reads is whatever the
caller downloaded, and it is treated as untrusted input throughout: it is a
file on a public web page, and a malformed or hostile one must produce "no
update" rather than an exception or a download of something else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import logging
import secrets
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# The file the installer site publishes beside the images, and the only thing
# this integration reads to learn that a build exists. The site is the same
# one the web installer flashes from, so "what a panel can be updated to" and
# "what a panel would be installed with over USB" cannot drift apart.
INDEX_FILENAME = "versions.json"

# An installation with no route to the internet reads nothing here and is
# offered nothing, which is the honest answer: Home Assistant downloads the
# binary and serves it to the panel, so a Home Assistant that cannot reach
# the release has no update to give. Nothing else about the panel changes.

# The contract version in which a panel first gained an over-the-air update
# client at all.
#
# This is not a nicety, it is the one thing no code on either side can work
# around. Firmware 0.5.0 — the image the web installer published before this
# existed — carries no OTA client of any kind. It cannot be told to fetch
# anything, because there is nothing in it that fetches. A panel already on
# that build therefore has to be moved forward **once, over USB**, and every
# update after that one is over the air.
#
# So it is asked rather than assumed. A panel reports the contract it speaks
# in every status report; a panel that reports less than this is offered
# nothing here, and the repair issue in `compatibility.py` — which is not
# suppressed while nothing is on offer — sends its owner to the web
# installer, which is the only thing that can help it.
MIN_OTA_CONTRACT_VERSION = 8

# What a published image may weigh. The upper bound is the app partition of
# the published table — see `tests/test_factory_firmware.py`, which pins that
# table — so an index entry that could not fit in a slot is refused here
# rather than after two megabytes have been downloaded. The lower bound only
# catches an error page saved as a firmware.
MAX_IMAGE_BYTES = 7936 * 1024
MIN_IMAGE_BYTES = 64 * 1024

SHA256_LENGTH = 64
MD5_LENGTH = 32

# One live nonce per panel, and this long to use it. The panel asks for the
# manifest and starts the download in the same breath, so this is generous:
# it covers a device that was interrupted between the two calls and nothing
# else. A download already under way is not affected — the nonce is spent
# when the request arrives, not when it finishes.
NONCE_TTL_SECONDS = 300.0
NONCE_BYTES = 16
# The length `secrets.token_hex(NONCE_BYTES)` produces. The route matches on
# it so that a request which could not be a nonce never reaches the store.
NONCE_LENGTH = NONCE_BYTES * 2


def _text(value: Any, limit: int) -> str:
    """Return a bounded string, or "" for anything that is not usable."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if 0 < len(text) <= limit else ""


def _digest(value: Any, length: int) -> str:
    """Return a lowercase hex digest of the expected length, or ""."""
    text = _text(value, length)
    if len(text) != length:
        return ""
    text = text.lower()
    return text if all(character in "0123456789abcdef" for character in text) else ""


def read_version(value: Any) -> tuple[int, ...] | None:
    """Return a dotted-numeric version as a tuple, or None for anything else.

    Deliberately strict. Released firmware is `X.Y.Z` and nothing else, and a
    version this function cannot read means "do not compare", which every
    caller turns into "offer nothing". Guessing at the order of two strings
    that are not versions is how a device gets sent backwards.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parts = text.split(".")
    if len(parts) > 4:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers)


def is_newer(candidate: str, installed: str) -> bool:
    """Return whether one version is strictly newer than another.

    Either side being unreadable is answered `False`: an unknown installed
    version is the case of a panel that has never reported, and offering it
    a firmware on no evidence would be worse than waiting for its first
    report, which arrives within seconds of it starting.
    """
    left = read_version(candidate)
    right = read_version(installed)
    if left is None or right is None:
        return False
    # (0, 6) and (0, 6, 0) are the same release written two ways.
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left > right


@dataclass(frozen=True, slots=True)
class FirmwareRelease:
    """One published build, as the release index describes it.

    `path` is relative to the installer site and is never joined with
    anything a request supplied: it comes out of the index and is used to
    fetch the binary, and only Home Assistant ever resolves it.
    """

    version: str
    contract_version: int
    path: str
    size: int
    sha256: str
    md5: str
    release_url: str = ""

    @property
    def is_usable(self) -> bool:
        """Return whether every field needed to install this build is sound."""
        return bool(
            read_version(self.version) is not None
            and self.contract_version > 0
            and self.path
            and self.sha256
            and self.md5
            and MIN_IMAGE_BYTES <= self.size <= MAX_IMAGE_BYTES
        )


def _read_release(entry: Any) -> FirmwareRelease | None:
    """Read one entry of the release index, or None when it is not one.

    An entry without an `ota` block is not an error: every index written
    before over-the-air updates existed looks exactly like that, and it still
    describes a build the web installer can flash over USB. It simply cannot
    be offered as an update.
    """
    if not isinstance(entry, dict):
        return None
    ota = entry.get("ota")
    if not isinstance(ota, dict):
        return None

    size = ota.get("size")
    if isinstance(size, bool) or not isinstance(size, int):
        return None
    contract = entry.get("contract_version")
    if isinstance(contract, bool) or not isinstance(contract, int):
        return None

    release = FirmwareRelease(
        version=_text(entry.get("version"), 32),
        contract_version=contract,
        path=_text(ota.get("path"), 255),
        size=size,
        sha256=_digest(ota.get("sha256"), SHA256_LENGTH),
        md5=_digest(ota.get("md5"), MD5_LENGTH),
        release_url=_text(entry.get("release_url"), 255),
    )
    return release if release.is_usable else None


def read_index(document: Any) -> tuple[FirmwareRelease, ...]:
    """Return every installable build in a release index.

    The document is a file downloaded from a public page, so nothing about it
    is assumed. Anything unreadable is dropped rather than raised over: a
    single malformed entry must not hide the builds beside it, and a
    completely malformed file must mean "no update", not a broken entity.
    """
    if not isinstance(document, dict):
        return ()
    builds = document.get("builds")
    if not isinstance(builds, list):
        return ()

    releases: list[FirmwareRelease] = []
    seen: set[str] = set()
    for entry in builds:
        release = _read_release(entry)
        if release is None or release.version in seen:
            continue
        seen.add(release.version)
        releases.append(release)
    # Newest first, so a caller reads the answer off the front.
    releases.sort(key=lambda item: read_version(item.version) or (), reverse=True)
    return tuple(releases)


def can_update_over_the_air(panel_contract: int) -> bool:
    """Return whether a panel on this contract can be updated from here.

    See `MIN_OTA_CONTRACT_VERSION`: a build from before the update client
    existed cannot be told to fetch anything, and has to be moved forward
    once over USB.
    """
    return panel_contract >= MIN_OTA_CONTRACT_VERSION


def select_release(
    releases: tuple[FirmwareRelease, ...],
    *,
    installed_version: str,
    panel_contract: int,
    integration_contract: int,
) -> FirmwareRelease | None:
    """Return the newest build this panel should be offered, or None.

    Three conditions, and all of them have to hold:

    * the panel **has an update client at all**. A build from before one
      existed is not offered anything here, because nothing here could reach
      it; see `can_update_over_the_air`;
    * the build is **newer than what the panel reported**. The panel's own
      report is the only trustworthy statement of what is on it; nothing is
      inferred from when it was paired or what was current at the time;
    * this integration **already speaks the build's contract**. A firmware
      built against a newer contract would install and then quietly ignore
      part of what it is sent, and the person who pressed the button would
      have made their panel worse. The upgrade order is the integration
      first, which is also the order HACS makes easy.

    A newer build held back by either version rule is not an error and raises
    nothing. Both cases are already reported where a person will see them:
    the repair issue in `compatibility.py` for a panel that is behind, and
    the update entity's own attributes for a build that is being withheld.
    """
    if not can_update_over_the_air(panel_contract):
        return None
    for release in releases:
        if release.contract_version > integration_contract:
            continue
        if is_newer(release.version, installed_version):
            return release
    return None


@dataclass(frozen=True, slots=True)
class FirmwareNonce:
    """One permission to download one build, once."""

    panel_id: str
    version: str
    expires_at: float


@dataclass(slots=True)
class NonceStore:
    """The download permissions that are currently outstanding.

    Keyed by panel, one at a time. A panel that asks for the manifest twice
    invalidates its own previous nonce, which bounds this store by the number
    of paired panels rather than by how often anything is asked for.

    A nonce is not a credential and deliberately carries no authority of its
    own: it names one panel and one version, it is spent the first time it is
    presented, and it dies on its own a few minutes later. It exists only
    because ESPHome's HTTP OTA client cannot send an `Authorization` header —
    see `panel_firmware.py`.
    """

    nonces: dict[str, FirmwareNonce] = field(default_factory=dict)

    @staticmethod
    def _now(now: float | None) -> float:
        return time.monotonic() if now is None else now

    def issue(
        self,
        panel_id: str,
        version: str,
        *,
        now: float | None = None,
    ) -> str:
        """Return a fresh nonce for one panel, replacing any it still had."""
        current = self._now(now)
        self._purge(current)
        for token, nonce in list(self.nonces.items()):
            if nonce.panel_id == panel_id:
                del self.nonces[token]
        token = secrets.token_hex(NONCE_BYTES)
        self.nonces[token] = FirmwareNonce(
            panel_id=panel_id,
            version=version,
            expires_at=current + NONCE_TTL_SECONDS,
        )
        return token

    def consume(
        self,
        token: str,
        *,
        now: float | None = None,
    ) -> FirmwareNonce | None:
        """Spend a nonce, returning what it permitted, or None.

        The comparison is constant-time and the lookup is over the whole
        store, so a caller cannot learn which half of a guess was right from
        how long the answer took. It is spent whether or not the download
        that follows succeeds: a retry asks for the manifest again, which the
        panel can do because that call carries its token.
        """
        current = self._now(now)
        self._purge(current)
        if not isinstance(token, str) or len(token) != NONCE_LENGTH:
            return None
        found: str | None = None
        for candidate in self.nonces:
            if hmac.compare_digest(candidate, token):
                found = candidate
        if found is None:
            return None
        return self.nonces.pop(found)

    def _purge(self, now: float) -> None:
        """Drop every nonce that has run out of time."""
        for token, nonce in list(self.nonces.items()):
            if nonce.expires_at <= now:
                del self.nonces[token]
