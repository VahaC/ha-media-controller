"""The colours a panel draws its player page with.

Eight text entities, one per colour, each holding `#RRGGBB`. They were
ESPHome text entities on the device's own ESPHome device until contract
version 9 removed the native API that carried them, and they are the reason
that removal did not cost the user the only way to restyle the player.

A colour is a setting, not a reading: it is what Home Assistant wants, the
panel adopts it on its next poll, and it keeps its value while the panel is
unplugged or being reflashed.

Home Assistant has no colour selector for a config entity, so this is a text
field with a pattern the frontend enforces and `PanelTheme` validates again.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity, async_store_theme
from .panel_state import THEME_COLOR_DEFAULTS

# `#` and six hexadecimal digits, which is what the contract says travels.
# The frontend refuses anything else before it is submitted; PanelTheme
# rejects it again, because a value can also arrive from a service call.
COLOR_PATTERN = "^#([0-9a-fA-F]{6})$"
COLOR_LENGTH = 7


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the theme colours of one panel."""
    runtime = entry.runtime_data
    # Only a client that draws with a theme has any. A tablet's two skins
    # carry their own palettes and it would have nothing to apply one to.
    if not runtime.client.profile.has_theme:
        return
    async_add_entities(
        ThemeColorText(entry, runtime, key) for key in THEME_COLOR_DEFAULTS
    )


class ThemeColorText(PanelEntity, TextEntity):
    """One of the eight colours, as `#RRGGBB`."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_min = COLOR_LENGTH
    _attr_native_max = COLOR_LENGTH
    _attr_pattern = COLOR_PATTERN

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: object,
        key: str,
    ) -> None:
        """Initialize one colour, named by its payload key."""
        super().__init__(entry, runtime, key)
        self._theme_key = key

    @property
    def native_value(self) -> str:
        """Return the stored colour."""
        return str(getattr(self._panel.theme, self._theme_key))

    async def async_set_value(self, value: str) -> None:
        """Store the new colour and let the panel pick it up.

        An unusable value is not rejected loudly: `PanelTheme` keeps the
        current colour instead, which is the same rule the panel follows when
        it reads one it cannot parse.
        """
        theme = self._panel.set_theme_value(self._theme_key, value)
        async_store_theme(self.hass, self._entry, theme)
