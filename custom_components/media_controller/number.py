"""The numbers a panel owns.

Three are timings the panel applies while it runs, so changing one here
changes its behavior within a poll cycle without restarting anything. The
fourth is the backlight level, which is a command rather than a setting: it is
sent once and the panel reports back what it actually reached.

The last four are the theme opacities of a panel that draws with a theme.
They were ESPHome numbers on the device's own ESPHome device until contract
version 9 removed the native API that carried them.
"""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import (
    PanelEntity,
    async_store_settings,
    async_store_theme,
)
from .panel_state import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    OPACITY_MAX,
    OPACITY_MIN,
    PLAYLIST_POLL_INTERVAL_MAX_MS,
    PLAYLIST_POLL_INTERVAL_MIN_MS,
    POLL_INTERVAL_MAX_MS,
    POLL_INTERVAL_MIN_MS,
    SCREEN_OFF_MAX_SECONDS,
    SETTING_PLAYLIST_POLL_INTERVAL,
    SETTING_POLL_INTERVAL,
    SETTING_SCREEN_OFF,
    THEME_OPACITY_DEFAULTS,
)

# The panel stores the two intervals in milliseconds, which is what the
# contract and config.ini use. Seconds are what a person setting them thinks
# in, so the conversion happens here and nowhere else.
MILLISECONDS_PER_SECOND = 1000


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the numbers of one panel."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            PollIntervalNumber(entry, runtime),
            PlaylistPollIntervalNumber(entry, runtime),
            ScreenOffNumber(entry, runtime),
            ScreenBrightnessNumber(entry, runtime),
        ]
    )
    # Only a client that draws with a theme gets them. A tablet would have
    # nothing to apply a progress-ring opacity to, and four permanently
    # meaningless numbers on its device page would be worse than none.
    if runtime.client.profile.has_theme:
        async_add_entities(
            ThemeOpacityNumber(entry, runtime, key)
            for key in THEME_OPACITY_DEFAULTS
        )


class _PanelSettingNumber(PanelEntity, NumberEntity):
    """A stored setting the panel reads on its next poll."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    async def async_set_native_value(self, value: float) -> None:
        """Store the new value and let the panel pick it up."""
        settings = self._panel.set_setting(
            self._setting_key, self._to_stored(value)
        )
        async_store_settings(self.hass, self._entry, settings)

    @property
    def _setting_key(self) -> str:
        """Return the settings key this entity edits."""
        raise NotImplementedError

    @staticmethod
    def _to_stored(value: float) -> int:
        """Convert the displayed value to the unit the panel reads."""
        raise NotImplementedError


class PollIntervalNumber(_PanelSettingNumber):
    """How often the panel asks Home Assistant for player and room state."""

    _attr_native_min_value = POLL_INTERVAL_MIN_MS / MILLISECONDS_PER_SECOND
    _attr_native_max_value = POLL_INTERVAL_MAX_MS / MILLISECONDS_PER_SECOND
    _attr_native_step = 0.5

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the update-interval setting."""
        super().__init__(entry, runtime, "poll_interval")

    @property
    def _setting_key(self) -> str:
        return SETTING_POLL_INTERVAL

    @staticmethod
    def _to_stored(value: float) -> int:
        return int(round(value * MILLISECONDS_PER_SECOND))

    @property
    def native_value(self) -> float:
        """Return the stored interval in seconds."""
        return (
            self._panel.settings.poll_interval_ms / MILLISECONDS_PER_SECOND
        )


class PlaylistPollIntervalNumber(_PanelSettingNumber):
    """How often the panel refreshes playlists and its own configuration."""

    _attr_native_min_value = (
        PLAYLIST_POLL_INTERVAL_MIN_MS / MILLISECONDS_PER_SECOND
    )
    _attr_native_max_value = (
        PLAYLIST_POLL_INTERVAL_MAX_MS / MILLISECONDS_PER_SECOND
    )
    _attr_native_step = 10

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the playlist-refresh setting."""
        super().__init__(entry, runtime, "playlist_poll_interval")

    @property
    def _setting_key(self) -> str:
        return SETTING_PLAYLIST_POLL_INTERVAL

    @staticmethod
    def _to_stored(value: float) -> int:
        return int(round(value * MILLISECONDS_PER_SECOND))

    @property
    def native_value(self) -> float:
        """Return the stored interval in seconds."""
        return (
            self._panel.settings.playlist_poll_interval_ms
            / MILLISECONDS_PER_SECOND
        )


class ScreenOffNumber(_PanelSettingNumber):
    """How long a panel waits before turning its display off.

    Zero is offered deliberately and means never: a panel on mains power in a
    hallway is often meant to stay lit until the Power button is pressed.

    Both panels apply it. The paired ESP32 firmware did not until contract
    version 9, because a *Screen Timeout* number on its own ESPHome device
    owned the value; that number went with the native API, and this is the
    only owner left.
    """

    _attr_native_min_value = 0
    _attr_native_max_value = SCREEN_OFF_MAX_SECONDS
    _attr_native_step = 5

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the screen-timeout setting."""
        super().__init__(entry, runtime, "screen_off")

    @property
    def _setting_key(self) -> str:
        return SETTING_SCREEN_OFF

    @staticmethod
    def _to_stored(value: float) -> int:
        return int(round(value))

    @property
    def native_value(self) -> float:
        """Return the stored timeout in seconds."""
        return float(self._panel.settings.screen_off_seconds)


class ScreenBrightnessNumber(PanelEntity, NumberEntity):
    """The backlight level of the tablet.

    This is the one number here that the tablet can refuse: the backlight is a
    kernel device, and writing to it needs a permission not every installation
    grants. The entity is therefore unavailable until a panel has reported a
    level it can actually set.
    """

    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = BRIGHTNESS_MIN
    _attr_native_max_value = BRIGHTNESS_MAX
    _attr_native_step = 1

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the backlight control."""
        super().__init__(entry, runtime, "screen_brightness")

    @property
    def available(self) -> bool:
        """Return whether the tablet reported a backlight it can write."""
        return self._panel.is_online() and self._panel.status.brightness >= 0

    @property
    def native_value(self) -> float | None:
        """Return the level the panel last reported."""
        brightness = self._panel.status.brightness
        return None if brightness < 0 else float(brightness)

    async def async_set_native_value(self, value: float) -> None:
        """Ask the panel to change its backlight."""
        self._panel.request_brightness(int(round(value)))


class ThemeOpacityNumber(PanelEntity, NumberEntity):
    """One of the four opacities a panel draws its player page with.

    A setting rather than a reading: it is what Home Assistant wants, the
    panel adopts it on its next poll, and it keeps its value while the panel
    is unplugged. The panel stores what it applied in its own flash, so a
    reboot with Home Assistant down comes back looking the same.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = OPACITY_MIN
    _attr_native_max_value = OPACITY_MAX
    _attr_native_step = 1

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: object,
        key: str,
    ) -> None:
        """Initialize one opacity, named by its payload key."""
        super().__init__(entry, runtime, key)
        self._theme_key = key

    @property
    def native_value(self) -> float:
        """Return the stored opacity."""
        return float(getattr(self._panel.theme, self._theme_key))

    async def async_set_native_value(self, value: float) -> None:
        """Store the new opacity and let the panel pick it up."""
        theme = self._panel.set_theme_value(self._theme_key, int(round(value)))
        async_store_theme(self.hass, self._entry, theme)
