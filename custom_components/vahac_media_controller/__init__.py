"""VahaC Media Controller integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ENTRY_ID,
    ATTR_QUEUE_ITEM_ID,
    CONF_PLAYER_ENTITY,
    DOMAIN,
    PLATFORMS,
    SERVICE_PLAY_QUEUE_ITEM,
    SERVICE_REFRESH,
)
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .music_assistant import MusicAssistantAdapter, MusicAssistantUnavailable

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class VahaCControllerRuntime:
    """Runtime objects owned by one config entry."""

    adapter: MusicAssistantAdapter
    queue: QueueCoordinator
    playlists: PlaylistCoordinator

    async def async_shutdown(self) -> None:
        """Stop entry-owned listeners and timers."""
        await self.queue.async_shutdown()
        await self.playlists.async_shutdown()


def _configured_value(entry: ConfigEntry, key: str) -> Any:
    """Return an option override or the original config-flow value."""
    return entry.options.get(key, entry.data.get(key))


def _runtime_for_call(
    hass: HomeAssistant,
    call: ServiceCall,
) -> VahaCControllerRuntime:
    """Resolve a runtime by entry ID or configured player entity."""
    runtimes: dict[str, VahaCControllerRuntime] = hass.data.get(DOMAIN, {})
    if entry_id := call.data.get(ATTR_ENTRY_ID):
        if runtime := runtimes.get(entry_id):
            return runtime
        raise ServiceValidationError("VahaC Media Controller entry is not loaded")

    if entity_id := call.data.get(CONF_ENTITY_ID):
        for runtime in runtimes.values():
            if runtime.adapter.player_entity_id == entity_id:
                return runtime
        raise ServiceValidationError(
            "No VahaC Media Controller entry uses this Music Assistant player"
        )

    if len(runtimes) == 1:
        return next(iter(runtimes.values()))
    raise ServiceValidationError("Specify a controller entry or media player")


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration-level actions."""
    hass.data.setdefault(DOMAIN, {})

    async def async_handle_refresh(call: ServiceCall) -> None:
        runtimes: dict[str, VahaCControllerRuntime] = hass.data[DOMAIN]
        if entry_id := call.data.get(ATTR_ENTRY_ID):
            runtime = runtimes.get(entry_id)
            if runtime is None:
                raise ServiceValidationError(
                    "VahaC Media Controller entry is not loaded"
                )
            selected = [runtime]
        else:
            selected = list(runtimes.values())
        if not selected:
            raise ServiceValidationError("No VahaC Media Controller entry is loaded")
        await asyncio.gather(
            *(
                coordinator.async_request_refresh()
                for runtime in selected
                for coordinator in (runtime.queue, runtime.playlists)
            )
        )

    async def async_handle_play_queue_item(call: ServiceCall) -> None:
        runtime = _runtime_for_call(hass, call)
        try:
            await runtime.adapter.async_play_queue_item(
                call.data[ATTR_QUEUE_ITEM_ID]
            )
        except MusicAssistantUnavailable as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        async_handle_refresh,
        schema=vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_QUEUE_ITEM,
        async_handle_play_queue_item,
        schema=vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): cv.entity_id,
                vol.Required(ATTR_QUEUE_ITEM_ID): vol.All(
                    cv.string,
                    vol.Length(min=1),
                ),
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a VahaC Media Controller config entry."""
    player_entity = _configured_value(entry, CONF_PLAYER_ENTITY)
    try:
        adapter = MusicAssistantAdapter.from_player(hass, player_entity)
    except MusicAssistantUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err

    queue = QueueCoordinator(hass, entry, adapter)
    playlists = PlaylistCoordinator(hass, entry, adapter)
    runtime = VahaCControllerRuntime(adapter, queue, playlists)

    try:
        await asyncio.gather(
            queue.async_config_entry_first_refresh(),
            playlists.async_config_entry_first_refresh(),
        )
    except Exception:
        await runtime.async_shutdown()
        raise

    entry.runtime_data = runtime
    hass.data[DOMAIN][entry.entry_id] = runtime

    queue.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and all entry-owned resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    runtime: VahaCControllerRuntime = entry.runtime_data
    await runtime.async_shutdown()
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
