"""Room-control configuration shared by the flows and the entities.

A **registry element** is one entry of a panel's entity list. It names the
real entity, has no proxy of any kind, and is stored on the panel config
entry. See `registry.py` and docs/CONTRACT.md.

Contract version 8 had a second shape beside it: a numbered **slot** backed by
a proxy entity, for a firmware that resolved entity IDs and service domains
while compiling. Nothing reads one any more — see docs/ROOM_SLOTS.md — and the
only trace left is the migration that deletes the proxies it created.

What survives here is read back into the object the config sensor serves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .contract import CONTRACT_VERSION
from .icon_catalog import normalize_icon_id
from .profiles import (
    CAP_CONTROLS,
    CAP_MAX_KELVIN,
    CAP_MAX_TEMP,
    CAP_MIN_KELVIN,
    CAP_MIN_TEMP,
    CAP_TEMP_STEP,
    ClientProfile,
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
    render_room_states,
)

__all__ = [
    "ClientConfiguration",
    "ControllerEntities",
    "RegistryEntry",
    "resolve_entries",
    "stored_entries",
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


class ControllerEntities:
    """The three entities every client of one controller reads.

    The queue and playlist sensors report their own entity IDs once Home
    Assistant has assigned them, so a client needs no entity ID of its own.
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
    """What one config entry publishes in its config sensor.

    Both kinds of entry have one. A panel's carries its registry, its settings
    and its commands; a source's carries only the three entities every client
    is pointed at, because a source draws nothing and applies nothing.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        owner_id: str,
        profile: ClientProfile,
        controller: ControllerEntities,
        panel: PanelState | None = None,
        entries: Iterable[RegistryEntry] = (),
    ) -> None:
        """Initialize one entry's configuration.

        `panel` is the settings and command channel of a panel device. A
        source has none: it applies nothing at runtime, so sending it settings
        it cannot act on would only mislead a reader of the payload.
        """
        self.hass = hass
        self.owner_id = owner_id
        self.profile = profile
        self.entries: list[RegistryEntry] = list(entries)
        self.controller = controller
        self.panel = panel
        # Reported by the skin select once Home Assistant has assigned it one,
        # the same way a proxy reports its own. A panel that offers a skin
        # picker on the device needs the entity ID to write to, and guessing
        # it from the device name would survive only until somebody renamed
        # something.
        self._skin_select_entity_id = ""
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to registry, controller, and panel changes."""
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
    def async_set_skin_select_entity_id(self, entity_id: str) -> None:
        """Record the entity ID Home Assistant gave this panel's skin select."""
        if self._skin_select_entity_id == entity_id:
            return
        self._skin_select_entity_id = entity_id
        for listener in list(self._listeners):
            listener()

    @callback
    def async_refresh_target_capabilities(self, entity_id: str) -> None:
        """Refresh one target's capabilities in place."""
        changed = False
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
        self.entries = refreshed_entries
        for listener in list(self._listeners):
            listener()

    @callback
    def async_set_entries(self, entries: Iterable[RegistryEntry]) -> bool:
        """Replace the registry in place and rebuild the payload if it moved.

        This is how a change made outside the options flow reaches a panel
        without a config-entry reload. A reload would recreate every entity
        this panel owns and make the device re-read a layout that did not
        change, all for a name somebody typed into the editor — see
        `panel_entity.async_store_settings`, which avoids the same reload for
        the same reason.
        """
        replacement = list(entries)
        if replacement == self.entries:
            return False
        self.entries = replacement
        for listener in list(self._listeners):
            listener()
        return True

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
        return {entry.target_entity_id for entry in self.entries}

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

        Capabilities are resolved at serve time, not only at setup: a form
        stores no controls at all, and a target missing at setup keeps none
        until something re-resolves it — which, for a switch with no
        capability attributes, is never. Serving freshly resolved entries
        makes stored staleness irrelevant, permanently.
        """
        if not self.profile.has_registry:
            return {}
        return render_room_states(
            self.hass,
            resolve_entries(self.hass, self.profile, self.entries),
        )

    def payload(self) -> ClientConfigPayload:
        """Build what this client reads from its config sensor.

        A source has no registry and is sent none: the block is left out
        rather than sent empty, so a reader can tell "no room controls
        configured" from "this entry has no room controls at all".

        The registry is resolved here, at serve time, rather than trusted
        from storage: stored controls go stale — a form stores none, and a
        target missing at setup keeps none — and a card whose element carries
        no `toggle` silently ignores every tap. Resolving live makes that
        class of staleness impossible; renames are followed the same way,
        without waiting for a reload.
        """
        panel = self.panel.as_payload() if self.panel is not None else {}
        registry = self.profile.has_registry
        resolved = (
            resolve_entries(self.hass, self.profile, self.entries)
            if registry
            else []
        )
        return ClientConfigPayload(
            settings=panel.get("settings"),
            commands=panel.get("commands"),
            # Only a client that draws with it is sent it, so that a tablet
            # is not handed twelve values it has nothing to apply.
            theme=panel.get("theme") if self.profile.has_theme else None,
            room_states=self.room_states() if registry else None,
            # Every entry is told which protocol this integration speaks,
            # panel or not. An entry nothing reads ignores it.
            contract_version=CONTRACT_VERSION,
            profile=self.profile.slug,
            player_entity=self.controller.player_entity,
            queue_entity=self.controller.queue_entity_id,
            playlists_entity=self.controller.playlists_entity_id,
            entity_limit=self.profile.entity_limit if registry else None,
            # Only a panel writes a skin, and only one that has a select to
            # write to. A source is sent no settings at all and has nothing
            # to do with this.
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
                    # Normalized here rather than read straight from
                    # storage. The picture a person chose is a fact about the
                    # element and not something resolved from the target the
                    # way controls and bounds are, but an identifier the
                    # catalog has since stopped publishing must reach a
                    # client as "automatic" rather than as a name it will
                    # spend a download on and never find.
                    icon=normalize_icon_id(entry.icon),
                )
                for entry in resolved
            )
            if registry
            else None,
        )
