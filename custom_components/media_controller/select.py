"""Which page the panel is showing, and sending it to another one.

The tablet reports the page a person navigated to, and accepts a request to
show a different one. That makes the panel addressable from an automation:
a doorbell can put the room page in front of whoever walks past, and the panel
returns to the player when someone touches it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity
from .panel_state import PAGES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the page selector of one panel."""
    runtime = entry.runtime_data
    if not hasattr(runtime, "state"):
        return
    async_add_entities([PanelPageSelect(entry, runtime)])


class PanelPageSelect(PanelEntity, SelectEntity):
    """The page the panel is on."""

    _attr_options = list(PAGES)

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the page selector."""
        super().__init__(entry, runtime, "page")

    @property
    def available(self) -> bool:
        """Return whether the tablet has reported which page it is on."""
        return self._panel.is_online() and bool(self._panel.status.page)

    @property
    def current_option(self) -> str | None:
        """Return the page the panel last reported."""
        return self._panel.status.page or None

    async def async_select_option(self, option: str) -> None:
        """Ask the panel to show another page."""
        if not self._panel.request_page(option):
            raise ServiceValidationError(f"{option} is not a panel page")
