"""The endpoint a panel keeps a copy of its own grid at.

Why this is an endpoint of its own rather than another block on the config
sensor: the config sensor is polled every `poll_interval_ms` — once a second
by default — and a layout of a hundred cards is several kilobytes. Sending it
down that channel would put the backup on the wire every second for data that
is read twice in the life of a panel. Keeping it out also keeps it out of
`revision`, so saving a layout cannot make the panel rebuild the page it has
just saved.

Storage is `Store` and not the config entry. Writing to entry data or options
updates the entry, which reloads it and rebuilds the config sensor — a
re-layout on the panel at the exact moment it saved one.

Authentication is the status endpoint's, unchanged: a panel presents the token
it was handed when it paired, and Home Assistant accepts the request only from
the Home Assistant user created for **that** panel. One panel can neither read
nor overwrite another's layout. That check lives in `status.py` and is called
from here rather than written a second time.

The rules about what may be stored — that the blob is opaque, and how large it
may be — are in `layout_backup.py`, which has no Home Assistant imports so
that they can be tested without a runtime.
"""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DATA_LAYOUTS, DOMAIN
from .layout_backup import MAX_LAYOUT_BYTES, LayoutBackups, layout_is_too_large
from .status import (
    STATUS_UNKNOWN_PANEL,
    STATUS_WRONG_PANEL,
    async_resolve_panel,
)

_LOGGER = logging.getLogger(__name__)

LAYOUT_URL = "/api/media_controller/panel_layout/{panel_id}"

STORAGE_KEY = f"{DOMAIN}.panel_layouts"
STORAGE_VERSION = 1

STATUS_OK = "ok"
STATUS_NO_LAYOUT = "no_layout"
STATUS_TOO_LARGE = "too_large"
STATUS_UNREADABLE = "unreadable"

# The blob is returned exactly as it arrived. It is text as far as this
# integration is concerned, and naming a content type it never parsed would be
# a claim it has not checked.
LAYOUT_CONTENT_TYPE = "text/plain"


class PanelLayoutStore:
    """The saved grid of every panel, persisted through `Store`."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Prepare the store without reading it; nothing needs it at setup."""
        self._store: Store[dict[str, str]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._backups: LayoutBackups | None = None

    async def _async_backups(self) -> LayoutBackups:
        """Return the stored layouts, reading the file once."""
        if self._backups is None:
            self._backups = LayoutBackups(await self._store.async_load())
        return self._backups

    async def async_get(self, panel_id: str) -> str | None:
        """Return one panel's saved layout, or None if it never saved one."""
        return (await self._async_backups()).get(panel_id)

    async def async_set(self, panel_id: str, layout: str) -> None:
        """Replace one panel's saved layout, writing only a real change."""
        backups = await self._async_backups()
        if backups.set(panel_id, layout):
            await self._store.async_save(backups.as_stored())


def async_layout_store(hass: HomeAssistant) -> PanelLayoutStore:
    """Return the installation's layout store, creating it on first use."""
    data = hass.data.setdefault(DOMAIN, {})
    store = data.get(DATA_LAYOUTS)
    if store is None:
        store = PanelLayoutStore(hass)
        data[DATA_LAYOUTS] = store
    return store


class PanelLayoutView(HomeAssistantView):
    """Read and write the saved grid of one panel."""

    url = LAYOUT_URL
    name = "api:media_controller:panel_layout"

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the objects a request needs; there is one view per setup."""
        self._hass = hass

    def _refuse(self, error: str) -> web.Response:
        """Turn a failed ownership check into the answer it deserves."""
        if error == STATUS_WRONG_PANEL:
            return self.json({"status": STATUS_WRONG_PANEL}, status_code=403)
        return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=404)

    async def get(self, request: web.Request, panel_id: str) -> web.Response:
        """Return the layout this panel last saved, byte for byte."""
        _registration, error = async_resolve_panel(
            self._hass, request, panel_id
        )
        if error is not None:
            return self._refuse(error)

        layout = await async_layout_store(self._hass).async_get(panel_id)
        if layout is None:
            return self.json({"status": STATUS_NO_LAYOUT}, status_code=404)
        return web.Response(text=layout, content_type=LAYOUT_CONTENT_TYPE)

    async def put(self, request: web.Request, panel_id: str) -> web.Response:
        """Store a copy of the layout this panel just saved.

        The body is not read as JSON and not validated against any shape. It
        is the client's own format, and this is a safe deposit box rather than
        a second opinion about what belongs in it.
        """
        _registration, error = async_resolve_panel(
            self._hass, request, panel_id
        )
        if error is not None:
            return self._refuse(error)

        # Checked before the body is read as well as after: a declared length
        # stops an oversized upload at the door, and the second check catches
        # a request that declared nothing.
        declared = request.content_length
        if declared is not None and declared > MAX_LAYOUT_BYTES:
            return self.json({"status": STATUS_TOO_LARGE}, status_code=413)
        try:
            body = await request.text()
        except (ValueError, UnicodeDecodeError):
            return self.json({"status": STATUS_UNREADABLE}, status_code=400)
        if layout_is_too_large(body):
            return self.json({"status": STATUS_TOO_LARGE}, status_code=413)

        await async_layout_store(self._hass).async_set(panel_id, body)
        _LOGGER.debug(
            "Panel %s saved a layout of %d bytes", panel_id, len(body)
        )
        return self.json({"status": STATUS_OK})


def async_setup_layout_endpoint(hass: HomeAssistant) -> None:
    """Register the layout endpoint and the store behind it."""
    async_layout_store(hass)
    hass.http.register_view(PanelLayoutView(hass))
