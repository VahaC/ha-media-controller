"""Media Controller integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    ATTR_ENTRY_ID,
    ATTR_QUEUE_ITEM_ID,
    CONF_PLAYER_ENTITY,
    CONF_PROFILE,
    CONF_SLOTS,
    DOMAIN,
    ENTRY_VERSION,
    LEGACY_SLOTS,
    PLATFORMS,
    SERVICE_PLAY_QUEUE_ITEM,
    SERVICE_REFRESH,
    SUBENTRY_TYPE_PANEL,
    slot_unique_id,
)
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .music_assistant import MusicAssistantAdapter, MusicAssistantUnavailable
from .profiles import (
    CONTROL_TOGGLE,
    CONTROLLER_PROFILE,
    limit_controls,
    panel_profile,
)
from .proxy import controller_device_info, panel_device_info
from .slots import (
    ClientConfiguration,
    ControllerEntities,
    resolve_slots,
    stored_slots,
)
from .transformations import SlotConfig, migrate_v1_section

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ClientBinding:
    """One client device: its slots, its Home Assistant device, its owner."""

    client: ClientConfiguration
    device_info: DeviceInfo
    subentry_id: str | None = None


@dataclass(slots=True)
class MediaControllerRuntime:
    """Runtime objects owned by one config entry."""

    adapter: MusicAssistantAdapter
    queue: QueueCoordinator
    playlists: PlaylistCoordinator
    clients: list[ClientBinding] = field(default_factory=list)
    controller_entities: ControllerEntities | None = None
    subentry_fingerprint: str = ""

    async def async_shutdown(self) -> None:
        """Stop entry-owned listeners and timers."""
        await self.queue.async_shutdown()
        await self.playlists.async_shutdown()


def _configured_value(entry: ConfigEntry, key: str) -> Any:
    """Return an option override or the original config-flow value."""
    return entry.options.get(key, entry.data.get(key))


def _controller_stored_slots(entry: ConfigEntry) -> list[SlotConfig]:
    """Return the ESP32 slots of a controller entry."""
    if CONF_SLOTS in entry.options:
        return stored_slots(entry.options, CONF_SLOTS)
    return stored_slots(entry.data, CONF_SLOTS)


def _panel_subentries(entry: ConfigEntry) -> list[Any]:
    """Return every panel subentry of a controller."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_PANEL
    ]


def _subentry_fingerprint(entry: ConfigEntry) -> str:
    """Return a value that changes when any subentry changes.

    Options changes are reloaded by the options flow itself, so the update
    listener must reload only when a panel was added, edited, or removed.
    """
    return json.dumps(
        sorted(
            (subentry.subentry_id, subentry.title, subentry.data)
            for subentry in _panel_subentries(entry)
        ),
        sort_keys=True,
        default=str,
    )


def _build_clients(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controller: ControllerEntities,
) -> list[ClientBinding]:
    """Build every client of a controller, capabilities freshly resolved."""
    clients = [
        ClientBinding(
            client=ClientConfiguration(
                hass,
                entry.entry_id,
                CONTROLLER_PROFILE,
                resolve_slots(
                    hass, CONTROLLER_PROFILE, _controller_stored_slots(entry)
                ),
                controller,
            ),
            device_info=controller_device_info(entry),
        )
    ]

    for subentry in _panel_subentries(entry):
        profile = panel_profile(subentry.data.get(CONF_PROFILE))
        clients.append(
            ClientBinding(
                client=ClientConfiguration(
                    hass,
                    subentry.subentry_id,
                    profile,
                    resolve_slots(
                        hass, profile, stored_slots(subentry.data, CONF_SLOTS)
                    ),
                    controller,
                ),
                device_info=panel_device_info(entry, subentry, profile),
                subentry_id=subentry.subentry_id,
            )
        )
    return clients


@callback
def _async_remove_orphaned_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    clients: list[ClientBinding],
) -> None:
    """Delete registry entries for slots and clients that no longer exist.

    Clearing a slot, or deleting a panel, must not leave a permanently
    unavailable proxy behind.
    """
    expected: set[tuple[str, str]] = {
        ("sensor", f"{entry.entry_id}_queue"),
        ("sensor", f"{entry.entry_id}_playlists"),
    }
    for binding in clients:
        owner_id = binding.client.owner_id
        expected.add(("sensor", f"{owner_id}_config"))
        for slot in binding.client.slots:
            expected.add((slot.domain, slot_unique_id(owner_id, slot.index)))

    registry = er.async_get(hass)
    for registry_entry in list(
        er.async_entries_for_config_entry(registry, entry.entry_id)
    ):
        if (registry_entry.domain, registry_entry.unique_id) in expected:
            continue
        _LOGGER.debug(
            "Removing orphaned Media Controller entity %s",
            registry_entry.entity_id,
        )
        registry.async_remove(registry_entry.entity_id)


def _runtime_for_call(
    hass: HomeAssistant,
    call: ServiceCall,
) -> MediaControllerRuntime:
    """Resolve a runtime by entry ID or configured player entity."""
    runtimes: dict[str, MediaControllerRuntime] = hass.data.get(DOMAIN, {})
    if entry_id := call.data.get(ATTR_ENTRY_ID):
        if runtime := runtimes.get(entry_id):
            return runtime
        raise ServiceValidationError("Media Controller entry is not loaded")

    if entity_id := call.data.get(CONF_ENTITY_ID):
        for runtime in runtimes.values():
            if runtime.adapter.player_entity_id == entity_id:
                return runtime
        raise ServiceValidationError(
            "No Media Controller entry uses this Music Assistant player"
        )

    if len(runtimes) == 1:
        return next(iter(runtimes.values()))
    raise ServiceValidationError("Specify a controller entry or media player")


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration-level actions."""
    hass.data.setdefault(DOMAIN, {})

    async def async_handle_refresh(call: ServiceCall) -> None:
        runtimes: dict[str, MediaControllerRuntime] = hass.data[DOMAIN]
        if entry_id := call.data.get(ATTR_ENTRY_ID):
            runtime = runtimes.get(entry_id)
            if runtime is None:
                raise ServiceValidationError(
                    "Media Controller entry is not loaded"
                )
            selected = [runtime]
        else:
            selected = list(runtimes.values())
        if not selected:
            raise ServiceValidationError("No Media Controller entry is loaded")
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the four named room controls to numbered slots."""
    if entry.version > ENTRY_VERSION:
        # Downgrading is not supported; refuse rather than corrupt the entry.
        return False
    if entry.version == ENTRY_VERSION:
        return True

    def initial_controls(index: int) -> tuple[str, ...]:
        return limit_controls((CONTROL_TOGGLE,), CONTROLLER_PROFILE.spec(index))

    _async_migrate_slot_unique_ids(hass, entry)
    hass.config_entries.async_update_entry(
        entry,
        data=migrate_v1_section(
            entry.data, CONF_SLOTS, CONF_PLAYER_ENTITY, LEGACY_SLOTS,
            initial_controls,
        ),
        options=migrate_v1_section(
            entry.options, CONF_SLOTS, CONF_PLAYER_ENTITY, LEGACY_SLOTS,
            initial_controls,
        ),
        version=ENTRY_VERSION,
    )
    _LOGGER.info("Migrated %s to numbered room-control slots", entry.title)
    return True


@callback
def _async_migrate_slot_unique_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Renumber the four version 1 proxies without changing their entity IDs.

    The registry keeps each row, so `light.<controller>_light_1` and the rest
    survive and flashed ESP32 devices need no reflash.
    """
    registry = er.async_get(hass)
    for index, legacy_key, domain in LEGACY_SLOTS:
        legacy_unique_id = f"{entry.entry_id}_{legacy_key}"
        entity_id = registry.async_get_entity_id(
            domain, DOMAIN, legacy_unique_id
        )
        if entity_id is None:
            continue
        new_unique_id = slot_unique_id(entry.entry_id, index)
        if registry.async_get_entity_id(domain, DOMAIN, new_unique_id):
            continue
        registry.async_update_entity(entity_id, new_unique_id=new_unique_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Media Controller config entry."""
    player_entity = _configured_value(entry, CONF_PLAYER_ENTITY)
    try:
        adapter = MusicAssistantAdapter.from_player(hass, player_entity)
    except MusicAssistantUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err

    queue = QueueCoordinator(hass, entry, adapter)
    playlists = PlaylistCoordinator(hass, entry, adapter)
    runtime = MediaControllerRuntime(adapter, queue, playlists)

    try:
        await asyncio.gather(
            queue.async_config_entry_first_refresh(),
            playlists.async_config_entry_first_refresh(),
        )
    except Exception:
        await runtime.async_shutdown()
        raise

    runtime.controller_entities = ControllerEntities(player_entity)
    runtime.clients = _build_clients(hass, entry, runtime.controller_entities)
    runtime.subentry_fingerprint = _subentry_fingerprint(entry)
    _async_remove_orphaned_entities(hass, entry, runtime.clients)

    entry.runtime_data = runtime
    hass.data[DOMAIN][entry.entry_id] = runtime
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    queue.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when a panel subentry was added, edited, or removed."""
    runtime: MediaControllerRuntime | None = getattr(
        entry, "runtime_data", None
    )
    if runtime is None:
        return
    if runtime.subentry_fingerprint == _subentry_fingerprint(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and all entry-owned resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    runtime: MediaControllerRuntime = entry.runtime_data
    await runtime.async_shutdown()
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
