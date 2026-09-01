"""Room-control light proxies."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    DOMAIN as LIGHT_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MediaControllerRuntime
from .profiles import CONTROL_BRIGHTNESS, CONTROL_COLOR_TEMP
from .proxy import ControllerProxyEntity
from .slots import ClientConfiguration, SlotConfig


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a light proxy for every slot whose domain is light."""
    runtime: MediaControllerRuntime = entry.runtime_data
    for binding in runtime.clients:
        entities = [
            ControllerLight(binding.client, slot, binding.device_info)
            for slot in binding.client.slots
            if slot.domain == LIGHT_DOMAIN
        ]
        if entities:
            async_add_entities(
                entities, config_subentry_id=binding.subentry_id
            )


class ControllerLight(ControllerProxyEntity, LightEntity):
    """Forward state and actions to the light selected for a slot.

    Colour modes are taken from the target instead of being fixed, so a tile
    can offer colour temperature through the proxy. Before contract version 2
    a client had to address the real light for that.
    """

    def __init__(
        self,
        client: ClientConfiguration,
        slot: SlotConfig,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize a room light proxy from its capability snapshot."""
        super().__init__(client, slot, device_info)
        # Home Assistant forbids combining BRIGHTNESS with a richer mode, so
        # the single most capable mode is declared.
        if CONTROL_COLOR_TEMP in slot.controls:
            color_mode = ColorMode.COLOR_TEMP
        elif CONTROL_BRIGHTNESS in slot.controls:
            color_mode = ColorMode.BRIGHTNESS
        else:
            color_mode = ColorMode.ONOFF
        self._attr_color_mode = color_mode
        self._attr_supported_color_modes = {color_mode}
        if slot.min_kelvin is not None:
            self._attr_min_color_temp_kelvin = slot.min_kelvin
        if slot.max_kelvin is not None:
            self._attr_max_color_temp_kelvin = slot.max_kelvin
        self._attr_is_on = False
        self._attr_brightness = None
        self._attr_color_temp_kelvin = None

    def _apply_platform_state(self, state: State | None) -> None:
        """Mirror on/off, brightness, and colour temperature."""
        self._attr_is_on = state is not None and state.state == STATE_ON
        attributes = state.attributes if state is not None else {}
        self._attr_brightness = attributes.get(ATTR_BRIGHTNESS)
        self._attr_color_temp_kelvin = attributes.get(ATTR_COLOR_TEMP_KELVIN)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Forward turn-on and any supported adjustment to the target."""
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: self.target_entity_id}
        for attribute in (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN):
            if attribute in kwargs:
                service_data[attribute] = kwargs[attribute]
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            service_data,
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forward turn-off to the target."""
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self.target_entity_id},
            blocking=True,
        )
