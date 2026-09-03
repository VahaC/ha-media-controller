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

# Canonical order, so that two equal control sets always compare equal.
CONTROL_ORDER = (CONTROL_TOGGLE, CONTROL_BRIGHTNESS, CONTROL_COLOR_TEMP)

# Keys of the capability mapping normalize_capabilities returns.
CAP_CONTROLS = "controls"
CAP_MIN_KELVIN = "min_kelvin"
CAP_MAX_KELVIN = "max_kelvin"
CAPABILITY_ATTRIBUTES = (
    "supported_color_modes",
    "brightness",
    "color_temp_kelvin",
    "min_color_temp_kelvin",
    "max_color_temp_kelvin",
)

LIGHT_DOMAIN = "light"
SWITCH_DOMAIN = "switch"

# The domains a client can draw a card for today. Every other domain a user
# may put in the registry — media_player, climate, cover, weather — is carried
# with an empty control list until its card exists, and a client ignores an
# element whose domain it cannot draw. See docs/CONTRACT.md, Registry entries.
CARD_DOMAINS = (LIGHT_DOMAIN, SWITCH_DOMAIN)

# Every Home Assistant colour mode except these carries a brightness channel,
# so brightness is derived from the set difference rather than an allow-list
# that would need editing whenever a new colour mode is added.
MODES_WITHOUT_BRIGHTNESS = frozenset({"onoff", "unknown"})
COLOR_TEMP_MODE = "color_temp"

# Used only when a colour-temperature light does not report its own bounds.
FALLBACK_MIN_KELVIN = 2000
FALLBACK_MAX_KELVIN = 6535


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
    # equivalent of SlotSpec.controls: the paired ESP32 has four buttons and a
    # brightness long-press and no control to set a colour temperature with,
    # so it is told about neither.
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
    controls=(CONTROL_TOGGLE, CONTROL_BRIGHTNESS, CONTROL_COLOR_TEMP),
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
# the firmware has buttons and a brightness long-press, and no control to set
# a colour temperature with.
ESP32_S3_PANEL = ClientProfile(
    slug="esp32_s3_panel",
    name="ESP32-S3 panel",
    skins=(SKIN_CLASSIC, SKIN_MINIMAL_RING, SKIN_COVER_CARD),
    update_kind=UPDATE_KIND_FIRMWARE,
    slots=(),
    entity_limit=64,
    controls=(CONTROL_TOGGLE, CONTROL_BRIGHTNESS),
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


def capability_signature(attributes: Mapping[str, Any] | None) -> tuple[Any, ...]:
    """Return the state portion that can change a light's controls."""
    safe_attributes = attributes or {}
    modes = safe_attributes.get("supported_color_modes") or ()
    if isinstance(modes, str):
        modes = (modes,)
    return tuple(
        tuple(str(mode) for mode in modes)
        if key == "supported_color_modes"
        else key in safe_attributes
        if key in ("brightness", "color_temp_kelvin")
        else safe_attributes.get(key)
        for key in CAPABILITY_ATTRIBUTES
    )


def _kelvin(value: Any, fallback: int) -> int:
    """Read a colour-temperature bound, falling back to a usable default."""
    try:
        kelvin = int(value)
    except (TypeError, ValueError):
        return fallback
    return kelvin if kelvin > 0 else fallback
