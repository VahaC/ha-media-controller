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

LIGHT_DOMAIN = "light"
SWITCH_DOMAIN = "switch"

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


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """What one kind of client device can drive."""

    slug: str
    name: str
    slots: tuple[SlotSpec, ...]

    @property
    def slot_count(self) -> int:
        """Return how many room controls this client drives."""
        return len(self.slots)

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

T560 = ClientProfile(
    slug="t560",
    name="T560 panel",
    slots=tuple(
        SlotSpec(
            index,
            (LIGHT_DOMAIN, SWITCH_DOMAIN),
            (CONTROL_TOGGLE, CONTROL_BRIGHTNESS, CONTROL_COLOR_TEMP),
        )
        for index in range(1, 7)
    ),
)

# The same hardware as ESP32_S3, running the paired firmware instead. It is a
# separate profile rather than a widening of ESP32_S3 because the two differ
# in what a slot may hold, and ESP32_S3 describes devices already in the field
# whose buttons carry a compile-time domain.
#
# Here the domain arrives with the slot at runtime, so any of the four may be
# a light or a switch. Colour temperature is still absent: the firmware has
# four buttons and a brightness long-press, and no control to set it with.
ESP32_S3_PANEL = ClientProfile(
    slug="esp32_s3_panel",
    name="ESP32-S3 panel",
    slots=tuple(
        SlotSpec(
            index,
            (LIGHT_DOMAIN, SWITCH_DOMAIN),
            (CONTROL_TOGGLE, CONTROL_BRIGHTNESS),
        )
        for index in range(1, 5)
    ),
)

# The controller config entry always carries the ESP32 slots; every other
# client is a panel subentry. Only panels are offered in the subentry flow.
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
    spec: SlotSpec | None,
) -> tuple[str, ...]:
    """Intersect what the target supports with what the client can draw."""
    ordered = order_controls(controls)
    if spec is None:
        return ordered
    return tuple(control for control in ordered if control in spec.controls)


def normalize_capabilities(
    domain: str,
    attributes: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert a target entity's attributes to a plain control description.

    Clients render from the result and never parse `supported_color_modes`
    themselves; the ESP32 could not, and the panel must not duplicate the rule.
    """
    if domain != LIGHT_DOMAIN:
        return {CAP_CONTROLS: (CONTROL_TOGGLE,)}

    safe_attributes = attributes or {}
    modes = safe_attributes.get("supported_color_modes") or ()
    if isinstance(modes, str):
        modes = (modes,)
    mode_set = {str(mode) for mode in modes}

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


def _kelvin(value: Any, fallback: int) -> int:
    """Read a colour-temperature bound, falling back to a usable default."""
    try:
        kelvin = int(value)
    except (TypeError, ValueError):
        return fallback
    return kelvin if kelvin > 0 else fallback
