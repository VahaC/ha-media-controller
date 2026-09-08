"""Handing a panel its bootstrap by asking it, rather than waiting to be asked.

`provision.py` next to this file is the older half of pairing and is still the
only one a T560 tablet uses: the client knows where Home Assistant is, so it
polls, and Home Assistant answers.

An ESP32 flashed from the factory image cannot do that. The whole point of one
universal image is that nothing personal is compiled into it, and an address is
personal — so the device has none to poll. It announces itself over mDNS
instead, on a real port, and Home Assistant posts the three things it needs to
that port once somebody has typed the six digits on its screen:

* where Home Assistant is, taken from the address Home Assistant already
  advertises for itself, or typed in when it cannot work one out;
* the panel's own access token;
* the entity ID of its config sensor, which is everything else.

Two moments, deliberately, and in this order:

1. **verify**, during the flow, before anything is created. The panel says
   whether the code on its screen is the one that was typed. A mistyped code
   therefore costs nothing and leaves no token and no Home Assistant user
   behind;
2. **deliver**, after the config entry is set up, because the config sensor it
   names has to exist first. That is why this does not happen in the flow: the
   entity is created by the entry the flow is still in the middle of writing.

The token is never put in a URL and never logged. Everything travels in the
body of a POST to one device on the local network.

What this module decides is in `bootstrap.py`, which has no Home Assistant
imports and is tested on its own. This is the transport around it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .bootstrap import (
    BLOCKED_NO_ADDRESS,
    ERROR_UNREACHABLE,
    PanelIdentity,
    error_for_status,
    panel_accepts_push,
    plan_delivery,
    read_identity,
)
from .const import (
    CONF_HA_URL,
    CONF_HOST,
    CONF_PANEL_ID,
    CONF_PANEL_PORT,
    CONF_REFRESH_TOKEN_ID,
    CONF_USER_ID,
    DATA_PROVISIONING,
    DEFAULT_PANEL_PORT,
    DOMAIN,
)
from .pairing import PairingStore
from .tokens import async_revoke_panel_token

_LOGGER = logging.getLogger(__name__)

INFO_PATH = "/api/provision/info"
VERIFY_PATH = "/api/provision/verify"
APPLY_PATH = "/api/provision"

# A panel on the same network answers in milliseconds. This is long enough for
# a device that is busy redrawing its screen and short enough that a form does
# not appear to hang when nothing is listening.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)

# Delivery happens after the entry is set up, so nobody is watching a form. It
# is worth a few attempts: a panel that has just been discovered may still be
# finishing its own boot.
DELIVERY_ATTEMPTS = 4
DELIVERY_BACKOFF = 3.0


def _base_url(host: str, port: int) -> str:
    """Return the origin of one panel's own web server."""
    return f"http://{host}:{port or DEFAULT_PANEL_PORT}"


async def async_panel_identity(
    hass: HomeAssistant,
    host: str,
    port: int,
) -> PanelIdentity | None:
    """Return what the panel at this address is, or None if it is not one."""
    if not host or port <= 0:
        return None
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{_base_url(host, port)}{INFO_PATH}", timeout=REQUEST_TIMEOUT
        ) as response:
            if response.status != 200:
                return None
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        _LOGGER.debug("No provisioning endpoint at %s", host)
        return None
    return read_identity(payload)


async def async_panel_accepts_push(
    hass: HomeAssistant,
    host: str,
    port: int,
    panel_id: str,
) -> bool:
    """Return whether this panel can be handed its bootstrap directly."""
    if port <= 0:
        return False
    identity = await async_panel_identity(hass, host, port)
    if identity is not None and identity.panel_id.strip().lower() != (
        panel_id.strip().lower()
    ):
        _LOGGER.warning(
            "The address discovered for panel %s answers for %s instead",
            panel_id,
            identity.panel_id,
        )
    return panel_accepts_push(port, identity, panel_id)


async def _async_post(
    hass: HomeAssistant,
    host: str,
    port: int,
    path: str,
    body: dict[str, Any],
) -> str | None:
    """Post one provisioning request, returning an error key or None."""
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            f"{_base_url(host, port)}{path}",
            json=body,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            return error_for_status(response.status)
    except (aiohttp.ClientError, TimeoutError):
        return ERROR_UNREACHABLE


async def async_verify_code(
    hass: HomeAssistant,
    host: str,
    port: int,
    code: str,
) -> str | None:
    """Ask the panel whether this is the code on its screen.

    Nothing is created and nothing is sent: this is the step that makes a
    wrong code free.
    """
    return await _async_post(hass, host, port, VERIFY_PATH, {"code": code})


@callback
def async_internal_url(hass: HomeAssistant) -> str | None:
    """Return the address a panel on this network should use, if there is one.

    Asked of Home Assistant rather than assembled here: it knows what it is
    reachable as, and a URL built out of a listening address would be wrong
    behind a proxy and wrong again in a container. External and cloud
    addresses are refused — a panel two metres away must not reach Home
    Assistant through the internet — and an IP address is accepted, because on
    a house network that is often the only name that resolves.
    """
    try:
        return get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
            allow_ip=True,
            require_ssl=False,
            require_standard_port=False,
        ).rstrip("/")
    except NoURLAvailableError:
        _LOGGER.debug("Home Assistant knows no internal URL to give a panel")
        return None


@callback
def async_config_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the entity ID of one panel's config sensor.

    The same lookup `provision.py` does, and for the same reason: Home
    Assistant derives an entity ID from the device name, so a second panel
    with the same name gets a suffix, and telling the panel which entity to
    read removes the guesswork.
    """
    return (
        er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_config"
        )
        or ""
    )


async def async_deliver_bootstrap(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Send a freshly paired panel its bootstrap, once its entities exist.

    Called from the entry's own setup. It does nothing at all unless a pairing
    is waiting with a token attached, so a panel that polls, a panel that was
    set up long ago and a reload of either all pass straight through.

    A panel that **serves no provisioning endpoint** is left alone: it is a
    panel that collects its own token by polling, and its pairing is what it
    collects. That is not a failure and must not be treated as one.

    A panel that has an address and **cannot be reached at it** is a different
    thing, and there the token is revoked rather than left lying about: a
    credential minted for a device which never received it is exactly the
    orphan this has to avoid. The entry survives, and the standard
    reauthentication prompt asks for a new code.
    """
    pairings: PairingStore | None = hass.data.get(DOMAIN, {}).get(
        DATA_PROVISIONING
    )
    panel_id = entry.data.get(CONF_PANEL_ID, "")
    if pairings is None or not panel_id:
        return

    pending = pairings.pending(panel_id)
    delivery, blocked = plan_delivery(
        host=entry.data.get(CONF_HOST, ""),
        port=int(entry.data.get(CONF_PANEL_PORT) or 0),
        pending=pending,
        ha_url=entry.data.get(CONF_HA_URL) or async_internal_url(hass),
        config_entity=async_config_entity_id(hass, entry),
    )
    if delivery is None:
        if pending is None:
            # The ordinary case: nothing was waiting. Every reload of every
            # panel that polls, or was set up long ago, lands here.
            await _async_check_still_paired(hass, entry)
            return
        if blocked == BLOCKED_NO_ADDRESS:
            # Not a failure, and treating it as one was a trap that closed on
            # itself. "No address" means this panel serves no provisioning
            # endpoint, which is the whole description of a panel that
            # collects its own token by polling: the T560 tablet always, and
            # an ESP32 whose port could not be probed at the moment somebody
            # typed the code.
            #
            # Abandoning here revoked the token that had just been minted and
            # started reauthentication, which minted another one, which was
            # abandoned in turn. The panel sat on its pairing screen through
            # all of it, because the one thing that would have ended it --
            # the token waiting to be collected -- was destroyed a moment
            # after it was created, every time round.
            #
            # So the pairing is left exactly where it is. The panel claims it
            # on its next poll, and if there is no panel to claim it the
            # record expires on its own inside five minutes and takes the
            # token with it.
            _LOGGER.debug(
                "%s has no provisioning endpoint; its token is left for it "
                "to collect by polling",
                entry.title,
            )
            return
        _LOGGER.error("Cannot provision %s: %s", entry.title, blocked)
        await _async_abandon(hass, entry, pairings, panel_id)
        return

    error: str | None = ERROR_UNREACHABLE
    for attempt in range(DELIVERY_ATTEMPTS):
        error = await _async_post(
            hass,
            delivery.host,
            delivery.port,
            APPLY_PATH,
            delivery.as_body(),
        )
        if error != ERROR_UNREACHABLE:
            break
        if attempt < DELIVERY_ATTEMPTS - 1:
            await asyncio.sleep(DELIVERY_BACKOFF)

    if error is None:
        # Consumed only now, so a delivery that failed halfway leaves the
        # pairing usable rather than spent.
        pairings.collect(panel_id)
        _LOGGER.info("Panel %s was given its access token", entry.title)
        return

    _LOGGER.error(
        "Could not hand %s its access token (%s); the token has been revoked "
        "and the panel has to be paired again",
        entry.title,
        error,
    )
    await _async_abandon(hass, entry, pairings, panel_id)


async def _async_check_still_paired(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Ask a reachable panel whether it still holds a token, and act if not.

    The pairing store lives in memory, so a Home Assistant restarted between
    writing a panel's entry and delivering its bootstrap has forgotten what it
    owed. Nothing else would notice: a panel that never received a token never
    polls, never reports, and simply sits on its pairing screen while Home
    Assistant believes it is configured.

    A panel that serves an identity route can be asked outright, and it is
    asked once per setup — one local request, only for a panel that advertises
    a port. A `no` starts the ordinary reauthentication prompt, which mints a
    fresh token and revokes the one that was never delivered.
    """
    host = entry.data.get(CONF_HOST, "")
    port = int(entry.data.get(CONF_PANEL_PORT) or 0)
    if not host or port <= 0 or not entry.data.get(CONF_REFRESH_TOKEN_ID):
        return

    identity = await async_panel_identity(hass, host, port)
    if identity is None or identity.paired:
        # Unreachable says nothing — the panel may be off — and paired is the
        # answer this is hoping for.
        return

    _LOGGER.warning(
        "%s holds no access token, so one it was owed never arrived; "
        "asking for its pairing code again",
        entry.title,
    )
    entry.async_start_reauth(hass)


async def _async_abandon(
    hass: HomeAssistant,
    entry: ConfigEntry,
    pairings: PairingStore,
    panel_id: str,
) -> None:
    """Undo a pairing whose token never arrived.

    The token is revoked and the IDs that name it are cleared, so nothing is
    left behind that could still be used and nothing points at a credential
    that no longer exists. Then the panel is asked for a code again through
    the reauthentication prompt, which is the same place a panel that lost its
    token ends up.
    """
    pairings.discard(panel_id)
    await async_revoke_panel_token(
        hass,
        entry.data.get(CONF_USER_ID),
        entry.data.get(CONF_REFRESH_TOKEN_ID),
    )
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_REFRESH_TOKEN_ID: "",
            CONF_USER_ID: "",
        },
    )
    entry.async_start_reauth(hass)
