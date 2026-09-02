"""Restarting the panel application from Home Assistant.

The tablet cannot be told anything, so pressing this does not reach it: it
records the moment the restart was asked for, the panel notices on its next
poll that the moment is newer than the last one it acted on, and it quits. The
watchdog on the tablet brings the application back within about two seconds.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the restart button of one panel."""
    runtime = entry.runtime_data
    if not hasattr(runtime, "state"):
        return
    async_add_entities([PanelRestartButton(entry, runtime)])


class PanelRestartButton(PanelEntity, ButtonEntity):
    """Ask the panel to restart its application."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the restart button."""
        super().__init__(entry, runtime, "restart")

    async def async_press(self) -> None:
        """Record the restart request the panel will read."""
        self._panel.request_restart()
