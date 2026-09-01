"""Telling the two kinds of config entry apart.

Both the setup path and the flows need this, and neither should have to import
the other to get it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_PANEL


def is_panel_entry(entry: ConfigEntry) -> bool:
    """Return whether an entry describes a panel rather than a controller.

    Entries written before panels existed carry no type at all, and every one
    of them is a controller.
    """
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_PANEL


def controller_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return every controller entry, loaded or not."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if not is_panel_entry(entry)
    ]
