"""Room-control slot configuration shared by the flows and the entities.

A slot is stored once, on the config entry for the ESP32 or on a panel
subentry for every other client, and read back here into the object the
proxies and the config sensor use. See docs/ROOM_SLOTS.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import slot_entity_key, slot_label_key
from .contract import CONTRACT_VERSION
from .profiles import (
    CAP_CONTROLS,
    CAP_MAX_KELVIN,
    CAP_MIN_KELVIN,
    CONTROL_TOGGLE,
    ClientProfile,
    capability_signature,
    limit_controls,
    normalize_capabilities,
)
from .panel_state import PanelState
from .transformations import (
    ClientConfigPayload,
    SlotConfig,
    SlotPayload,
    stored_slots,
)

__all__ = [
    "ClientConfiguration",
    "ControllerEntities",
    "SlotConfig",
    "resolve_slots",
    "slots_from_input",
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
    ) -> None:
        """Initialize one client's configuration.

        `panel` is the settings and command channel of a panel device. The
        ESP32 controller has none: it applies nothing at runtime, so sending
        it settings it cannot act on would only mislead a reader of the
        payload.
        """
        self.hass = hass
        self.owner_id = owner_id
        self.profile = profile
        self.slots: list[SlotConfig] = list(slots)
        self.controller = controller
        self.panel = panel
        self._proxy_entity_ids: dict[int, str] = {}
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
        if not changed:
            return
        self.slots = refreshed
        for listener in list(self._listeners):
            listener()

    def _label(self, slot: SlotConfig) -> str:
        """Return the tile label, falling back to the target's name."""
        if slot.label:
            return slot.label
        state = self.hass.states.get(slot.target_entity_id)
        if state is not None and state.name:
            return state.name
        return slot.target_entity_id

    def payload(self) -> ClientConfigPayload:
        """Build what this client reads from its config sensor."""
        panel = self.panel.as_payload() if self.panel is not None else {}
        return ClientConfigPayload(
            settings=panel.get("settings"),
            commands=panel.get("commands"),
            # Every client is told which protocol this integration speaks,
            # panel or not. A client that has no use for it ignores it, which
            # is what the classic ESP32 firmware does.
            contract_version=CONTRACT_VERSION,
            profile=self.profile.slug,
            slot_count=self.profile.slot_count,
            player_entity=self.controller.player_entity,
            queue_entity=self.controller.queue_entity_id,
            playlists_entity=self.controller.playlists_entity_id,
            slots=tuple(
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
        )
