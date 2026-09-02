"""What a panel reports about itself that is simply true or false."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity, PanelReadingEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the reported flags of one panel."""
    runtime = entry.runtime_data
    if not hasattr(runtime, "state"):
        return
    async_add_entities(
        [
            PanelConnectivitySensor(entry, runtime),
            PanelChargingSensor(entry, runtime),
        ]
    )


class PanelConnectivitySensor(PanelEntity, BinarySensorEntity):
    """Whether the tablet is reporting at all.

    This one is never unavailable: "the panel has not been heard from" is
    exactly what it exists to say, so it has to keep saying it.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(entry, runtime, "connected")

    @property
    def is_on(self) -> bool:
        """Return whether a report arrived recently."""
        return self._panel.is_online()


class PanelChargingSensor(PanelReadingEntity, BinarySensorEntity):
    """Whether the tablet is charging."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: object) -> None:
        """Initialize the charging sensor."""
        super().__init__(entry, runtime, "charging")

    @property
    def available(self) -> bool:
        """Return whether the tablet reported a battery at all."""
        return super().available and self._panel.status.battery_percent >= 0

    @property
    def is_on(self) -> bool:
        """Return whether a charger is supplying the tablet."""
        return self._panel.status.battery_charging
