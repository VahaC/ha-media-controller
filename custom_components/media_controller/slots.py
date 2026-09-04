"""Room-control configuration shared by the flows and the entities.

Two shapes live here, one per kind of client.

* A **slot** is a numbered position backed by a proxy entity. Only the classic
  ESP32 firmware has any, because it resolves entity IDs and service domains
  while compiling; they are stored on the controller config entry.
* A **registry element** is one entry of a panel's unbounded entity list. It
  names the real entity, has no proxy, and is stored on the panel config
  entry. See `registry.py` and docs/CONTRACT.md.

Both are read back here into the object the proxies and the config sensor use.
See docs/ROOM_SLOTS.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import slot_entity_key, slot_label_key
from .contract import CONTRACT_VERSION
from .profiles import (
    CAP_CONTROLS,
    CAP_MAX_KELVIN,
    CAP_MAX_TEMP,
    CAP_MIN_KELVIN,
    CAP_MIN_TEMP,
    CAP_TEMP_STEP,
    CONTROL_TOGGLE,
    ClientProfile,
    capability_signature,
    limit_controls,
    normalize_capabilities,
)
from .panel_state import PanelState
from .registry import (
    RegistryEntry,
    resolve_entity_ids,
    sort_entries,
    stored_entries,
)
from .transformations import (
    ClientConfigPayload,
    EntityPayload,
    SlotConfig,
    SlotPayload,
    room_state_values,
    stored_slots,
)

__all__ = [
    "ClientConfiguration",
    "ControllerEntities",
    "RegistryEntry",
    "SlotConfig",
    "resolve_entries",
    "resolve_slots",
    "slots_from_input",
    "stored_entries",
    "stored_slots",
    "suggested_slot_values",
]


def _resolve_capabilities(
    hass: HomeAssistant,
    slot: SlotConfig,
    profile: ClientProfile,
) -> SlotConfig:
    """Refresh a slot's capabilities from the live target when it exists.

    The stored snapshot is kept when the target is missing, so a slot still
    renders correctly while the light it points at is unavailable.
    """
    state = hass.states.get(slot.target_entity_id)
    if state is None:
        return slot

    capabilities = normalize_capabilities(slot.domain, state.attributes)
    return replace(
        slot,
        controls=limit_controls(
            capabilities[CAP_CONTROLS], profile.spec(slot.index)
        ),
        min_kelvin=capabilities.get(CAP_MIN_KELVIN),
        max_kelvin=capabilities.get(CAP_MAX_KELVIN),
    )


def resolve_slots(
    hass: HomeAssistant,
    profile: ClientProfile,
    slots: Iterable[SlotConfig],
) -> list[SlotConfig]:
    """Return the slots a client actually gets, capabilities refreshed."""
    return [
        _resolve_capabilities(hass, slot, profile)
        for slot in slots
        if profile.spec(slot.index) is not None
    ]


def seed_registry_ids(
    hass: HomeAssistant,
    entries: Iterable[RegistryEntry],
) -> list[RegistryEntry]:
    """Record each target's entity-registry row ID before storing it.

    This is what a later rename is followed by. It is done when the form is
    saved rather than at load, because at load the entity ID may already have
    moved and there would be nothing left to look the row up by.
    """
    registry = er.async_get(hass)
    seeded: list[RegistryEntry] = []
    for entry in entries:
        row = registry.async_get(entry.target_entity_id)
        seeded.append(
            entry if row is None else replace(entry, registry_id=row.id)
        )
    return seeded


def _registry_lookup(
    hass: HomeAssistant,
) -> Callable[[RegistryEntry], tuple[str, str]]:
    """Return the entity-registry lookup the rename rule needs.

    Home Assistant keeps a registry row's ID across a rename, so an element
    that recorded one follows its entity. An element that has none — one saved
    before this field existed, or one pointing at an entity outside the
    registry — is looked up by entity ID, which also seeds the row ID for the
    next time.
    """
    registry = er.async_get(hass)

    def lookup(entry: RegistryEntry) -> tuple[str, str]:
        if entry.registry_id:
            row = registry.entities.get_entry(entry.registry_id)
            if row is not None:
                return row.entity_id, row.id
            # The row is gone. Keep the last known entity ID rather than
            # clearing the element: the entity may come back under it.
            return "", ""
        row = registry.async_get(entry.target_entity_id)
        if row is None:
            return "", ""
        return row.entity_id, row.id

    return lookup


def _resolve_entry_capabilities(
    hass: HomeAssistant,
    entry: RegistryEntry,
    profile: ClientProfile,
) -> RegistryEntry:
    """Refresh one registry element's controls from its live target."""
    state = hass.states.get(entry.target_entity_id)
    if state is None:
        return entry

    capabilities = normalize_capabilities(entry.domain, state.attributes)
    return replace(
        entry,
        controls=limit_controls(capabilities[CAP_CONTROLS], profile),
        min_kelvin=capabilities.get(CAP_MIN_KELVIN),
        max_kelvin=capabilities.get(CAP_MAX_KELVIN),
        min_temp=capabilities.get(CAP_MIN_TEMP),
        max_temp=capabilities.get(CAP_MAX_TEMP),
        target_temp_step=capabilities.get(CAP_TEMP_STEP),
    )


def resolve_entries(
    hass: HomeAssistant,
    profile: ClientProfile,
    entries: Iterable[RegistryEntry],
) -> list[RegistryEntry]:
    """Return the registry a panel actually gets.

    Every element is followed through a Home Assistant rename first, so that
    capabilities are read from the entity the element still means, and the
    whole list is capped at the profile's limit: a registry that grew past it
    because the profile changed is truncated rather than sent as it is.
    """
    if not profile.has_registry:
        return []
    followed = resolve_entity_ids(entries, _registry_lookup(hass))
    resolved = [
        _resolve_entry_capabilities(hass, entry, profile)
        for entry in followed
    ]
    return sort_entries(resolved)[: profile.entity_limit]


def slots_from_input(
    hass: HomeAssistant,
    profile: ClientProfile,
    user_input: Mapping[str, Any],
    previous: Iterable[SlotConfig] = (),
) -> list[SlotConfig]:
    """Convert a submitted slot form into stored slot records."""
    known = {slot.index: slot for slot in previous}
    slots: list[SlotConfig] = []

    for spec in profile.slots:
        target = user_input.get(slot_entity_key(spec.index))
        if not target:
            continue
        label = str(user_input.get(slot_label_key(spec.index)) or "").strip()
        domain = str(target).split(".")[0]
        state = hass.states.get(str(target))
        if state is not None:
            capabilities = normalize_capabilities(domain, state.attributes)
            controls = limit_controls(capabilities[CAP_CONTROLS], spec)
            min_kelvin = capabilities.get(CAP_MIN_KELVIN)
            max_kelvin = capabilities.get(CAP_MAX_KELVIN)
        elif (kept := known.get(spec.index)) is not None and (
            kept.target_entity_id == target
        ):
            controls = kept.controls
            min_kelvin = kept.min_kelvin
            max_kelvin = kept.max_kelvin
        else:
            # A target that does not exist yet can still be toggled; the real
            # capabilities are picked up the next time the entry is loaded.
            controls = limit_controls((CONTROL_TOGGLE,), spec)
            min_kelvin = None
            max_kelvin = None

        slots.append(
            SlotConfig(
                index=spec.index,
                target_entity_id=str(target),
                domain=domain,
                label=label,
                controls=controls,
                min_kelvin=min_kelvin,
                max_kelvin=max_kelvin,
            )
        )
    return slots


def suggested_slot_values(slots: Iterable[SlotConfig]) -> dict[str, Any]:
    """Return current slot values as config-flow form suggestions."""
    suggestions: dict[str, Any] = {}
    for slot in slots:
        suggestions[slot_entity_key(slot.index)] = slot.target_entity_id
        if slot.label:
            suggestions[slot_label_key(slot.index)] = slot.label
    return suggestions


class ControllerEntities:
    """The three entities every client of one controller reads.

    The queue and playlist sensors report their own entity IDs once Home
    Assistant has assigned them, for the same reason the slot proxies do.
    """

    def __init__(self, player_entity: str) -> None:
        """Initialize with the configured Music Assistant player."""
        self.player_entity = player_entity or ""
        self.queue_entity_id = ""
        self.playlists_entity_id = ""
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to entity ID changes."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _async_notify(self) -> None:
        """Tell every client that the controller entities changed."""
        for listener in list(self._listeners):
            listener()

    @callback
    def async_set_queue_entity_id(self, entity_id: str) -> None:
        """Record the entity ID of the queue sensor."""
        if self.queue_entity_id != entity_id:
            self.queue_entity_id = entity_id
            self._async_notify()

    @callback
    def async_set_playlists_entity_id(self, entity_id: str) -> None:
        """Record the entity ID of the playlists sensor."""
        if self.playlists_entity_id != entity_id:
            self.playlists_entity_id = entity_id
            self._async_notify()


class ClientConfiguration:
    """The slots of one client device and the proxies they resolve to.

    Proxies report their own entity ID once Home Assistant has assigned one,
    so the config sensor never has to guess a registry entity ID or depend on
    the order in which platforms are set up.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        owner_id: str,
        profile: ClientProfile,
        slots: Iterable[SlotConfig],
        controller: ControllerEntities,
        panel: PanelState | None = None,
        entries: Iterable[RegistryEntry] = (),
    ) -> None:
        """Initialize one client's configuration.

        `panel` is the settings and command channel of a panel device. The
        ESP32 controller has none: it applies nothing at runtime, so sending
        it settings it cannot act on would only mislead a reader of the
        payload.

        `slots` and `entries` are the two shapes a client's room controls take
        and no client has both: the classic ESP32 carries slots, and a panel
        carries a registry.
        """
        self.hass = hass
        self.owner_id = owner_id
        self.profile = profile
        self.slots: list[SlotConfig] = list(slots)
        self.entries: list[RegistryEntry] = list(entries)
        self.controller = controller
        self.panel = panel
        self._proxy_entity_ids: dict[int, str] = {}
        # Reported by the skin select once Home Assistant has assigned it one,
        # the same way a proxy reports its own. A panel that offers a skin
        # picker on the device needs the entity ID to write to, and guessing
        # it from the device name would survive only until somebody renamed
        # something.
        self._skin_select_entity_id = ""
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to proxy, controller, and panel changes."""
        self._listeners.append(listener)
        remove_controller = self.controller.async_add_listener(listener)
        remove_panel = (
            self.panel.add_config_listener(listener)
            if self.panel is not None
            else None
        )

        def remove() -> None:
            remove_controller()
            if remove_panel is not None:
                remove_panel()
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def async_set_proxy_entity_id(self, index: int, entity_id: str) -> None:
        """Record the entity ID Home Assistant gave one slot proxy."""
        if self._proxy_entity_ids.get(index) == entity_id:
            return
        self._proxy_entity_ids[index] = entity_id
        for listener in list(self._listeners):
            listener()

    @callback
    def async_set_skin_select_entity_id(self, entity_id: str) -> None:
        """Record the entity ID Home Assistant gave this panel's skin select."""
        if self._skin_select_entity_id == entity_id:
            return
        self._skin_select_entity_id = entity_id
        for listener in list(self._listeners):
            listener()

    @callback
    def async_refresh_target_capabilities(self, entity_id: str) -> None:
        """Refresh one target's capabilities without recreating its proxy."""
        refreshed: list[SlotConfig] = []
        changed = False
        for slot in self.slots:
            updated = (
                _resolve_capabilities(self.hass, slot, self.profile)
                if slot.target_entity_id == entity_id
                else slot
            )
            refreshed.append(updated)
            changed = changed or updated != slot

        refreshed_entries: list[RegistryEntry] = []
        for entry in self.entries:
            updated_entry = (
                _resolve_entry_capabilities(self.hass, entry, self.profile)
                if entry.target_entity_id == entity_id
                else entry
            )
            refreshed_entries.append(updated_entry)
            changed = changed or updated_entry != entry

        if not changed:
            return
        self.slots = refreshed
        self.entries = refreshed_entries
        for listener in list(self._listeners):
            listener()

    @callback
    def async_refresh_registry_targets(self) -> None:
        """Follow the registry's targets after a Home Assistant rename.

        The stored element is left as it was: `registry_id` is the anchor and
        the entity ID in it is only a fallback, so a rename costs no write to
        the config entry. What changes is the payload, which always carries
        the entity ID the target has now.
        """
        if not self.profile.has_registry:
            return
        refreshed = resolve_entries(self.hass, self.profile, self.entries)
        if refreshed == self.entries:
            return
        self.entries = refreshed
        for listener in list(self._listeners):
            listener()

    @property
    def target_entity_ids(self) -> set[str]:
        """Return every entity whose capabilities this client depends on."""
        return {slot.target_entity_id for slot in self.slots} | {
            entry.target_entity_id for entry in self.entries
        }

    def _label(self, slot: SlotConfig) -> str:
        """Return the tile label, falling back to the target's name."""
        if slot.label:
            return slot.label
        state = self.hass.states.get(slot.target_entity_id)
        if state is not None and state.name:
            return state.name
        return slot.target_entity_id

    def _entry_name(self, entry: RegistryEntry) -> str:
        """Return the tile name, falling back to the entity's own name."""
        if entry.name:
            return entry.name
        state = self.hass.states.get(entry.target_entity_id)
        if state is not None and state.name:
            return state.name
        return entry.target_entity_id
    def room_states(self) -> dict[str, list[Any]]:
        """Render the current state of every registry element, keyed by rid.

        Read live from the state machine on every call: the config sensor is
        polled by panels, and what it serves must be the state as of the
        request rather than as of the last configuration change. An element
        whose entity is gone reads as unknown rather than keeping a stale
        value. The classic ESP32 controller has no registry and gets no
        block; it learns its four states over the native API instead.
        """
        if not self.profile.has_registry:
            return {}
        states: dict[str, list[Any]] = {}
        for entry in self.entries:
            target = self.hass.states.get(entry.target_entity_id)
            if target is None:
                states[entry.rid] = ["unknown"]
            else:
                states[entry.rid] = room_state_values(
                    entry.domain, target.state, target.attributes
                )
        return states

    def payload(self) -> ClientConfigPayload:
        """Build what this client reads from its config sensor.

        Exactly one of the two room-control blocks is filled in. A client is
        never sent the one it does not read: a panel gets no `slots`, and the
        classic ESP32 firmware gets no `entities`.
        """
        panel = self.panel.as_payload() if self.panel is not None else {}
        registry = self.profile.has_registry
        return ClientConfigPayload(
            settings=panel.get("settings"),
            commands=panel.get("commands"),
            room_states=self.room_states() if registry else None,
            # Every client is told which protocol this integration speaks,
            # panel or not. A client that has no use for it ignores it, which
            # is what the classic ESP32 firmware does.
            contract_version=CONTRACT_VERSION,
            profile=self.profile.slug,
            slot_count=None if registry else self.profile.slot_count,
            player_entity=self.controller.player_entity,
            queue_entity=self.controller.queue_entity_id,
            playlists_entity=self.controller.playlists_entity_id,
            slots=None
            if registry
            else tuple(
                SlotPayload(
                    slot=slot.index,
                    entity=proxy_entity_id,
                    label=self._label(slot),
                    controls=slot.controls,
                    min_kelvin=slot.min_kelvin,
                    max_kelvin=slot.max_kelvin,
                )
                for slot in self.slots
                if (proxy_entity_id := self._proxy_entity_ids.get(slot.index))
            ),
            entity_limit=self.profile.entity_limit if registry else None,
            # Only a panel writes a skin, and only one that has a select to
            # write to. The classic ESP32 controller is sent no settings at
            # all and has nothing to do with this.
            skin_select_entity=self._skin_select_entity_id if registry else "",
            entities=tuple(
                EntityPayload(
                    rid=entry.rid,
                    entity=entry.target_entity_id,
                    name=self._entry_name(entry),
                    domain=entry.domain,
                    controls=entry.controls,
                    min_kelvin=entry.min_kelvin,
                    max_kelvin=entry.max_kelvin,
                    min_temp=entry.min_temp,
                    max_temp=entry.max_temp,
                    target_temp_step=entry.target_temp_step,
                )
                for entry in self.entries
            )
            if registry
            else None,
        )
