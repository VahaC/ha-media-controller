"""Media Controller integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
    CONF_CONTROLLER_ENTRY_ID,
    CONF_PANEL_ID,
    CONF_PLAYER_ENTITY,
    CONF_PROFILE,
    CONF_SLOTS,
    CONF_REFRESH_TOKEN_ID,
    CONF_USER_ID,
    DATA_CONTROLLER_ENTITIES,
    DATA_PROVISIONING,
    DATA_RUNTIMES,
    DOMAIN,
    ENTRY_VERSION,
    LEGACY_SLOTS,
    PLATFORMS,
    SERVICE_PLAY_QUEUE_ITEM,
    SERVICE_REFRESH,
    slot_unique_id,
)
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .entries import is_panel_entry
from .music_assistant import MusicAssistantAdapter, MusicAssistantUnavailable
from .profiles import (
    CONTROL_TOGGLE,
    CONTROLLER_PROFILE,
    limit_controls,
    panel_profile,
)
from .pairing import PairingStore
from .provision import PanelProvisionView
from .proxy import controller_device_info, panel_device_info
from .slots import (
    ClientConfiguration,
    ControllerEntities,
    resolve_slots,
    stored_slots,
)
from .tokens import async_revoke_panel_token
from .transformations import SlotConfig, migrate_v1_section

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PanelRuntime:
    """Runtime objects owned by one panel entry."""

    client: ClientConfiguration
    device_info: DeviceInfo

    async def async_shutdown(self) -> None:
        """A panel owns no timers of its own."""


@dataclass(slots=True)
class MediaControllerRuntime:
    """Runtime objects owned by one controller entry."""

    adapter: MusicAssistantAdapter
    queue: QueueCoordinator
    playlists: PlaylistCoordinator
    client: ClientConfiguration
    device_info: DeviceInfo

    async def async_shutdown(self) -> None:
        """Stop entry-owned listeners and timers."""
        await self.queue.async_shutdown()
        await self.playlists.async_shutdown()


def _configured_value(entry: ConfigEntry, key: str) -> Any:
    """Return an option override or the original config-flow value."""
    return entry.options.get(key, entry.data.get(key))


def _entry_slots(entry: ConfigEntry) -> list[SlotConfig]:
    """Return the slots of an entry, options overriding the original data."""
    if CONF_SLOTS in entry.options:
        return stored_slots(entry.options, CONF_SLOTS)
    return stored_slots(entry.data, CONF_SLOTS)


@callback
def _async_controller_entities(
    hass: HomeAssistant,
    controller_entry: ConfigEntry,
) -> ControllerEntities:
    """Return the shared entity record of one controller.

    A panel is a separate config entry, so it cannot reach into a controller's
    runtime; both share this object instead. It is seeded from the entity
    registry, which outlives an unloaded controller, and is then kept current
    by the controller's own sensors as they are added.
    """
    shared: dict[str, ControllerEntities] = hass.data[DOMAIN][
        DATA_CONTROLLER_ENTITIES
    ]
    player_entity = _configured_value(controller_entry, CONF_PLAYER_ENTITY) or ""
    if (existing := shared.get(controller_entry.entry_id)) is not None:
        existing.player_entity = player_entity
        return existing

    entities = ControllerEntities(player_entity)
    registry = er.async_get(hass)
    entities.queue_entity_id = (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{controller_entry.entry_id}_queue"
        )
        or ""
    )
    entities.playlists_entity_id = (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{controller_entry.entry_id}_playlists"
        )
        or ""
    )
    shared[controller_entry.entry_id] = entities
    return entities


@callback
def _async_remove_orphaned_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: ClientConfiguration,
    extra: set[tuple[str, str]] | None = None,
) -> None:
    """Delete registry entries for slots that no longer exist.

    Clearing a slot must not leave a permanently unavailable proxy behind.
    """
    expected: set[tuple[str, str]] = set(extra or ())
    expected.add(("sensor", f"{client.owner_id}_config"))
    for slot in client.slots:
        expected.add((slot.domain, slot_unique_id(client.owner_id, slot.index)))

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
    """Resolve a controller runtime by entry ID or player entity."""
    runtimes: dict[str, MediaControllerRuntime] = hass.data[DOMAIN][
        DATA_RUNTIMES
    ]
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
    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault(DATA_RUNTIMES, {})
    data.setdefault(DATA_CONTROLLER_ENTITIES, {})
    pairings = data.setdefault(DATA_PROVISIONING, PairingStore())

    # Unauthenticated by necessity: a panel asking for its first token has no
    # credentials to present. See pairing.py for what guards it instead.
    hass.http.register_view(PanelProvisionView(hass, pairings))

    async def async_handle_refresh(call: ServiceCall) -> None:
        runtimes: dict[str, MediaControllerRuntime] = hass.data[DOMAIN][
            DATA_RUNTIMES
        ]
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
    """Set up either kind of Media Controller entry."""
    if is_panel_entry(entry):
        return await _async_setup_panel(hass, entry)
    return await _async_setup_controller(hass, entry)


async def _async_setup_controller(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up a controller: the Music Assistant side and the ESP32 slots."""
    player_entity = _configured_value(entry, CONF_PLAYER_ENTITY)
    try:
        adapter = MusicAssistantAdapter.from_player(hass, player_entity)
    except MusicAssistantUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err

    queue = QueueCoordinator(hass, entry, adapter)
    playlists = PlaylistCoordinator(hass, entry, adapter)

    try:
        await asyncio.gather(
            queue.async_config_entry_first_refresh(),
            playlists.async_config_entry_first_refresh(),
        )
    except Exception:
        await queue.async_shutdown()
        await playlists.async_shutdown()
        raise

    client = ClientConfiguration(
        hass,
        entry.entry_id,
        CONTROLLER_PROFILE,
        resolve_slots(hass, CONTROLLER_PROFILE, _entry_slots(entry)),
        _async_controller_entities(hass, entry),
    )
    runtime = MediaControllerRuntime(
        adapter, queue, playlists, client, controller_device_info(entry)
    )
    _async_remove_orphaned_entities(
        hass,
        entry,
        client,
        {
            ("sensor", f"{entry.entry_id}_queue"),
            ("sensor", f"{entry.entry_id}_playlists"),
        },
    )

    entry.runtime_data = runtime
    hass.data[DOMAIN][DATA_RUNTIMES][entry.entry_id] = runtime

    queue.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_setup_panel(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a panel: its own proxies and its own config sensor."""
    controller_entry_id = entry.data.get(CONF_CONTROLLER_ENTRY_ID)
    controller_entry = (
        hass.config_entries.async_get_entry(controller_entry_id)
        if controller_entry_id
        else None
    )
    if controller_entry is None or is_panel_entry(controller_entry):
        raise ConfigEntryNotReady(
            "The media controller this panel belongs to no longer exists. "
            "Remove the panel and add it again."
        )

    profile = panel_profile(entry.data.get(CONF_PROFILE))
    client = ClientConfiguration(
        hass,
        entry.entry_id,
        profile,
        resolve_slots(hass, profile, _entry_slots(entry)),
        _async_controller_entities(hass, controller_entry),
    )
    runtime = PanelRuntime(
        client, panel_device_info(entry, controller_entry, profile)
    )
    _async_remove_orphaned_entities(hass, entry, client)

    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Revoke a deleted panel's token so it cannot be used again."""
    if not is_panel_entry(entry):
        return
    pairings: PairingStore | None = hass.data.get(DOMAIN, {}).get(
        DATA_PROVISIONING
    )
    if pairings is not None:
        pairings.discard(entry.data.get(CONF_PANEL_ID, ""))
    await async_revoke_panel_token(
        hass,
        entry.data.get(CONF_USER_ID),
        entry.data.get(CONF_REFRESH_TOKEN_ID),
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and all entry-owned resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    runtime = entry.runtime_data
    await runtime.async_shutdown()
    hass.data[DOMAIN][DATA_RUNTIMES].pop(entry.entry_id, None)
    hass.data[DOMAIN][DATA_CONTROLLER_ENTITIES].pop(entry.entry_id, None)
    return True
