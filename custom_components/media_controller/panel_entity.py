"""Common behavior of the entities a panel device owns itself.

These are not proxies. A proxy mirrors something else in Home Assistant; the
entities below describe the tablet — its battery, its display, its settings,
and the one button that restarts its application.

Two kinds live here, and they differ in when they are available:

* a **setting** is what Home Assistant wants, so it is always available. It
  keeps its value while the tablet is asleep, unplugged, or being reflashed,
  and the panel adopts it the next time it polls;
* a **reading** is what the panel last reported, so it is available only
  while a report is recent. Showing the last known battery level of a tablet
  that has been off for a day would be worse than showing nothing.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity

from .const import CONF_PANEL_SETTINGS, panel_entity_unique_id
from .panel_state import PanelSettings, PanelState


@callback
def async_store_settings(
    hass: HomeAssistant,
    entry: ConfigEntry,
    settings: PanelSettings,
) -> None:
    """Persist the settings of one panel on its config entry.

    They are written to entry data, not options: an options update reloads the
    entry, which would recreate every proxy and make the tablet re-read a
    layout that did not change, for a value the panel picks up on its next
    poll anyway.
    """
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_PANEL_SETTINGS: settings.as_stored()},
    )


class PanelEntity(Entity):
    """One entity of a panel device, backed by its shared state."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, runtime: Any, key: str) -> None:
        """Initialize the metadata every panel entity shares."""
        self._entry = entry
        self._panel: PanelState = runtime.state
        self._attr_unique_id = panel_entity_unique_id(entry.entry_id, key)
        self._attr_translation_key = key
        self._attr_device_info = runtime.device_info

    async def async_added_to_hass(self) -> None:
        """Follow every change to the panel's state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._panel.add_listener(self.async_write_ha_state)
        )


class PanelReadingEntity(PanelEntity):
    """A panel entity that shows what the tablet last reported."""

    @property
    def available(self) -> bool:
        """Return whether the panel reported recently enough to be believed."""
        return self._panel.is_online()
