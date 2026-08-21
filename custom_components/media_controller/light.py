"""Optional Light 1 and Light 2 proxy entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    DOMAIN as LIGHT_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_LIGHT_1_ENTITY, CONF_LIGHT_2_ENTITY
from .proxy import ControllerProxyEntity, configured_value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create both proxy lights, unavailable when not configured."""
    async_add_entities(
        [
            ControllerLight(
                entry,
                CONF_LIGHT_1_ENTITY,
                configured_value(entry, CONF_LIGHT_1_ENTITY),
            ),
            ControllerLight(
                entry,
                CONF_LIGHT_2_ENTITY,
                configured_value(entry, CONF_LIGHT_2_ENTITY),
            ),
        ]
    )


class ControllerLight(ControllerProxyEntity, LightEntity):
    """Forward light state and brightness actions to a selected HA light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        entry: ConfigEntry,
        slot: str,
        target_entity_id: str | None,
    ) -> None:
        """Initialize a room light proxy."""
        super().__init__(entry, target_entity_id)
        self._attr_unique_id = f"{entry.entry_id}_{slot}"
        self._attr_translation_key = slot.removesuffix("_entity")
        self._attr_is_on = False
        self._attr_brightness = None

    def _apply_platform_state(self, state: State | None) -> None:
        """Mirror on/off and brightness state."""
        self._attr_is_on = state is not None and state.state == STATE_ON
        self._attr_brightness = (
            state.attributes.get(ATTR_BRIGHTNESS) if state is not None else None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Forward turn-on and optional brightness to the selected light."""
        service_data: dict[str, Any] = {
            ATTR_ENTITY_ID: self._require_target()
        }
        if ATTR_BRIGHTNESS in kwargs:
            service_data[ATTR_BRIGHTNESS] = kwargs[ATTR_BRIGHTNESS]
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            service_data,
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forward turn-off to the selected light."""
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self._require_target()},
            blocking=True,
        )

