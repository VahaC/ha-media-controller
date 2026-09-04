"""Compatibility sensors consumed by the clients."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MediaControllerRuntime
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .panel_entity import PanelEntity, PanelReadingEntity
from .proxy import controller_device_info
from .profiles import capability_signature
from .slots import ClientConfiguration, ControllerEntities
from .transformations import PlaylistPayload, QueuePayload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the config sensor, and whatever else the entry kind owns."""
    runtime = entry.runtime_data
    async_add_entities(
        [ClientConfigSensor(runtime.client, runtime.device_info)]
    )
    if not isinstance(runtime, MediaControllerRuntime):
        async_add_entities(
            [
                PanelBatterySensor(entry, runtime),
                PanelUptimeSensor(entry, runtime),
                PanelLastReportSensor(entry, runtime),
                PanelWifiSensor(entry, runtime),
                PanelTemperatureSensor(entry, runtime),
            ]
        )
        return

    controller = runtime.client.controller
    async_add_entities(
        [
            QueueSensor(entry, runtime.queue, controller),
            PlaylistSensor(entry, runtime.playlists, controller),
        ]
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
        self._tracked: set[str] = set()
        self._untrack: Callable[[], None] | None = None
        # The room states served with the last write, to avoid rewriting the
        # sensor on events that moved nothing a panel draws.
        self._last_room_states: dict[str, list[Any]] | None = None

    async def async_added_to_hass(self) -> None:
        """Re-publish whenever a proxy or a registry element changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._client.async_add_listener(self._async_client_changed)
        )
        self.async_on_remove(self._async_stop_tracking)
        self._async_track_targets()

    @callback
    def _async_client_changed(self) -> None:
        """Follow the client's targets, then publish the new payload.

        A registry element that followed its entity through a rename points at
        a different entity ID than the one being watched, so the subscription
        is rebuilt before the payload is written.
        """
        self._async_track_targets()
        self._last_room_states = self._client.room_states()
        self.async_write_ha_state()

    @callback
    def _async_track_targets(self) -> None:
        """Watch exactly the entities whose capabilities this payload uses."""
        targets = self._client.target_entity_ids
        if targets == self._tracked:
            return
        self._async_stop_tracking()
        self._tracked = targets
        if targets:
            self._untrack = async_track_state_change_event(
                self.hass,
                list(targets),
                self._async_target_state_changed,
            )

    @callback
    def _async_stop_tracking(self) -> None:
        """Drop the current state subscription, if there is one."""
        if self._untrack is not None:
            self._untrack()
            self._untrack = None

    @callback
    def _async_target_state_changed(self, event: Event) -> None:
        """Refresh capabilities on capability changes, republish on state ones.

        The room states ride this sensor, so a toggle must rewrite it: the
        capability signature deliberately ignores power state, and without the
        second half below a lamp switched elsewhere would keep its old value
        here until something reconfigured the panel. Compared rather than
        blindly written, so that a dimming sweep — dozens of events for one
        gesture — costs one write per value a panel actually draws.
        """
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if capability_signature(
            old_state.attributes if old_state is not None else None
        ) != capability_signature(
            new_state.attributes if new_state is not None else None
        ):
            entity_id = event.data.get("entity_id")
            if entity_id is not None:
                self._client.async_refresh_target_capabilities(entity_id)
        self._async_publish_room_states()

    @callback
    def _async_publish_room_states(self) -> None:
        """Write a new state when the rendered room states moved."""
        states = self._client.room_states()
        if states == self._last_room_states:
            return
        self._last_room_states = states
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Keep the state short; payload data belongs in attributes."""
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the slot layout and capabilities."""
        return self._client.payload().as_attributes()


class PanelBatterySensor(PanelReadingEntity, SensorEntity):
    """The charge of the tablet the panel runs on.

    The panel reads it from the kernel and pushes it here, because Home
    Assistant cannot ask a tablet anything. A tablet without a battery — a
    panel wired to a permanent supply — never reports one, and the sensor
    stays unavailable rather than claiming zero.
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the battery sensor of one panel."""
        super().__init__(entry, runtime, "battery")

    @property
    def available(self) -> bool:
        """Return whether the tablet reported a battery it can read."""
        return super().available and self._panel.status.battery_percent >= 0

    @property
    def native_value(self) -> int | None:
        """Return the reported charge."""
        percent = self._panel.status.battery_percent
        return None if percent < 0 else percent


class PanelUptimeSensor(PanelReadingEntity, SensorEntity):
    """When the panel application last started.

    A timestamp rather than a duration, because that is the fact worth
    watching: it stays still while the application does, and a new value means
    the tablet restarted it — or the watchdog did.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the uptime sensor of one panel."""
        super().__init__(entry, runtime, "uptime")

    @property
    def available(self) -> bool:
        """Return whether the tablet reported how long it has been running."""
        return super().available and self._panel.started_at is not None

    @property
    def native_value(self) -> datetime | None:
        """Return the moment the application started."""
        started_at = self._panel.started_at
        if started_at is None:
            return None
        return datetime.fromtimestamp(started_at, tz=timezone.utc)


class PanelLastReportSensor(PanelEntity, SensorEntity):
    """When the tablet was last heard from.

    Never unavailable, like the connectivity sensor beside it: a panel that
    stopped reporting is exactly what this is for. It is unknown only until
    the first report of a Home Assistant run.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the last-report sensor of one panel."""
        super().__init__(entry, runtime, "last_report")

    @property
    def native_value(self) -> datetime | None:
        """Return the arrival time of the last accepted report."""
        reported_wall_at = self._panel.reported_wall_at
        if reported_wall_at is None:
            return None
        return datetime.fromtimestamp(reported_wall_at, tz=timezone.utc)


class PanelWifiSensor(PanelReadingEntity, SensorEntity):
    """The Wi-Fi signal the tablet is seeing.

    A wall-mounted panel that drops out at the same time every day is almost
    always a signal problem, and this is what makes that visible without
    logging in to the tablet.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the Wi-Fi signal sensor of one panel."""
        super().__init__(entry, runtime, "wifi_signal")

    @property
    def available(self) -> bool:
        """Return whether the tablet reported a wireless link at all."""
        return super().available and self._panel.status.wifi_dbm is not None

    @property
    def native_value(self) -> float | None:
        """Return the reported signal strength."""
        return self._panel.status.wifi_dbm


class PanelTemperatureSensor(PanelReadingEntity, SensorEntity):
    """The temperature the tablet reports.

    A tablet held at full charge on a wall runs warm, and a battery that is
    swelling runs warmer. It is a diagnostic, not a room temperature.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the temperature sensor of one panel."""
        super().__init__(entry, runtime, "temperature")

    @property
    def available(self) -> bool:
        """Return whether the tablet exposes a thermal zone it can read."""
        return (
            super().available
            and self._panel.status.temperature_c is not None
        )

    @property
    def native_value(self) -> float | None:
        """Return the reported temperature."""
        return self._panel.status.temperature_c
