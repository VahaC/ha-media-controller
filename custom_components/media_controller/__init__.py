"""Media Controller integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ATTR_ENTRY_ID,
    ATTR_QUEUE_ITEM_ID,
    CONF_CONTROLLER_ENTRY_ID,
    CONF_ENTITIES,
    CONF_PANEL_ID,
    CONF_PANEL_SETTINGS,
    CONF_PANEL_THEME,
    CONF_PLAYER_ENTITY,
    CONF_PROFILE,
    CONF_SLOTS,
    CONF_REFRESH_TOKEN_ID,
    CONF_USER_ID,
    DATA_CONTROLLER_ENTITIES,
    DATA_PANELS,
    DATA_PROVISIONING,
    DATA_RUNTIMES,
    DOMAIN,
    ENTRY_VERSION,
    LEGACY_SLOTS,
    LEGACY_TITLE_PREFIX,
    PANEL_PLATFORMS,
    PLATFORMS,
    SERVICE_PLAY_QUEUE_ITEM,
    SERVICE_REFRESH,
    panel_entity_unique_id,
    slot_unique_id,
)
from .compatibility import (
    async_clear_panel_issue,
    async_update_panel_issue,
)
from .coordinator import PlaylistCoordinator, QueueCoordinator
from .entries import is_panel_entry
from .music_assistant import MusicAssistantAdapter, MusicAssistantUnavailable
from .profiles import (
    SOURCE,
    UPDATE_KIND_FIRMWARE,
    ClientProfile,
    panel_profile,
)
from .pairing import PairingStore
from .icons import async_setup_icon_endpoints
from .panel_card import async_setup_card_endpoint
from .panel_firmware import (
    async_firmware_index,
    async_setup_firmware_endpoints,
)
from .panel_layout import async_setup_layout_endpoint
from .panel_provision import async_deliver_bootstrap
from .panel_push import async_start_push
from .panel_state import (
    THEME_COLOR_DEFAULTS,
    THEME_OPACITY_DEFAULTS,
    PanelSettings,
    PanelState,
    PanelTheme,
)
from .provision import PanelProvisionView
from .devices import controller_device_info, panel_device_info
from .registry import RegistryEntry
from .slots import (
    ClientConfiguration,
    ControllerEntities,
    resolve_entries,
    stored_entries,
)
from .status import (
    PanelStatusView,
    async_register_panel,
    async_unregister_panel,
)
from .tokens import async_revoke_panel_token
from .transformations import migrate_v2_title, migrate_v3_section

_LOGGER = logging.getLogger(__name__)

# There is no YAML for this domain: every controller and panel arrives
# through the config flow. The schema says so, and rejects the key.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


# How often the panel's own entities are re-evaluated. Nothing changes on
# this tick; it exists so that a tablet which stopped reporting becomes
# unavailable on its own rather than at the next unrelated update.
PANEL_PRESENCE_INTERVAL = timedelta(seconds=30)


@dataclass(slots=True)
class PanelRuntime:
    """Runtime objects owned by one panel entry."""

    client: ClientConfiguration
    device_info: DeviceInfo
    state: PanelState
    panel_id: str
    # Monotonic, and only ever read as a duration. It is what lets a panel
    # that has never reported be told apart from one that was set up a moment
    # ago and has not had time to; see compatibility.py.
    loaded_at: float = 0.0
    cancel_presence: Callable[[], None] | None = None
    cancel_registry: Callable[[], None] | None = None
    # Stops watching the two states this panel is sent rather than asked for.
    # None for a panel whose config sensor did not exist when setup ran, which
    # is a panel that polls -- see panel_push.py.
    cancel_push: Callable[[], None] | None = None

    async def async_shutdown(self) -> None:
        """Stop the timers and listeners a panel owns."""
        if self.cancel_presence is not None:
            self.cancel_presence()
            self.cancel_presence = None
        if self.cancel_registry is not None:
            self.cancel_registry()
            self.cancel_registry = None
        if self.cancel_push is not None:
            self.cancel_push()
            self.cancel_push = None


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


def _entry_registry(entry: ConfigEntry) -> list[RegistryEntry]:
    """Return the registry of a panel entry, options overriding data."""
    if CONF_ENTITIES in entry.options:
        return stored_entries(entry.options, CONF_ENTITIES)
    return stored_entries(entry.data, CONF_ENTITIES)


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
    """Delete rows this entry no longer has an entity for.

    Anything left behind would sit permanently unavailable with no way to
    remove it, which is what the room-control proxies of contract version 8
    would otherwise do to every installation that ever had one.
    """
    expected: set[tuple[str, str]] = set(extra or ())
    expected.add(("sensor", f"{client.owner_id}_config"))

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
    data.setdefault(DATA_PANELS, {})
    pairings = data.setdefault(DATA_PROVISIONING, PairingStore())

    # Unauthenticated by necessity: a panel asking for its first token has no
    # credentials to present. See pairing.py for what guards it instead.
    hass.http.register_view(PanelProvisionView(hass, pairings))
    # Authenticated, and only for the panel's own user. See status.py.
    hass.http.register_view(PanelStatusView(hass))
    # The same ownership check, for the durable copy of a panel's own grid.
    # See panel_layout.py for why it is an endpoint of its own.
    async_setup_layout_endpoint(hass)
    # And again, for the one thing the on-device layout editor may write back
    # to Home Assistant: the display name and icon of a card it already draws.
    # See panel_card.py for how narrow that is and why it has to be.
    async_setup_card_endpoint(hass)
    # The firmware a panel can install without a cable. The manifest half is
    # authenticated the same way; the image half cannot be, because ESPHome's
    # HTTP update client sends no Authorization header, and is guarded by a
    # single-use nonce the manifest hands out instead. See panel_firmware.py.
    async_setup_firmware_endpoints(hass)
    # The card artwork itself. Authenticated like everything else, and a
    # separate request rather than a block on the config sensor: panels poll
    # that sensor about once a second, and a catalog that changes when the
    # integration is upgraded has no business on that channel.
    async_setup_icon_endpoints(hass)

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
    """Bring an entry up to the current version, one version at a time.

    Each step is written as `version < n` rather than `version == n - 1`, so
    an entry that has sat through several releases passes through every step
    in order instead of skipping the ones between where it was and here.
    """
    if entry.version > ENTRY_VERSION:
        # Downgrading is not supported; refuse rather than corrupt the entry.
        return False

    if entry.version < 3:
        _async_migrate_v2_title(hass, entry)
    if entry.version < 4:
        _async_migrate_v3_slots(hass, entry)

    if entry.version != ENTRY_VERSION:
        hass.config_entries.async_update_entry(entry, version=ENTRY_VERSION)
    return True


@callback
def _async_migrate_v2_title(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the "Media Controller – " prefix from a source's title.

    Only sources carry it, and only the ones whose title has not been edited
    since. The title is what names the device, so every entity of the source
    gets a shorter friendly name; entity IDs are registry rows and do not move.
    """
    if is_panel_entry(entry):
        return
    previous = entry.title
    title = migrate_v2_title(previous, LEGACY_TITLE_PREFIX)
    if title == previous:
        return
    hass.config_entries.async_update_entry(entry, title=title)
    _LOGGER.info("Renamed %s to %s", previous, title)


@callback
def _async_migrate_v3_slots(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the room-control slots and the proxies they created.

    Contract version 9 deletes both, together with the classic firmware that
    was the only thing that ever read them. Two things are left behind by an
    entry that had any, and neither goes away on its own:

    * the stored `slots` block, and — on an entry old enough — the four
      version 1 keys that preceded it. Nothing reads either, so they are
      dropped rather than carried forward for the life of the entry;
    * one entity-registry row per proxy. Deleting the entity is not enough:
      a row whose entity never comes back sits unavailable forever, and the
      user cannot remove it while the config entry that owns it is loaded.

    Both proxy naming schemes are looked for. Version 1 registered
    `<entry>_light_1_entity`, version 2 renamed the same rows to
    `<entry>_slot_1`, and an installation that skipped straight from 1 to
    here has the first shape and never had the second.
    """
    if is_panel_entry(entry):
        return

    registry = er.async_get(hass)
    for index, legacy_key, domain in LEGACY_SLOTS:
        for unique_id in (
            slot_unique_id(entry.entry_id, index),
            f"{entry.entry_id}_{legacy_key}",
        ):
            entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
            if entity_id is not None:
                _LOGGER.info(
                    "Removing the room-control proxy %s: contract version 9 "
                    "has no slots",
                    entity_id,
                )
                registry.async_remove(entity_id)

    dead = {CONF_SLOTS, *(key for _, key, _ in LEGACY_SLOTS)}
    data = migrate_v3_section(entry.data, dead)
    options = migrate_v3_section(entry.options, dead)
    if data != dict(entry.data) or options != dict(entry.options):
        hass.config_entries.async_update_entry(
            entry, data=data, options=options
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up either kind of Media Controller entry."""
    if is_panel_entry(entry):
        return await _async_setup_panel(hass, entry)
    return await _async_setup_controller(hass, entry)


async def _async_setup_controller(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up a source: the Music Assistant side and its three sensors."""
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
        SOURCE,
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
    """Set up a panel: its own entities and its own config sensor."""
    # The controller can be changed in the panel's options, exactly like a
    # registry element, so the option wins over the one chosen when it was
    # added.
    controller_entry_id = _configured_value(entry, CONF_CONTROLLER_ENTRY_ID)
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
    state = PanelState(
        PanelSettings.from_stored(entry.data.get(CONF_PANEL_SETTINGS)),
        PanelTheme.from_stored(entry.data.get(CONF_PANEL_THEME)),
    )
    client = ClientConfiguration(
        hass,
        entry.entry_id,
        profile,
        _async_controller_entities(hass, controller_entry),
        state,
        resolve_entries(hass, profile, _entry_registry(entry)),
    )
    panel_id = entry.data.get(CONF_PANEL_ID, "")
    runtime = PanelRuntime(
        client,
        panel_device_info(entry, controller_entry, profile),
        state,
        panel_id,
        time.monotonic(),
    )
    _async_remove_orphaned_entities(
        hass, entry, client, _panel_own_entities(entry, profile)
    )

    # The panel's own user is what the status endpoint checks a report
    # against, so a panel paired before that field existed simply never
    # reports and its diagnostic entities stay unavailable.
    async_register_panel(
        hass,
        panel_id,
        state,
        entry.data.get(CONF_USER_ID, ""),
        entry.entry_id,
    )

    @callback
    def _async_update_offered() -> bool:
        """Return whether this panel has a firmware waiting on its own entity.

        Only a client that can be updated from Home Assistant can have one,
        and only when a build is actually being held out: an ESP32 panel that
        is behind with nothing published for it, or with a build held back
        because the integration is the older half, is offered nothing and
        must still be reported by the repair issue.
        """
        if profile.update_kind != UPDATE_KIND_FIRMWARE:
            return False
        index = async_firmware_index(hass)
        return (
            index.offer(
                state.status.app_version, state.status.contract_version
            )
            is not None
        )

    @callback
    def _async_presence_tick(_now: Any) -> None:
        """Re-evaluate availability, so a silent panel stops looking present."""
        state.notify()
        # The same tick answers the other question silence raises: whether
        # this panel has ever reported at all. A report cannot be waited for,
        # so it is re-read here rather than pushed from the endpoint.
        async_update_panel_issue(
            hass,
            entry,
            state,
            loaded_at=runtime.loaded_at,
            update_offered=_async_update_offered(),
        )

    runtime.cancel_presence = async_track_time_interval(
        hass, _async_presence_tick, PANEL_PRESENCE_INTERVAL
    )

    @callback
    def _async_entity_registry_updated(event: Any) -> None:
        """Follow a registry element's target when its entity ID is renamed.

        A `rid` is what a panel keys its own grid on precisely because entity
        IDs move, but the payload still has to carry the entity ID the target
        has now, and the panel should not have to wait for a reload to be told.
        """
        if event.data.get("action") != "update":
            return
        if "entity_id" not in (event.data.get("changes") or {}):
            return
        client.async_refresh_registry_targets()

    runtime.cancel_registry = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, _async_entity_registry_updated
    )

    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PANEL_PLATFORMS)

    # A panel that was just paired over its own provisioning endpoint is still
    # waiting for the three things it needs, and one of them is the entity ID
    # of the config sensor the line above has only now created. Delivering it
    # is therefore the last thing setup does, and it is a background task: a
    # device that has gone quiet must not hold up the entry it belongs to.
    #
    # It returns immediately unless a pairing is waiting with a token
    # attached, so every ordinary reload passes straight through.
    entry.async_create_background_task(
        hass,
        async_deliver_bootstrap(hass, entry),
        f"media_controller provision {entry.entry_id}",
    )

    # Watching the two states this panel would otherwise poll for. After the
    # platforms, for the same reason the delivery above is: the config sensor
    # it follows is created by them, and there is nothing to subscribe to
    # until it exists. A panel whose sensor is not there yet gets None and
    # goes on polling; the next reload finds it.
    #
    # Nothing is pushed until the panel has reported a key, so this being
    # started here says only that Home Assistant is watching -- whether it
    # speaks is the panel's answer to give.
    runtime.cancel_push = async_start_push(hass, entry, runtime.state)
    return True


# The entities a panel device owns beyond its config sensor. Each is
# (platform domain, unique-ID suffix); the suffix is also the entity
# translation key.
#
# This list is what `_async_remove_orphaned_entities` keeps: a row that is not
# in it is deleted from the entity registry on every setup. Anything a panel
# platform creates therefore has to be named here, including the entities only
# some profiles get — a key that is missing costs the user their entity ID
# customisations once per reload.
PANEL_OWN_ENTITIES: tuple[tuple[str, str], ...] = (
    ("sensor", "battery"),
    ("sensor", "uptime"),
    ("sensor", "last_report"),
    ("sensor", "wifi_signal"),
    ("sensor", "temperature"),
    ("binary_sensor", "connected"),
    ("binary_sensor", "charging"),
    ("switch", "screen"),
    ("button", "restart"),
    ("select", "page"),
    ("select", "player_skin"),
    ("select", "screen_rotation"),
    ("number", "poll_interval"),
    ("number", "playlist_poll_interval"),
    ("number", "screen_off"),
    ("number", "screen_brightness"),
    ("update", "firmware"),
)

# The theme entities, for a profile that has a theme, and the diagnostic
# sensors, for one that reports them. They are kept apart from the list above
# because both are per-profile: a panel that has neither must not be left with
# nineteen rows it will never fill, and one that has them must not have them
# deleted as orphans.
PANEL_THEME_ENTITIES: tuple[tuple[str, str], ...] = (
    *(("text", key) for key in THEME_COLOR_DEFAULTS),
    *(("number", key) for key in THEME_OPACITY_DEFAULTS),
)
PANEL_DIAGNOSTIC_ENTITIES: tuple[tuple[str, str], ...] = (
    ("sensor", "heap_free"),
    ("sensor", "heap_max_block"),
    ("sensor", "heap_min_free"),
    ("sensor", "heap_fragmentation"),
    ("sensor", "psram_free"),
    ("sensor", "loop_time"),
    ("sensor", "http_ms"),
    ("sensor", "reset_reason"),
)


@callback
def _panel_own_entities(
    entry: ConfigEntry,
    profile: ClientProfile,
) -> set[tuple[str, str]]:
    """Return the registry keys of the entities this panel owns itself."""
    keys = list(PANEL_OWN_ENTITIES)
    if profile.has_theme:
        keys.extend(PANEL_THEME_ENTITIES)
    if profile.reports_diagnostics:
        keys.extend(PANEL_DIAGNOSTIC_ENTITIES)
    return {
        (domain, panel_entity_unique_id(entry.entry_id, key))
        for domain, key in keys
    }


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Revoke a deleted panel's token so it cannot be used again."""
    if not is_panel_entry(entry):
        return
    # A repair issue outlives an unload on purpose, so a restart does not make
    # it flicker. Removing the panel is the one event that really ends it.
    async_clear_panel_issue(hass, entry)
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
    platforms = PANEL_PLATFORMS if is_panel_entry(entry) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, platforms
    )
    if not unload_ok:
        return False
    runtime = entry.runtime_data
    if isinstance(runtime, PanelRuntime):
        async_unregister_panel(hass, runtime.panel_id)
    await runtime.async_shutdown()
    hass.data[DOMAIN][DATA_RUNTIMES].pop(entry.entry_id, None)
    hass.data[DOMAIN][DATA_CONTROLLER_ENTITIES].pop(entry.entry_id, None)
    return True
