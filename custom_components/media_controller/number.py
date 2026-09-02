"""The panel settings that used to live in config.ini on the tablet.

Three of these are timings the panel applies while it runs, so changing one
here changes the tablet's behavior within a poll cycle without restarting
anything. The fourth is the backlight level, which is a command rather than a
setting: it is sent once and the tablet reports back what it actually reached.
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

from .panel_entity import PanelEntity, async_store_settings
from .panel_state import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    PLAYLIST_POLL_INTERVAL_MAX_MS,
    PLAYLIST_POLL_INTERVAL_MIN_MS,
    POLL_INTERVAL_MAX_MS,
    POLL_INTERVAL_MIN_MS,
    SCREEN_OFF_MAX_SECONDS,
    SETTING_PLAYLIST_POLL_INTERVAL,
    SETTING_POLL_INTERVAL,
    SETTING_SCREEN_OFF,
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
    """Create the settings of one panel."""
    runtime = entry.runtime_data
    if not hasattr(runtime, "state"):
        # A controller entry: the ESP32 has no settings Home Assistant owns.
        return

    async_add_entities(
        [
            PollIntervalNumber(entry, runtime),
            PlaylistPollIntervalNumber(entry, runtime),
            ScreenOffNumber(entry, runtime),
            ScreenBrightnessNumber(entry, runtime),
        ]
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
    """How long the tablet waits before turning its display off.

    Zero is offered deliberately and means never: a panel on mains power in a
    hallway is often meant to stay lit until the Power button is pressed.
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
