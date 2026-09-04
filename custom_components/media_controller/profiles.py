"""Client profiles and room-control capability rules.

This module deliberately has no Home Assistant imports, so the capability rules
that decide which controls a client draws can be tested without a Home
Assistant runtime. See [docs/ROOM_SLOTS.md](../../../docs/ROOM_SLOTS.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CONTROL_TOGGLE = "toggle"
CONTROL_BRIGHTNESS = "brightness"
CONTROL_COLOR_TEMP = "color_temp"
# A single setpoint a card can move. Added in contract version 7 with the
# climate card; a client that does not know the name ignores it, which is
# what lets one card type ship at a time.
CONTROL_TARGET_TEMPERATURE = "target_temperature"
# How far open something is, as a percentage a card can drag. Added in
# contract version 8 with the cover card, alongside `stop`.
CONTROL_POSITION = "position"
# Halting something that is moving. It is an action rather than a value, and
# it is the one control a blind needs that no other card type has: a blind
# takes seconds to travel and is stopped half way on purpose.
CONTROL_STOP = "stop"

# Canonical order, so that two equal control sets always compare equal.
CONTROL_ORDER = (
    CONTROL_TOGGLE,
    CONTROL_BRIGHTNESS,
    CONTROL_COLOR_TEMP,
    CONTROL_TARGET_TEMPERATURE,
    CONTROL_POSITION,
    CONTROL_STOP,
)

# Keys of the capability mapping normalize_capabilities returns.
CAP_CONTROLS = "controls"
CAP_MIN_KELVIN = "min_kelvin"
CAP_MAX_KELVIN = "max_kelvin"
CAP_MIN_TEMP = "min_temp"
CAP_MAX_TEMP = "max_temp"
CAP_TEMP_STEP = "target_temp_step"

# What a target entity's state has to change for its controls to change with
# it. Nothing here may be a value that moves while the thing is simply being
# used: the brightness of a lamp and the temperature of a room both do, and
# folding one in would rebuild the payload of every panel in the house every
# time somebody dimmed a light or a room warmed up.
CAPABILITY_ATTRIBUTES = (
    "supported_color_modes",
    "brightness",
    "color_temp_kelvin",
    "min_color_temp_kelvin",
    "max_color_temp_kelvin",
    "supported_features",
    "hvac_modes",
    "min_temp",
    "max_temp",
    "target_temp_step",
)
# The two of those that are read for presence rather than for their value: a
# light group reports the effective attribute without a complete
# `supported_color_modes`, so the attribute being there is the capability.
_PRESENCE_ATTRIBUTES = frozenset({"brightness", "color_temp_kelvin"})
_LIST_ATTRIBUTES = frozenset({"supported_color_modes", "hvac_modes"})

LIGHT_DOMAIN = "light"
SWITCH_DOMAIN = "switch"
CLIMATE_DOMAIN = "climate"
COVER_DOMAIN = "cover"

# The domains a client can draw a card for today. Every other domain a user
# may put in the registry — weather — is carried with an empty control list
# until its card exists, and a client ignores an element whose domain it
# cannot draw. So is a domain that is no longer a group at all.
# See docs/CONTRACT.md, Registry entries.
CARD_DOMAINS = (LIGHT_DOMAIN, SWITCH_DOMAIN, CLIMATE_DOMAIN, COVER_DOMAIN)

# Every Home Assistant colour mode except these carries a brightness channel,
# so brightness is derived from the set difference rather than an allow-list
# that would need editing whenever a new colour mode is added.
MODES_WITHOUT_BRIGHTNESS = frozenset({"onoff", "unknown"})
COLOR_TEMP_MODE = "color_temp"

# Used only when a colour-temperature light does not report its own bounds.
FALLBACK_MIN_KELVIN = 2000
FALLBACK_MAX_KELVIN = 6535

# Bits of Home Assistant's `ClimateEntityFeature`, written out rather than
# imported: this module deliberately has no Home Assistant imports so that
# the rules below can be tested without a runtime. They are part of the
# public climate API and have not moved.
CLIMATE_TARGET_TEMPERATURE = 1
CLIMATE_TURN_OFF = 128
CLIMATE_TURN_ON = 256

# The mode a thermostat is in when it is off. A climate entity that lists it
# can be turned off and on again, which is what `toggle` means here.
HVAC_MODE_OFF = "off"

# Bits of Home Assistant's `CoverEntityFeature`, written out for the same
# reason as the climate ones above. They are part of the public cover API and
# have not moved.
COVER_OPEN = 1
COVER_CLOSE = 2
COVER_SET_POSITION = 4
COVER_STOP = 8

# Used only when a thermostat does not report its own bounds, which a real
# one always does. They are the Home Assistant defaults, and like every
# temperature in the payload they are in the unit the entity itself reports —
# the integration converts nothing and the payload names no unit.
FALLBACK_MIN_TEMP = 7.0
FALLBACK_MAX_TEMP = 35.0
FALLBACK_TEMP_STEP = 0.5


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """One room-control slot of a client device.

    A profile is not a bare maximum: the ESP32 constrains each slot
    individually, because its four LVGL buttons carry different compile-time
    actions.
    """

    index: int
    domains: tuple[str, ...]
    controls: tuple[str, ...]


# How a stale build of one client is replaced. "Rebuild it and copy it to the
# tablet" and "flash it with ESPHome" are not the same instruction, so the
# repair issue Home Assistant shows is chosen from this rather than written
# once and made vague enough to cover both.
UPDATE_KIND_TABLET = "tablet"
UPDATE_KIND_FIRMWARE = "firmware"


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """What one kind of client device can drive."""

    slug: str
    name: str
    # Fixed, numbered room slots backed by proxy entities. Only the classic
    # ESP32 firmware has any: it resolves entity IDs and service domains while
    # compiling, so a proxy is the only thing it can be flashed against. Every
    # panel has an empty tuple here and an `entity_limit` instead.
    slots: tuple[SlotSpec, ...]
    # The layouts this client draws, in the client's own vocabulary and in the
    # order it offers them; the first is what it falls back to. The names
    # travel in `player_skin` and mean nothing outside this client, which is
    # why they live on the profile rather than in the settings record: the
    # tablet has two skins of its own and the ESP32 three of its own, and
    # neither would know what to do with the other's names. Empty for a client
    # that draws one interface.
    skins: tuple[str, ...] = ()
    # What kind of update a stale build of this client needs; see the
    # constants above. Every panel is checked the same way — they pair, poll
    # and report alike — so this picks the wording of the repair issue and
    # nothing else. A new panel profile needs the matching
    # `panel_contract_outdated_<update_kind>` and
    # `panel_never_reported_<update_kind>` translations.
    update_kind: str = UPDATE_KIND_FIRMWARE
    # How many registry elements this client accepts in total, across every
    # group. Zero means it has no registry at all and reads `slots` instead.
    #
    # The two panels differ because the limits answer different questions: the
    # tablet's registry is read by an application with a filesystem and never
    # travels into a firmware image, while the ESP32's is held by a device
    # whose config sensor it parses with no JSON library and bounded memory.
    entity_limit: int = 0
    # What this client can draw for a registry element at all, intersected
    # with what the target entity actually supports. It is the registry's
    # equivalent of SlotSpec.controls: the paired ESP32 has a tap and one
    # long-press sweep per card, which it spends on brightness for a lamp and
    # on the setpoint for a thermostat, and has nothing left to set a colour
    # temperature with — so it is told about that one and not the others.
    controls: tuple[str, ...] = CONTROL_ORDER

    @property
    def slot_count(self) -> int:
        """Return how many room controls this client drives."""
        return len(self.slots)

    @property
    def has_registry(self) -> bool:
        """Return whether this client reads `entities` rather than `slots`."""
        return self.entity_limit > 0

    def knows_skin(self, skin: str) -> bool:
        """Return whether this client draws the named layout."""
        return skin in self.skins

    def spec(self, index: int) -> SlotSpec | None:
        """Return the specification of one slot, or None when out of range."""
        for spec in self.slots:
            if spec.index == index:
                return spec
        return None


ESP32_S3 = ClientProfile(
    slug="esp32_s3",
    name="ESP32-S3 controller",
    slots=(
        SlotSpec(1, (LIGHT_DOMAIN,), (CONTROL_TOGGLE, CONTROL_BRIGHTNESS)),
        SlotSpec(2, (LIGHT_DOMAIN,), (CONTROL_TOGGLE, CONTROL_BRIGHTNESS)),
        SlotSpec(3, (SWITCH_DOMAIN,), (CONTROL_TOGGLE,)),
        SlotSpec(4, (SWITCH_DOMAIN,), (CONTROL_TOGGLE,)),
    ),
)

# The tablet's two skins. "cassette" restyles the whole interface, not the
# player page alone.
SKIN_MODERN = "modern"
SKIN_CASSETTE = "cassette"

# The ESP32's three home layouts. The firmware holds the value in a select of
# its own that restores across reboots, the way `config.ini` holds the
# tablet's; these names are what the payload calls them.
SKIN_CLASSIC = "classic"
SKIN_MINIMAL_RING = "minimal_ring"
SKIN_COVER_CARD = "cover_card"

# The tablet reads a registry rather than slots, and its limit is generous:
# the payload is parsed by a GTK application with json-glib and cached to a
# file, and nothing about it is ever compiled into an image.
T560 = ClientProfile(
    slug="t560",
    name="T560 panel",
    skins=(SKIN_MODERN, SKIN_CASSETTE),
    update_kind=UPDATE_KIND_TABLET,
    slots=(),
    entity_limit=100,
    controls=(
        CONTROL_TOGGLE,
        CONTROL_BRIGHTNESS,
        CONTROL_COLOR_TEMP,
        CONTROL_TARGET_TEMPERATURE,
    ),
)

# The same hardware as ESP32_S3, running the paired firmware instead. It is a
# separate profile rather than a widening of ESP32_S3 because the two differ
# in what they read at all: ESP32_S3 describes devices already in the field
# whose buttons carry a compile-time entity ID and service domain, and this
# one resolves both at runtime from what Home Assistant sends it.
#
# That is why it has a registry and the classic firmware cannot. The limit is
# lower than the tablet's because the payload is parsed on the device itself,
# by brace depth and with no JSON library. Colour temperature is still absent:
# the firmware has buttons, and its one gesture beyond a tap is a long press
# that sweeps a value. It spends that gesture on brightness for a light and on
# the setpoint for a thermostat, and has nothing left to set a colour
# temperature with.
ESP32_S3_PANEL = ClientProfile(
    slug="esp32_s3_panel",
    name="ESP32-S3 panel",
    skins=(SKIN_CLASSIC, SKIN_MINIMAL_RING, SKIN_COVER_CARD),
    update_kind=UPDATE_KIND_FIRMWARE,
    slots=(),
    entity_limit=64,
    controls=(
        CONTROL_TOGGLE,
        CONTROL_BRIGHTNESS,
        CONTROL_TARGET_TEMPERATURE,
    ),
)

# The controller config entry always carries the ESP32 slots; every other
# client is a panel entry with a registry. Only panels are offered in the
# panel flow.
CONTROLLER_PROFILE = ESP32_S3
PANEL_PROFILES: tuple[ClientProfile, ...] = (T560, ESP32_S3_PANEL)
PROFILES: dict[str, ClientProfile] = {
    profile.slug: profile for profile in (ESP32_S3, T560, ESP32_S3_PANEL)
}


def panel_profile(slug: str | None) -> ClientProfile:
    """Return a panel profile, falling back to the first one."""
    if slug and (profile := PROFILES.get(slug)) in PANEL_PROFILES:
        assert profile is not None
        return profile
    return PANEL_PROFILES[0]


def order_controls(controls: Iterable[str]) -> tuple[str, ...]:
    """Return controls in canonical order, without duplicates."""
    present = set(controls)
    return tuple(control for control in CONTROL_ORDER if control in present)


def limit_controls(
    controls: Iterable[str],
    ceiling: SlotSpec | ClientProfile | None,
) -> tuple[str, ...]:
    """Intersect what the target supports with what the client can draw.

    The ceiling is a slot specification for the classic ESP32, whose buttons
    each carry their own compile-time action, and the client profile for a
    registry element, where every element of one client is drawn the same way.
    """
    ordered = order_controls(controls)
    if ceiling is None:
        return ordered
    return tuple(control for control in ordered if control in ceiling.controls)


def normalize_capabilities(
    domain: str,
    attributes: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert a target entity's attributes to a plain control description.

    Clients render from the result and never parse `supported_color_modes`
    themselves; the ESP32 could not, and the panel must not duplicate the rule.

    A domain no client can draw a card for yet returns no controls at all,
    rather than a toggle nothing would render. The element still travels in
    the payload carrying its domain, so a client that learns the card later
    finds it already there.
    """
    if domain == SWITCH_DOMAIN:
        return {CAP_CONTROLS: (CONTROL_TOGGLE,)}
    if domain == CLIMATE_DOMAIN:
        return _climate_capabilities(attributes or {})
    if domain == COVER_DOMAIN:
        return _cover_capabilities(attributes or {})
    if domain != LIGHT_DOMAIN:
        return {CAP_CONTROLS: ()}

    safe_attributes = attributes or {}
    modes = safe_attributes.get("supported_color_modes") or ()
    if isinstance(modes, str):
        modes = (modes,)
    mode_set = {str(mode) for mode in modes}

    # Some light groups expose the effective state attributes without a
    # complete supported_color_modes list. Preserve their adjustment controls
    # instead of reducing an otherwise dimmable group to toggle-only.
    if "brightness" in safe_attributes and not (
        mode_set - MODES_WITHOUT_BRIGHTNESS
    ):
        mode_set.add("brightness")
    if (
        "color_temp_kelvin" in safe_attributes
        and COLOR_TEMP_MODE not in mode_set
    ):
        mode_set.add(COLOR_TEMP_MODE)

    controls = [CONTROL_TOGGLE]
    if mode_set - MODES_WITHOUT_BRIGHTNESS:
        controls.append(CONTROL_BRIGHTNESS)

    capabilities: dict[str, Any] = {}
    if COLOR_TEMP_MODE in mode_set:
        controls.append(CONTROL_COLOR_TEMP)
        capabilities[CAP_MIN_KELVIN] = _kelvin(
            safe_attributes.get("min_color_temp_kelvin"), FALLBACK_MIN_KELVIN
        )
        capabilities[CAP_MAX_KELVIN] = _kelvin(
            safe_attributes.get("max_color_temp_kelvin"), FALLBACK_MAX_KELVIN
        )

    capabilities[CAP_CONTROLS] = order_controls(controls)
    return capabilities


def _climate_capabilities(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a thermostat's attributes to the controls a card may draw.

    Two of them, and each is claimed only on evidence:

    * `toggle` needs a thermostat that can be turned off and on again. A
      climate entity says so by listing `off` among its `hvac_modes`, which
      is what Home Assistant's own `climate.turn_off` acts on; the explicit
      `TURN_ON`/`TURN_OFF` feature bits are accepted too, for an entity that
      implements them itself instead.
    * `target_temperature` needs the single-setpoint feature. An entity that
      offers only `TARGET_TEMPERATURE_RANGE` has a high and a low and no one
      number a card could move, so it is left with no setpoint control rather
      than one that would write the wrong field.
    """
    features = _integer(attributes.get("supported_features"))
    modes = attributes.get("hvac_modes") or ()
    if isinstance(modes, str):
        modes = (modes,)
    mode_set = {str(mode) for mode in modes}

    controls: list[str] = []
    if HVAC_MODE_OFF in mode_set or (
        features & CLIMATE_TURN_ON and features & CLIMATE_TURN_OFF
    ):
        controls.append(CONTROL_TOGGLE)

    capabilities: dict[str, Any] = {}
    if features & CLIMATE_TARGET_TEMPERATURE:
        controls.append(CONTROL_TARGET_TEMPERATURE)
        capabilities[CAP_MIN_TEMP] = _temperature(
            attributes.get("min_temp"), FALLBACK_MIN_TEMP
        )
        capabilities[CAP_MAX_TEMP] = _temperature(
            attributes.get("max_temp"), FALLBACK_MAX_TEMP
        )
        step = _temperature(
            attributes.get("target_temp_step"), FALLBACK_TEMP_STEP
        )
        capabilities[CAP_TEMP_STEP] = step if step > 0 else FALLBACK_TEMP_STEP
        if capabilities[CAP_MAX_TEMP] <= capabilities[CAP_MIN_TEMP]:
            # A range a card could not draw a slider over. Fall back to the
            # defaults rather than sending an inverted or empty one.
            capabilities[CAP_MIN_TEMP] = FALLBACK_MIN_TEMP
            capabilities[CAP_MAX_TEMP] = FALLBACK_MAX_TEMP

    capabilities[CAP_CONTROLS] = order_controls(controls)
    return capabilities


def _cover_capabilities(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a cover's attributes to the controls a card may draw.

    Three of them, and each on the feature bit that names it:

    * `toggle` needs **both** open and close. `cover.toggle` decides from the
      current state which of the two to call, so a blind that can only be
      opened would be given a control that works once.
    * `position` needs `SET_POSITION`, the percentage a card drags. A cover
      without it still opens and closes; it simply has no half way.
    * `stop` needs `STOP`. It is what makes a travelling blind stoppable, and
      a cover that reports no stop feature is left without the control rather
      than with a button Home Assistant would refuse.

    A cover reports no bounds: `current_position` is a percentage by
    definition, so unlike a thermostat there is nothing to send alongside.
    """
    features = _integer(attributes.get("supported_features"))

    controls: list[str] = []
    if features & COVER_OPEN and features & COVER_CLOSE:
        controls.append(CONTROL_TOGGLE)
    if features & COVER_SET_POSITION:
        controls.append(CONTROL_POSITION)
    if features & COVER_STOP:
        controls.append(CONTROL_STOP)

    return {CAP_CONTROLS: order_controls(controls)}


def capability_signature(attributes: Mapping[str, Any] | None) -> tuple[Any, ...]:
    """Return the state portion that can change a target's controls."""
    safe_attributes = attributes or {}
    return tuple(
        _signature_field(safe_attributes, key) for key in CAPABILITY_ATTRIBUTES
    )


def _signature_field(attributes: Mapping[str, Any], key: str) -> Any:
    """Return one attribute in the shape the signature compares it in."""
    if key in _LIST_ATTRIBUTES:
        value = attributes.get(key) or ()
        if isinstance(value, str):
            value = (value,)
        return tuple(str(item) for item in value)
    if key in _PRESENCE_ATTRIBUTES:
        return key in attributes
    return attributes.get(key)


def _kelvin(value: Any, fallback: int) -> int:
    """Read a colour-temperature bound, falling back to a usable default."""
    try:
        kelvin = int(value)
    except (TypeError, ValueError):
        return fallback
    return kelvin if kelvin > 0 else fallback


def _integer(value: Any) -> int:
    """Read a feature bitmask, treating anything unusable as no features."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _temperature(value: Any, fallback: float) -> float:
    """Read a temperature bound, falling back to a usable default.

    Rounded to one decimal because that is the resolution a thermostat is
    ever set to, and because a bound that arrives as 21.999999999 would
    otherwise travel into every payload and every checksum with it.
    """
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return fallback
    return round(temperature, 1)
