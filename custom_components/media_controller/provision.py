"""Handing a panel its access token over HTTP.

A panel has no keyboard, so the token cannot be typed on it, and Home
Assistant cannot push anything to a tablet that serves nothing. The panel
therefore asks, and Home Assistant answers only while a pairing has been
approved:

1. a panel with no token shows a six-digit code and polls this endpoint;
2. Home Assistant asks the person to type that code — as the first step of
   adding the panel, or through a reauthentication prompt on a panel that
   already exists;
3. the first poll carrying the right code confirms the pairing, which is what
   lets the setup form move on to the room controls;
4. the token follows on the first poll after the panel's config entry and its
   config sensor exist, once. While they do not, the answer is
   `pairing_pending` and the panel simply keeps asking.

The endpoint is unauthenticated because the caller has no credentials yet.
What protects it is in pairing.py: it answers only for an armed pairing, only
for a few minutes, only for a code shown on the device's own screen, and only
once. This module is the transport around those rules.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
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
            # Nothing to pair with. The panel shows "add me in Home Assistant".
            return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=404)

        # The panel exists but nobody has approved a pairing. Ask, through the
        # standard reauthentication prompt, so that a panel which lost its
        # token is re-paired without being added again. Home Assistant keeps
        # one flow per entry, so repeated polling does not pile up.
        entry.async_start_reauth(self._hass)
        return self.json({"status": STATUS_PAIRING_REQUIRED}, status_code=403)
