"""The endpoint a panel reports its own hardware state to.

Home Assistant cannot ask a tablet anything: a panel serves nothing and is
reachable only while it is polling. Battery charge, whether the display is
lit, and what backlight level it is at are therefore pushed by the panel, on a
change and once a minute regardless, and this view turns each report into the
entities on the panel's device.

Unlike the provisioning endpoint next to it, this one is authenticated: a
reporting panel already holds the token Home Assistant minted for it. The
token alone is not enough, though. Every panel gets a Home Assistant user of
its own, so the report is accepted only when the caller is the user that owns
that panel — one panel cannot write another one's battery level, and no other
token in the installation can write any of them.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DATA_PANELS, DOMAIN
from .panel_state import PanelState

_LOGGER = logging.getLogger(__name__)

STATUS_URL = "/api/media_controller/panel_status"

STATUS_OK = "ok"
STATUS_UNKNOWN_PANEL = "unknown_panel"
STATUS_WRONG_PANEL = "wrong_panel"
STATUS_INVALID_REPORT = "invalid_report"


class PanelRegistration:
    """One loaded panel, as the status endpoint needs to see it."""

    def __init__(
        self,
        state: PanelState,
        user_id: str,
        entry_id: str,
    ) -> None:
        """Hold the state to update, the user allowed to, and the device."""
        self.state = state
        self.user_id = user_id
        self.entry_id = entry_id


def async_register_panel(
    hass: HomeAssistant,
    panel_id: str,
    state: PanelState,
    user_id: str,
    entry_id: str,
) -> None:
    """Make a loaded panel reachable by the status endpoint."""
    hass.data[DOMAIN][DATA_PANELS][panel_id] = PanelRegistration(
        state, user_id, entry_id
    )


def async_unregister_panel(hass: HomeAssistant, panel_id: str) -> None:
    """Drop a panel that is being unloaded."""
    hass.data.get(DOMAIN, {}).get(DATA_PANELS, {}).pop(panel_id, None)


def async_resolve_panel(
    hass: HomeAssistant,
    request: web.Request,
    panel_id: str,
) -> tuple[PanelRegistration | None, str | None]:
    """Return the loaded panel a request may act on, or why it may not.

    This is the one ownership rule of every authenticated panel endpoint, in
    one place: a panel is reachable only while its entry is loaded, and only
    the Home Assistant user created for that panel may speak for it. A second
    endpoint gets exactly the isolation the first one already has, rather than
    a second implementation of it that can drift.

    The failure is returned rather than raised so that each endpoint keeps
    control of its own answers.
    """
    panels: dict[str, PanelRegistration] = hass.data.get(DOMAIN, {}).get(
        DATA_PANELS, {}
    )
    registration = panels.get(panel_id)
    if registration is None:
        return None, STATUS_UNKNOWN_PANEL

    user = request.get("hass_user")
    if user is None or user.id != registration.user_id:
        _LOGGER.warning(
            "Refused a request for panel %s from another account", panel_id
        )
        return None, STATUS_WRONG_PANEL
    return registration, None


class PanelStatusView(HomeAssistantView):
    """Accept one panel's report about itself."""

    url = STATUS_URL
    name = "api:media_controller:panel_status"

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the objects the request needs; there is one view per setup."""
        self._hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Record a status report from the panel that owns this token."""
        try:
            payload: dict[str, Any] = await request.json()
        except ValueError:
            return self.json(
                {"status": STATUS_INVALID_REPORT}, status_code=400
            )
        if not isinstance(payload, dict):
            return self.json(
                {"status": STATUS_INVALID_REPORT}, status_code=400
            )

        panel_id = str(payload.get("panel_id") or "").strip()
        if not panel_id:
            return self.json(
                {"status": STATUS_INVALID_REPORT}, status_code=400
            )

        registration, error = async_resolve_panel(
            self._hass, request, panel_id
        )
        if error == STATUS_WRONG_PANEL:
            return self.json({"status": STATUS_WRONG_PANEL}, status_code=403)
        if registration is None:
            return self.json(
                {"status": STATUS_UNKNOWN_PANEL}, status_code=404
            )

        registration.state.apply_report(payload)
        self._async_update_device(registration)
        return self.json({"status": STATUS_OK})

    def _async_update_device(self, registration: PanelRegistration) -> None:
        """Put what a report says about the panel itself on its device.

        Both facts here belong on the device rather than in an entity: they
        are the same kind of fact as the model, and neither deserves a row in
        the history database.

        * the application version is what tells you which tablet in a house is
          behind;
        * the editor address becomes the link on the device page, so the way
          to the panel's own layout editor is where somebody looking at that
          panel already is, instead of a port they have to remember.
        """
        status = registration.state.status
        registry = dr.async_get(self._hass)
        device = registry.async_get_device(
            identifiers={(DOMAIN, registration.entry_id)}
        )
        if device is None:
            return

        changes: dict[str, Any] = {}
        if status.app_version and device.sw_version != status.app_version:
            changes["sw_version"] = status.app_version
        # A panel that serves no editor — a tablet with `web_port=0`, or a
        # client that has none at all — reports no address, and the link is
        # then taken off the device rather than left pointing at a port
        # nothing answers on.
        configuration_url = status.editor_url or None
        if device.configuration_url != configuration_url:
            changes["configuration_url"] = configuration_url
        if changes:
            registry.async_update_device(device.id, **changes)
