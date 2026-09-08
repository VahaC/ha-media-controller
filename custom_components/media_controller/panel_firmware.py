"""The endpoints a panel updates its own firmware from.

```text
GET /api/media_controller/panel_firmware/{panel_id}           the manifest
GET /api/media_controller/panel_firmware/{panel_id}/{nonce}   the image
```

Why this exists at all is in `docs/ESP32_PAIRED_CONTROLLER.md`: a panel
flashed from the public web installer has no ESPHome OTA, because ESPHome's
OTA needs a password and a password compiled into a file anybody can download
is not a password. A paired panel does hold something no other device has —
the Home Assistant token minted for it alone — and that is what authorises an
update here.

**Home Assistant fetches the binary; the panel does not.** A panel on an
isolated VLAN has no route to the internet, and giving the device a
certificate bundle and TLS so it could reach a public host would cost flash
and add an attack surface for nothing. Home Assistant already has both. It
downloads the released image, checks its SHA-256 before anything is offered
to anybody, and serves the bytes it verified over the local network.

**Two routes, because the download cannot carry a token.** ESPHome's
`ota: platform: http_request` sends no `Authorization` header — its update
action accepts a URL, an MD5 and HTTP Basic credentials, and nothing else.
So the authenticated half and the download are separated:

* the **manifest** is an ordinary authenticated panel endpoint, guarded by
  the same ownership rule as `status.py`, `panel_layout.py` and
  `panel_card.py`. It answers only the panel whose token it is, and only
  about that panel's own pending build. It hands back a single-use nonce;
* the **image** route is unauthenticated by necessity and guarded by that
  nonce alone: one panel, one version, one use, five minutes. The nonce is
  not the token and grants nothing else, so this does not put a credential
  in a URL, and the route serves exactly one thing — an image Home Assistant
  has already downloaded and verified for that panel. It is not a proxy: no
  request can name what it fetches.

Nothing is ever downloaded because a device asked. The image is fetched when
a person presses Install in Home Assistant, verified there, and only then is
the panel told a version is waiting. A panel that asks for a manifest with no
pending build is told there is nothing, and no traffic leaves the house.

The rules — which build is newer, which is compatible, and what a nonce
permits — are in `firmware_release.py`, which has no Home Assistant imports
and is tested without a runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientTimeout, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DATA_FIRMWARE,
    DATA_PANELS,
    DOMAIN,
    FIRMWARE_INDEX_INTERVAL,
    INSTALLER_URL,
)
from .contract import CONTRACT_VERSION
from .firmware_release import (
    INDEX_FILENAME,
    MAX_IMAGE_BYTES,
    NONCE_LENGTH,
    FirmwareRelease,
    NonceStore,
    read_index,
    select_release,
)
from .panel_state import UPDATE_TIMEOUT_SECONDS
from .status import STATUS_UNKNOWN_PANEL, STATUS_WRONG_PANEL, async_resolve_panel

_LOGGER = logging.getLogger(__name__)

MANIFEST_URL = "/api/media_controller/panel_firmware/{panel_id}"
IMAGE_URL = "/api/media_controller/panel_firmware/{panel_id}/{nonce}"

STATUS_OK = "ok"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_NOT_READY = "not_ready"
STATUS_UNKNOWN_NONCE = "unknown_nonce"

# The image is a firmware, not a document, and must not be sniffed as one.
IMAGE_CONTENT_TYPE = "application/octet-stream"

# How long to wait for the release index and for the image itself. The index
# is a few hundred bytes; the image is a couple of megabytes from GitHub
# Pages, fetched while somebody watches a spinner in Home Assistant.
INDEX_TIMEOUT = ClientTimeout(total=30)
IMAGE_TIMEOUT = ClientTimeout(total=180)

# How close together two "check for updates" requests have to be before the
# second is answered with the first one's result. Home Assistant asks every
# update entity at once, so an installation with four panels would otherwise
# ask the installer site for the same few hundred bytes four times in the
# same second. It is short enough that a person pressing the button again
# because the first answer surprised them still gets a fresh read.
INDEX_CHECK_COALESCE_SECONDS = 30.0

# How much of a download is read at a time. The body is read in pieces rather
# than in one call because a stream returns what has arrived, not what was
# asked for: a single read of two megabytes comes back short and would leave
# an image that fails its digest check for no reason anybody could debug.
DOWNLOAD_CHUNK = 64 * 1024


class FirmwareUnavailable(Exception):
    """The released image could not be fetched or did not match its digest."""


@dataclass(slots=True)
class PreparedImage:
    """One verified firmware image, held until a panel has collected it."""

    release: FirmwareRelease
    payload: bytes
    md5: str
    prepared_at: float


class FirmwareIndex:
    """What the installer site publishes, and the images taken from it.

    One per Home Assistant installation. Every panel reads the same index,
    and two panels updating to the same build download it once.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Prepare the index without fetching anything."""
        self._hass = hass
        self.releases: tuple[FirmwareRelease, ...] = ()
        # Whether the index has ever been read successfully. Until it has,
        # "no update" means "not asked yet" rather than "up to date", and the
        # update entity says so instead of claiming a panel is current.
        self.loaded = False
        self.nonces = NonceStore()
        self._images: dict[str, PreparedImage] = {}
        self._listeners: list[Any] = []
        self._lock = asyncio.Lock()
        # When the index was last asked for -- asked, not read successfully,
        # because an installation that cannot reach the site must not retry
        # once per panel per button press. Both of these belong to
        # `async_check_now`; the six-hourly timer needs neither.
        self._checked_at: float | None = None
        self._check_lock = asyncio.Lock()

    # ----------------------------------------------------------- listeners

    @callback
    def add_listener(self, listener: Any) -> Any:
        """Follow every change to what is published; returns the remover."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # --------------------------------------------------------------- index

    async def async_refresh(self, _now: Any = None) -> None:
        """Read the release index, leaving the last good one on failure.

        An installation with no route to the internet fails here on every
        attempt and is offered nothing, which is the honest answer: Home
        Assistant serves the image to the panel, so a Home Assistant that
        cannot reach the release has no update to give. Nothing else about
        the panel is affected, and this is logged at debug level because a
        deliberately offline installation must not fill a log with it.
        """
        url = urljoin(INSTALLER_URL, INDEX_FILENAME)
        session = async_get_clientsession(self._hass)
        self._checked_at = time.monotonic()
        try:
            async with session.get(url, timeout=INDEX_TIMEOUT) as response:
                response.raise_for_status()
                document = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Could not read the firmware release index: %s", err)
            return

        releases = read_index(document)
        changed = releases != self.releases or not self.loaded
        self.releases = releases
        self.loaded = True
        if changed:
            self._notify()

    async def async_check_now(self) -> None:
        """Read the index because a person asked, not because six hours passed.

        The timer is right for a background poll and wrong for the person who
        has just published a build and is looking at the update dialog: until
        this existed, the only thing that re-read the index sooner was
        restarting Home Assistant, because the reader is started in
        `async_setup` and survives a config entry being reloaded.

        Home Assistant's `homeassistant.update_entity` -- what **Check for
        updates** calls -- reaches this through every panel's update entity
        at once, which is what the coalescing window is for.
        """
        async with self._check_lock:
            if (
                self._checked_at is not None
                and time.monotonic() - self._checked_at
                < INDEX_CHECK_COALESCE_SECONDS
            ):
                return
            await self.async_refresh()

    def offer(
        self,
        installed_version: str,
        panel_contract: int,
    ) -> FirmwareRelease | None:
        """Return the build a panel in this state should be offered."""
        return select_release(
            self.releases,
            installed_version=installed_version,
            panel_contract=panel_contract,
            integration_contract=CONTRACT_VERSION,
        )

    # -------------------------------------------------------------- images

    async def async_prepare(self, release: FirmwareRelease) -> PreparedImage:
        """Fetch and verify one released image, or raise.

        This is where the supply-chain check happens, and it happens before
        anybody is told an update is available: the bytes are compared
        against the SHA-256 the index names, and an image that does not match
        is never held, never offered and never served.

        The MD5 handed to the panel is computed here, from the bytes that
        passed that check, rather than copied out of the index. ESPHome's
        HTTP update verifies MD5 and nothing else, so this makes the device's
        check a check against what Home Assistant actually holds.
        """
        async with self._lock:
            self._evict()
            if (prepared := self._images.get(release.version)) is not None:
                if prepared.release == release:
                    return prepared

            url = urljoin(INSTALLER_URL, release.path)
            if not url.startswith(INSTALLER_URL):
                # The path came out of a downloaded document. It names a file
                # on the installer site or it names nothing.
                raise FirmwareUnavailable(
                    f"firmware {release.version} is published outside the "
                    "installer site"
                )

            session = async_get_clientsession(self._hass)
            try:
                async with session.get(url, timeout=IMAGE_TIMEOUT) as response:
                    response.raise_for_status()
                    payload = await _read_bounded(response)
            except (ClientError, TimeoutError) as err:
                raise FirmwareUnavailable(
                    f"firmware {release.version} could not be downloaded: {err}"
                ) from err

            if len(payload) != release.size:
                raise FirmwareUnavailable(
                    f"firmware {release.version} is {len(payload)} bytes; the "
                    f"release index says {release.size}"
                )
            digest = hashlib.sha256(payload).hexdigest()
            if not _same_digest(digest, release.sha256):
                raise FirmwareUnavailable(
                    f"firmware {release.version} does not match its published "
                    "SHA-256 and will not be installed"
                )

            prepared = PreparedImage(
                release=release,
                payload=payload,
                md5=hashlib.md5(
                    payload, usedforsecurity=False
                ).hexdigest(),
                prepared_at=time.monotonic(),
            )
            self._images[release.version] = prepared
            _LOGGER.debug(
                "Firmware %s is verified and ready (%d bytes)",
                release.version,
                len(payload),
            )
            return prepared

    def prepared(self, version: str) -> PreparedImage | None:
        """Return a verified image already held, or None."""
        self._evict()
        return self._images.get(version)

    def _evict(self) -> None:
        """Drop images nobody can still be collecting.

        An image is held for one update window. After that the panel has
        either installed it or failed to, and in both cases a couple of
        megabytes has no business staying in memory.
        """
        now = time.monotonic()
        for version, image in list(self._images.items()):
            if now - image.prepared_at > UPDATE_TIMEOUT_SECONDS:
                del self._images[version]


async def _read_bounded(response: Any) -> bytes:
    """Read a response body, refusing to grow past one application slot.

    A body larger than that could not be written to a panel anyway, and
    reading it first to find that out is how a Home Assistant runs out of
    memory over a file it was never going to use.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await response.content.read(DOWNLOAD_CHUNK):
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise FirmwareUnavailable(
                "the published image is larger than an application slot"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _same_digest(left: str, right: str) -> bool:
    """Compare two hex digests without leaking where they differ."""
    return hmac.compare_digest(left.lower(), right.lower())


@callback
def async_firmware_index(hass: HomeAssistant) -> FirmwareIndex:
    """Return the installation's release index, creating it on first use."""
    data = hass.data.setdefault(DOMAIN, {})
    index: FirmwareIndex | None = data.get(DATA_FIRMWARE)
    if index is None:
        index = FirmwareIndex(hass)
        data[DATA_FIRMWARE] = index
    return index


class PanelFirmwareManifestView(HomeAssistantView):
    """Tell one panel which build is waiting for it, and let it fetch it."""

    url = MANIFEST_URL
    name = "api:media_controller:panel_firmware"

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the objects a request needs; there is one view per setup."""
        self._hass = hass

    async def get(self, request: web.Request, panel_id: str) -> web.Response:
        """Return the pending build for the panel this token belongs to.

        A panel asks only after it has read an `update` command naming a
        version, so the answer is about that version and no other. Anything
        else — no pending update, a different version, an image that is no
        longer held — is "nothing to do", never a different build.
        """
        registration, error = async_resolve_panel(self._hass, request, panel_id)
        if error == STATUS_WRONG_PANEL:
            return self.json({"status": STATUS_WRONG_PANEL}, status_code=403)
        if registration is None:
            return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=404)

        wanted = registration.state.commands.update_version
        if not wanted:
            return self.json({"status": STATUS_UP_TO_DATE})

        index = async_firmware_index(self._hass)
        prepared = index.prepared(wanted)
        if prepared is None:
            # The image is fetched and verified when Install is pressed, so
            # this means the window has closed or Home Assistant restarted.
            # The panel is told to do nothing rather than handed a build
            # nobody has checked.
            _LOGGER.debug(
                "Panel %s asked for firmware %s, which is no longer held",
                panel_id,
                wanted,
            )
            return self.json({"status": STATUS_NOT_READY}, status_code=503)

        nonce = index.nonces.issue(panel_id, prepared.release.version)
        return self.json(
            {
                "status": STATUS_OK,
                "version": prepared.release.version,
                "contract_version": prepared.release.contract_version,
                "size": len(prepared.payload),
                # ESPHome's HTTP update verifies MD5. The SHA-256 is what
                # Home Assistant checked the download against, and is sent so
                # that the two halves can be compared in a log.
                "md5": prepared.md5,
                "sha256": prepared.release.sha256,
                # A path rather than a URL: the panel already knows where
                # Home Assistant is — it just asked it something — and Home
                # Assistant guessing at its own external address is how a
                # device ends up fetching from somewhere it cannot reach.
                "path": IMAGE_URL.format(panel_id=panel_id, nonce=nonce),
            }
        )


class PanelFirmwareImageView(HomeAssistantView):
    """Serve one verified image to one panel, once.

    Unauthenticated because it has to be: this is the request ESPHome's OTA
    client makes, and that client sends no `Authorization` header. What
    stands in its place is the nonce, which was handed out over the
    authenticated manifest call above to the panel that owns this panel ID.
    """

    url = IMAGE_URL
    name = "api:media_controller:panel_firmware_image"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the objects a request needs; there is one view per setup."""
        self._hass = hass

    async def get(
        self,
        request: web.Request,
        panel_id: str,
        nonce: str,
    ) -> web.Response:
        """Return the image this nonce permits, and spend the nonce.

        The order is the whole of the guard: the nonce is resolved first, and
        the panel and the version come out of what it recorded when it was
        issued. Nothing in the request decides what is served.
        """
        if len(nonce) != NONCE_LENGTH:
            return self.json(
                {"status": STATUS_UNKNOWN_NONCE}, status_code=404
            )

        index = async_firmware_index(self._hass)
        permitted = index.nonces.consume(nonce)
        if permitted is None or permitted.panel_id != panel_id:
            _LOGGER.warning(
                "Refused a firmware download for panel %s: the nonce is "
                "spent, expired, or belongs to another panel",
                panel_id,
            )
            return self.json(
                {"status": STATUS_UNKNOWN_NONCE}, status_code=404
            )

        # A panel whose entry has been unloaded — removed, or its token
        # revoked and the entry taken down with it — is offered nothing, the
        # same way it is offered nothing by every other endpoint here.
        panels = self._hass.data.get(DOMAIN, {}).get(DATA_PANELS, {})
        if panel_id not in panels:
            return self.json(
                {"status": STATUS_UNKNOWN_PANEL}, status_code=404
            )

        prepared = index.prepared(permitted.version)
        if prepared is None:
            return self.json({"status": STATUS_NOT_READY}, status_code=503)

        _LOGGER.info(
            "Serving firmware %s (%d bytes) to panel %s",
            prepared.release.version,
            len(prepared.payload),
            panel_id,
        )
        return web.Response(
            body=prepared.payload,
            content_type=IMAGE_CONTENT_TYPE,
            headers={
                # An image is served once to one device and must never be
                # kept by anything in between.
                "Cache-Control": "no-store",
            },
        )


@callback
def async_setup_firmware_endpoints(hass: HomeAssistant) -> None:
    """Register the firmware endpoints and start reading the release index."""
    index = async_firmware_index(hass)
    hass.http.register_view(PanelFirmwareManifestView(hass))
    hass.http.register_view(PanelFirmwareImageView(hass))
    async_track_time_interval(hass, index.async_refresh, FIRMWARE_INDEX_INTERVAL)
    # The first read, so that a panel added minutes after Home Assistant
    # started is not told it is up to date on the strength of never having
    # looked. It is a background task because a few hundred bytes from a
    # public page must not hold up the integration setting up.
    hass.async_create_background_task(
        index.async_refresh(), f"{DOMAIN} firmware index"
    )
