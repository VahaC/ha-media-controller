"""Room-control switch proxies."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MediaControllerRuntime
from .proxy import ControllerProxyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a switch proxy for every slot whose domain is switch."""
    runtime: MediaControllerRuntime = entry.runtime_data
    for binding in runtime.clients:
        entities = [
            ControllerSwitch(binding.client, slot, binding.device_info)
            for slot in binding.client.slots
            if slot.domain == SWITCH_DOMAIN
        ]
        if entities:
            async_add_entities(
                entities, config_subentry_id=binding.subentry_id
            )


class ControllerSwitch(ControllerProxyEntity, SwitchEntity):
    """Forward state and actions to the switch selected for a slot."""

    _attr_is_on = False

    def _apply_platform_state(self, state: State | None) -> None:
        """Mirror on/off state."""
        self._attr_is_on = state is not None and state.state == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Forward turn-on to the target."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self.target_entity_id},
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forward turn-off to the target."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self.target_entity_id},
            blocking=True,
        )
