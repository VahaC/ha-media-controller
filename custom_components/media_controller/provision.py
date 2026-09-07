"""Handing a panel its access token over HTTP.

A panel has no keyboard, so the token cannot be typed on it, and Home
Assistant cannot push anything to a tablet that serves nothing. The panel
therefore asks, and Home Assistant answers only while a pairing has been
approved:

1. a panel with no token shows a six-digit code and polls this endpoint;
2. a poll from a panel Home Assistant does not know is that panel asking to be
   added, and is offered as a discovered device. It is the whole reason no
   setup form asks for a panel ID: the poll carries the identifier, and a
   panel has no screen to read one off;
3. Home Assistant asks the person to type the code — as the first step of
   adding the panel, or through a reauthentication prompt on a panel that
   already exists;
4. the first poll carrying the right code confirms the pairing, which is what
   lets the setup form move on to the room controls;
5. the token follows on the first poll after the panel's config entry and its
   config sensor exist, once. While they do not, the answer is
   `pairing_pending` and the panel simply keeps asking.

The endpoint is unauthenticated because the caller has no credentials yet.
What protects it is in pairing.py: it answers only for an armed pairing, only
for a few minutes, only for a code shown on the device's own screen, and only
once. This module is the transport around those rules.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_PANEL_ID, DOMAIN
from .entries import is_panel_entry
from .pairing import (
    STATE_COLLECTED,
    STATUS_ALREADY_PAIRED,
    STATUS_INVALID_CODE,
    STATUS_PAIRING_PENDING,
    STATUS_PAIRING_REQUIRED,
    STATUS_UNKNOWN_PANEL,
    PairingStore,
)

_LOGGER = logging.getLogger(__name__)

PROVISION_URL = "/api/media_controller/provision"

# How long a panel that nobody has added waits before it is offered again. It
# polls every three seconds, and one card per poll would be a stream rather
# than an offer; a card that was dismissed on purpose has to come back, or a
# panel could only be added by restarting Home Assistant.
OFFER_INTERVAL = 300.0


@callback
def async_panel_entry(hass: HomeAssistant, panel_id: str) -> ConfigEntry | None:
    """Return the configured panel with this identifier."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if is_panel_entry(entry) and entry.data.get(CONF_PANEL_ID) == panel_id:
            return entry
    return None


@callback
def _config_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the panel's config sensor.

    Home Assistant derives an entity ID from the device name, so a second
    panel with the same name gets a suffix. Telling the panel which entity to
    read removes the guesswork, and with it a whole class of two-tablet bugs.
    """
    return (
        er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_config"
        )
        or ""
    )


class PanelProvisionView(HomeAssistantView):
    """Answer a panel asking for its token."""

    url = PROVISION_URL
    name = "api:media_controller:provision"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, pairings: PairingStore) -> None:
        """Hold the objects the request needs; there is one view per setup."""
        self._hass = hass
        self._pairings = pairings
        # When each unknown panel may be offered again, by panel ID.
        self._offered: dict[str, float] = {}

    async def post(self, request: web.Request) -> web.Response:
        """Deliver the token of an approved pairing."""
        try:
            payload: dict[str, Any] = await request.json()
        except ValueError:
            return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=400)

        panel_id = str(payload.get("panel_id") or "").strip()
        code = str(payload.get("code") or "").strip()
        if not panel_id or not code:
            return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=400)

        if not self._pairings.confirm(panel_id, code):
            return self._refuse(panel_id)

        # The code was right. The token can only be handed over once the
        # entities it is meant to read exist, which during setup is after the
        # person finishes the rest of the form. Until then the panel is told
        # to keep asking, and the approval stays open.
        entry = async_panel_entry(self._hass, panel_id)
        config_entity = "" if entry is None else _config_entity_id(
            self._hass, entry
        )
        if not config_entity:
            return self.json(
                {"status": STATUS_PAIRING_PENDING}, status_code=202
            )

        if (token := self._pairings.collect(panel_id)) is None:
            # Another request of the same panel got there first.
            return self.json(
                {"status": STATUS_ALREADY_PAIRED}, status_code=403
            )

        _LOGGER.info("Panel %s collected its access token", panel_id)
        return self.json({"token": token, "config_entity": config_entity})

    def _refuse(self, panel_id: str) -> web.Response:
        """Answer a poll that carried no usable code."""
        state = self._pairings.state(panel_id)
        if state is not None:
            # An approval exists or has just been used, so this was the wrong
            # code, or a token that was already handed over.
            status = (
                STATUS_ALREADY_PAIRED
                if state == STATE_COLLECTED
                else STATUS_INVALID_CODE
            )
            return self.json({"status": status}, status_code=403)

        entry = async_panel_entry(self._hass, panel_id)
        if entry is None:
            # Nothing to pair with yet, so this poll is the panel asking to be
            # added, and it carries the one thing the setup form used to have
            # to be told: which panel it is.
            self._async_offer(panel_id)
            return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=404)

        # The panel exists but nobody has approved a pairing. Ask, through the
        # standard reauthentication prompt, so that a panel which lost its
        # token is re-paired without being added again. Home Assistant keeps
        # one flow per entry, so repeated polling does not pile up.
        entry.async_start_reauth(self._hass)
        return self.json({"status": STATUS_PAIRING_REQUIRED}, status_code=403)

    @callback
    def _async_offer(self, panel_id: str) -> None:
        """Put a panel nobody has added in front of somebody.

        A panel that cannot announce itself over mDNS still has to poll this
        endpoint before it can hold a token, so the poll is a discovery in its
        own right: it says a panel exists, and it says which one. Offering it
        here is what lets the setup form ask only for the six digits on
        the screen: the identifier arrives by itself, and it never has to
        be read off a device that does not display one.

        The flow is started detached, because it runs to its first form before
        returning and this poll is a panel waiting for an answer.
        """
        now = time.monotonic()
        if now < self._offered.get(panel_id, 0.0):
            return
        self._offered[panel_id] = now + OFFER_INTERVAL

        _LOGGER.debug("Offering panel %s as a discovered device", panel_id)
        self._hass.async_create_task(
            self._hass.config_entries.flow.async_init(
                DOMAIN,
                # A card that is already up, or a form somebody is filling
                # in, ends this flow at async_set_unique_id rather than
                # stacking a second card on the first.
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_PANEL_ID: panel_id},
            ),
            f"media_controller discovery {panel_id}",
        )
