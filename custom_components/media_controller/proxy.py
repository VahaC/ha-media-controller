"""Shared state tracking for optional room-control proxy entities."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, State, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN


class ControllerProxyEntity(Entity):
    """Mirror one user-selected Home Assistant entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        target_entity_id: str | None,
    ) -> None:
        """Initialize common proxy metadata."""
        self._target_entity_id = target_entity_id
        self._attr_available = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="VahaC",
            model="ESP32 Music Assistant Media Controller",
        )

    @property
    def target_entity_id(self) -> str | None:
        """Return the configured source entity."""
        return self._target_entity_id

    async def async_added_to_hass(self) -> None:
        """Start mirroring source state changes."""
        await super().async_added_to_hass()
        if self._target_entity_id is None:
            return
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

    def _require_target(self) -> str:
        """Return the source entity or raise a clear action error."""
        if self._target_entity_id is None:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError("This room control is not configured")
        return self._target_entity_id


def configured_value(entry: ConfigEntry, key: str) -> Any:
    """Return an Options Flow override or initial Config Flow value."""
    return entry.options.get(key, entry.data.get(key))

