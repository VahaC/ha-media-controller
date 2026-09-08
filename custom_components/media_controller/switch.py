"""The switch a panel owns."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the display switch of one panel."""
    async_add_entities([PanelDisplaySwitch(entry, entry.runtime_data)])


class PanelDisplaySwitch(PanelEntity, SwitchEntity):
    """The backlight of the tablet the panel runs on.

    Turning it here is the same act as pressing the Power button on the
    tablet, and both are visible in the other place: the request travels in
    the panel's configuration, the tablet applies it, and it reports what its
    display actually did. Until that report arrives the switch shows what was
    asked for, so a tap does not appear to do nothing for a second.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the display switch of one panel."""
        super().__init__(entry, runtime, "screen")

    @property
    def available(self) -> bool:
        """Return whether the tablet is reporting its display state."""
        return self._panel.is_online() and self._panel.status.display_known

    @property
    def is_on(self) -> bool:
        """Return whether the display is lit."""
        return self._panel.status.display_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Ask the panel to light its display."""
        self._panel.request_display(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Ask the panel to turn its display off."""
        self._panel.request_display(False)
