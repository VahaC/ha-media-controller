"""The rules behind handing a panel its bootstrap.

`panel_provision.py` is the transport: aiohttp, the config entry, the token
store. Everything it has to *decide* is here instead, and this module has no
Home Assistant imports, so those decisions can be tested without a Home
Assistant runtime — the same split `pairing.py` and `provision.py` already
have.

Four decisions live here:

* whether a discovered panel can be pushed to at all, or whether Home
  Assistant has to wait to be polled the way it always did;
* what a panel's answer about itself means, given that the answer arrives
  from a device on the network and may be anything;
* what an HTTP status from that device means to the person looking at a form;
* whether a delivery has everything it needs, and what is missing when it
  does not.

The address rules mirror the ones the device enforces on the other side, in
`components/media_controller_provision/`. They are deliberately duplicated:
the device cannot trust Home Assistant to have checked, and Home Assistant
should not send something it knows will be refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The most any single field may be, matched to what the device will store.
# A longer value is refused here rather than sent and rejected there.
MAX_URL_CHARS = 128
MAX_TOKEN_CHARS = 254
MAX_ENTITY_CHARS = 128

# The error keys these rules produce. Every one has a string in strings.json
# under config.error.
ERROR_CODE_MISMATCH = "code_mismatch"
ERROR_ALREADY_PAIRED = "panel_already_paired"
ERROR_TOO_MANY_ATTEMPTS = "too_many_attempts"
ERROR_NOT_READY = "panel_not_ready"
ERROR_UNREACHABLE = "pairing_timeout"
ERROR_REFUSED = "panel_refused"

# What the device answers with, mapped to the key above. Anything else is
# "refused": an unexpected status from a device on the network is not
# something to guess about.
_STATUS_ERRORS: dict[int, str] = {
    403: ERROR_CODE_MISMATCH,
    409: ERROR_ALREADY_PAIRED,
    429: ERROR_TOO_MANY_ATTEMPTS,
    503: ERROR_NOT_READY,
}

# Why a delivery cannot be attempted. Unlike the keys above these never reach
# a form — nobody is looking at one by the time delivery runs — so they are
# log lines, and they say what is missing rather than what to do about it.
BLOCKED_NOT_PENDING = "no pairing is waiting for this panel"
BLOCKED_NO_ADDRESS = "the panel serves no provisioning endpoint"
BLOCKED_NO_URL = "Home Assistant has no internal URL to give the panel"
BLOCKED_NO_CONFIG_ENTITY = "the panel's config sensor does not exist"


def error_for_status(status: int) -> str | None:
    """Return what one answer from a panel means, or None when it agreed."""
    if status == 200:
        return None
    return _STATUS_ERRORS.get(status, ERROR_REFUSED)


def normalise_url(value: Any) -> str:
    """Return an address a panel will accept, or an empty string.

    The panel appends a path to whatever it is given, so it is given an origin
    and nothing else: a value carrying a path of its own could redirect a
    request meant for `/api/states/` somewhere unrelated. A trailing slash is
    the one thing forgiven, because it is what a person types.
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip().rstrip("/")
    if len(candidate) > MAX_URL_CHARS:
        return ""
    if any(character.isspace() for character in candidate):
        return ""
    for scheme in ("http://", "https://"):
        if candidate.startswith(scheme):
            rest = candidate[len(scheme) :]
            return candidate if rest and "/" not in rest else ""
    return ""


def is_plausible_token(value: Any) -> bool:
    """Return whether this could be a Home Assistant long-lived token.

    A JWT: three base64url segments and two dots. The point is not to validate
    the token — only Home Assistant can — but to be sure that what goes into a
    request header cannot contain a newline or a space.
    """
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_CHARS:
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    return all(part and set(part) <= allowed for part in parts)


def is_plausible_entity_id(value: Any) -> bool:
    """Return whether this is a `<domain>.<object_id>` a panel can read."""
    if not isinstance(value, str) or not value or len(value) > MAX_ENTITY_CHARS:
        return False
    parts = value.split(".")
    if len(parts) != 2:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    return all(part and set(part) <= allowed for part in parts)


@dataclass(frozen=True, slots=True)
class PanelIdentity:
    """What a panel says about itself before anything has been agreed.

    None of it is a secret and none of it is trusted: it is read defensively
    because it arrives from a device on the network, and it is used for one
    thing only — deciding whether the address Home Assistant found really is
    the panel whose code somebody is about to type.
    """

    panel_id: str
    profile: str
    name: str
    version: str
    contract_version: int
    paired: bool


def read_identity(payload: Any) -> PanelIdentity | None:
    """Return what a panel reported about itself, or None if it reported none.

    None covers every way this can fail to be useful — a body that is not an
    object, a device that is not a panel, a panel too old to answer — because
    the caller does the same thing in all of them: fall back to waiting to be
    polled.
    """
    if not isinstance(payload, dict):
        return None
    panel_id = payload.get("panel_id")
    if not isinstance(panel_id, str) or not panel_id.strip():
        return None

    contract = payload.get("contract_version")
    return PanelIdentity(
        panel_id=panel_id.strip(),
        profile=_text(payload.get("profile")),
        name=_text(payload.get("name")),
        version=_text(payload.get("version")),
        contract_version=(
            int(contract)
            if isinstance(contract, (int, float)) and not isinstance(contract, bool)
            else 0
        ),
        paired=bool(payload.get("paired")),
    )


def _text(value: Any) -> str:
    """Return a string field of a payload, using "" for anything else."""
    return value.strip() if isinstance(value, str) else ""


def panel_accepts_push(
    port: int,
    identity: PanelIdentity | None,
    panel_id: str,
) -> bool:
    """Return whether the bootstrap may be posted to this address.

    Three things have to hold, and every one of them fails safe: a device that
    advertises no port serves nothing — that is the T560 tablet, which
    advertises port 0 for exactly this reason; a device that does not answer
    may simply still be booting; and a device that answers for another panel
    is not the one being paired. In all three cases pairing still works, the
    long way round, and nothing is sent to the wrong device.
    """
    if port <= 0 or identity is None or not panel_id:
        return False
    return identity.panel_id.strip().lower() == panel_id.strip().lower()


@dataclass(frozen=True, slots=True)
class Delivery:
    """One bootstrap, ready to be posted to one panel."""

    host: str
    port: int
    code: str
    ha_url: str
    token: str
    config_entity: str

    def as_body(self) -> dict[str, str]:
        """Return the request body, which is the whole of what is sent."""
        return {
            "code": self.code,
            "ha_url": self.ha_url,
            "token": self.token,
            "config_entity": self.config_entity,
        }


def plan_delivery(
    *,
    host: str,
    port: int,
    pending: tuple[str, str] | None,
    ha_url: str | None,
    config_entity: str,
) -> tuple[Delivery | None, str | None]:
    """Return the bootstrap to send, or why there is nothing to send.

    The order of the checks is the order in which they stop mattering. A panel
    with nothing pending is the ordinary case — every reload of every panel
    that was set up long ago — and it is not a problem, so it is settled
    first and reported as a plain reason rather than a failure. The two that
    follow are: the token has been minted by then, and the caller has to
    revoke it.
    """
    if pending is None:
        return None, BLOCKED_NOT_PENDING
    if not host or port <= 0:
        return None, BLOCKED_NO_ADDRESS

    code, token = pending
    address = normalise_url(ha_url)
    if not address:
        return None, BLOCKED_NO_URL
    if not is_plausible_entity_id(config_entity):
        return None, BLOCKED_NO_CONFIG_ENTITY
    if not is_plausible_token(token):
        # Not reachable from a token this integration minted, and worth
        # refusing anyway: a malformed one would be put in a request header.
        return None, BLOCKED_NOT_PENDING

    return (
        Delivery(
            host=host,
            port=port,
            code=code,
            ha_url=address,
            token=token,
            config_entity=config_entity,
        ),
        None,
    )
