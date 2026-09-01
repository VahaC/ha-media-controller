"""Compatibility sensors consumed by the clients."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MediaControllerRuntime
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .proxy import controller_device_info
from .slots import ClientConfiguration, ControllerEntities
from .transformations import PlaylistPayload, QueuePayload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the queue, playlist, and per-client config sensors."""
    runtime: MediaControllerRuntime = entry.runtime_data
    controller = runtime.controller_entities
    assert controller is not None
    async_add_entities(
        [
            QueueSensor(entry, runtime.queue, controller),
            PlaylistSensor(entry, runtime.playlists, controller),
        ]
    )
    for binding in runtime.clients:
        async_add_entities(
            [ClientConfigSensor(binding.client, binding.device_info)],
            config_subentry_id=binding.subentry_id,
        )


class _ControllerSensor(CoordinatorEntity, SensorEntity):
    """Common entity metadata for a controller sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: Any,
        controller: ControllerEntities,
    ) -> None:
        """Initialize a controller sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._controller = controller
        self._attr_device_info = controller_device_info(entry)

    @property
    def native_value(self) -> str:
        """Keep the state short; payload data belongs in attributes."""
        return "ok"


class QueueSensor(_ControllerSensor):
    """Bounded Music Assistant queue compatibility sensor."""

    _attr_translation_key = "queue"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: QueueCoordinator,
        controller: ControllerEntities,
    ) -> None:
        """Initialize the queue sensor."""
        super().__init__(entry, coordinator, controller)
        self._attr_unique_id = f"{entry.entry_id}_queue"

    async def async_added_to_hass(self) -> None:
        """Publish the entity ID every client needs to read the queue."""
        await super().async_added_to_hass()
        self._controller.async_set_queue_entity_id(self.entity_id)

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
        controller: ControllerEntities,
    ) -> None:
        """Initialize the playlist sensor."""
        super().__init__(entry, coordinator, controller)
        self._attr_unique_id = f"{entry.entry_id}_playlists"

    async def async_added_to_hass(self) -> None:
        """Publish the entity ID every client needs to read playlists."""
        await super().async_added_to_hass()
        self._controller.async_set_playlists_entity_id(self.entity_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the playlist payload expected by the firmware."""
        payload = self.coordinator.data or PlaylistPayload()
        return payload.as_attributes()


class ClientConfigSensor(SensorEntity):
    """Everything one client device needs to draw its room controls.

    A client reads this with a single request and renders the slots it
    receives; it never resolves entity IDs or capabilities itself.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "config"

    def __init__(
        self,
        client: ClientConfiguration,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the config sensor of one client."""
        self._client = client
        self._attr_unique_id = f"{client.owner_id}_config"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Re-publish whenever a slot proxy reports its entity ID."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._client.async_add_listener(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> str:
        """Keep the state short; payload data belongs in attributes."""
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the slot layout and capabilities."""
        return self._client.payload().as_attributes()
