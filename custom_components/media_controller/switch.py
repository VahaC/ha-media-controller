"""Optional Fan and AC proxy switch entities."""

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

from .const import CONF_AC_ENTITY, CONF_FAN_ENTITY
from .proxy import ControllerProxyEntity, configured_value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create Fan and AC proxy switches."""
    async_add_entities(
        [
            ControllerSwitch(
                entry,
                CONF_FAN_ENTITY,
                configured_value(entry, CONF_FAN_ENTITY),
            ),
            ControllerSwitch(
                entry,
                CONF_AC_ENTITY,
                configured_value(entry, CONF_AC_ENTITY),
            ),
        ]
    )


class ControllerSwitch(ControllerProxyEntity, SwitchEntity):
    """Forward switch state and actions to a selected HA switch."""

    def __init__(
        self,
        entry: ConfigEntry,
        slot: str,
        target_entity_id: str | None,
    ) -> None:
        """Initialize a room switch proxy."""
        super().__init__(entry, target_entity_id)
        self._attr_unique_id = f"{entry.entry_id}_{slot}"
        self._attr_translation_key = slot.removesuffix("_entity")
        self._attr_is_on = False

    def _apply_platform_state(self, state: State | None) -> None:
        """Mirror on/off state."""
        self._attr_is_on = state is not None and state.state == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Forward turn-on to the selected switch."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self._require_target()},
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forward turn-off to the selected switch."""
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self._require_target()},
            blocking=True,
        )

