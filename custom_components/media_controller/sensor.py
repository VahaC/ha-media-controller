"""Compatibility sensors consumed by the ESP32 REST client."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import VahaCControllerRuntime
from .const import DOMAIN
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .transformations import PlaylistPayload, QueuePayload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the queue and playlist sensors."""
    runtime: VahaCControllerRuntime = entry.runtime_data
    async_add_entities(
        [
            QueueSensor(entry, runtime.queue),
            PlaylistSensor(entry, runtime.playlists),
        ]
    )


class _ControllerSensor(CoordinatorEntity, SensorEntity):
    """Common entity metadata for a controller sensor."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        """Initialize a controller sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="VahaC",
            model="ESP32 Music Assistant Media Controller",
        )

    @property
    def native_value(self) -> str:
        """Keep the state short; payload data belongs in attributes."""
        return "ok"


class QueueSensor(_ControllerSensor):
    """Bounded Music Assistant queue compatibility sensor."""

    _attr_translation_key = "queue"

    def __init__(self, entry: ConfigEntry, coordinator: QueueCoordinator) -> None:
        """Initialize the queue sensor."""
        super().__init__(entry, coordinator)
        self._attr_unique_id = f"{entry.entry_id}_queue"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the queue payload expected by the firmware."""
        payload = self.coordinator.data or QueuePayload()
        return {
            "data": payload.as_json(),
            "count": payload.count,
        }


class PlaylistSensor(_ControllerSensor):
    """Music Assistant playlist compatibility sensor."""

    _attr_translation_key = "playlists"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: PlaylistCoordinator,
    ) -> None:
        """Initialize the playlist sensor."""
        super().__init__(entry, coordinator)
        self._attr_unique_id = f"{entry.entry_id}_playlists"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the playlist payload expected by the firmware."""
        payload = self.coordinator.data or PlaylistPayload()
        return payload.as_attributes()
