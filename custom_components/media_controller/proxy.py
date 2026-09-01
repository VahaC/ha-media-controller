"""Shared state tracking for room-control proxy entities."""

from __future__ import annotations

from abc import abstractmethod

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, State, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, slot_translation_key, slot_unique_id
from .profiles import ClientProfile
from .slots import ClientConfiguration, SlotConfig

CONTROLLER_MODEL = "ESP32 Music Assistant Media Controller"


def controller_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device shared by the controller's own entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="VahaC",
        model=CONTROLLER_MODEL,
    )


def panel_device_info(
    entry: ConfigEntry,
    subentry: ConfigSubentry,
    profile: ClientProfile,
) -> DeviceInfo:
    """Return the device of one panel client."""
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer="VahaC",
        model=profile.name,
        via_device=(DOMAIN, entry.entry_id),
    )


class ControllerProxyEntity(Entity):
    """Mirror the entity a user put in one room-control slot.

    Clients address the proxy, never the target. It is the only way an ESP32
    can follow a slot change made in the Home Assistant UI, because ESPHome
    resolves entity IDs at compile time.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        client: ClientConfiguration,
        slot: SlotConfig,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize common proxy metadata."""
        self._client = client
        self._slot = slot
        self._target_entity_id = slot.target_entity_id
        self._attr_unique_id = slot_unique_id(client.owner_id, slot.index)
        self._attr_translation_key = slot_translation_key(slot.index)
        self._attr_device_info = device_info
        self._attr_available = False

    @property
    def target_entity_id(self) -> str:
        """Return the configured source entity."""
        return self._target_entity_id

    async def async_added_to_hass(self) -> None:
        """Publish the assigned entity ID and start mirroring the target."""
        await super().async_added_to_hass()
        self._client.async_set_proxy_entity_id(self._slot.index, self.entity_id)
        self._apply_target_state(self.hass.states.get(self._target_entity_id))
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._target_entity_id],
                self._async_target_state_changed,
            )
        )

    @callback
    def _async_target_state_changed(self, event: Event) -> None:
        """Mirror the newest source state."""
        self._apply_target_state(event.data.get("new_state"))
        self.async_write_ha_state()

    @callback
    def _apply_target_state(self, state: State | None) -> None:
        """Update availability before applying platform-specific values."""
        self._attr_available = state is not None and state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        self._apply_platform_state(state if self._attr_available else None)

    @abstractmethod
    def _apply_platform_state(self, state: State | None) -> None:
        """Apply platform-specific source state and attributes."""
