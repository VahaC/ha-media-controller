"""Room-control switch proxies."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity
from .proxy import ControllerProxyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a switch proxy for every slot whose domain is switch."""
    runtime = entry.runtime_data
    async_add_entities(
        ControllerSwitch(runtime.client, slot, runtime.device_info)
        for slot in runtime.client.slots
        if slot.domain == SWITCH_DOMAIN
    )
    if hasattr(runtime, "state"):
        async_add_entities([PanelDisplaySwitch(entry, runtime)])


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


class PanelDisplaySwitch(PanelEntity, SwitchEntity):
    """The backlight of the tablet the panel runs on.

    Turning it here is the same act as pressing the Power button on the
    tablet, and both are visible in the other place: the request travels in
    the panel's configuration, the tablet applies it, and it reports what its
    display actually did. Until that report arrives the switch shows what was
    asked for, so a tap does not appear to do nothing for a second.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the display switch of one panel."""
        super().__init__(entry, runtime, "screen")

    @property
    def available(self) -> bool:
        """Return whether the tablet is reporting its display state."""
        return self._panel.is_online() and self._panel.status.display_known

    @property
    def is_on(self) -> bool:
        """Return whether the display is lit."""
        return self._panel.status.display_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Ask the panel to light its display."""
        self._panel.request_display(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Ask the panel to turn its display off."""
        self._panel.request_display(False)
