"""Tests for the fan card of both panels.

Until now a fan reached a panel only if somebody exposed it as a `switch`:
it toggled and it had no speed control, because a `switch` has none to give.
`fan` is a registry group of its own now, and it resolves to the two things
a fan card can honestly draw -- a `toggle`, and a `percentage` the long
press sweeps -- with preset modes, direction and oscillation deliberately
left out, because this build has no gesture left for them and the ticket
asked for them to be ignored rather than half-drawn.

What is worth pinning here is what could quietly come apart:

* `toggle` is unconditional for a fan and `percentage` is not. A one-speed
  fan must keep behaving exactly as the switch-exposed fan always did;
* the speed must reach Home Assistant **once**, on release. A mains fan
  could take a call a tick, but many sit on the same Zigbee or Z-Wave mesh a
  radiator valve does, and the setpoint's reasoning carries over unchanged;
* a fan that is off is swept nowhere -- its card shows OFF with no number,
  and a sweep with nothing on screen changing is the one thing a sweep must
  never do;
* the once-a-second config poll must not write Home Assistant's speed back
  over the one a finger is choosing.

The firmware and grid-component halves are asserted by reading the sources,
the way `test_cover_cards.py`, `test_factory_firmware.py` and
`test_firmware_json_style.py` do: the ESP32 component has no C++ test harness
in this repository, and a rule checked nowhere is a rule that comes apart.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest

REPO = Path(__file__).parents[1]
INTEGRATION = REPO / "custom_components" / "media_controller"
PAIRED = REPO / "firmware" / "media-controller-paired.yaml"
GRID_CPP = REPO / "components" / "media_controller_grid" / "media_controller_grid.cpp"
GRID_H = REPO / "components" / "media_controller_grid" / "media_controller_grid.h"
T560_UI = REPO / "clients" / "t560" / "src" / "panel_ui.c"
T560_CONFIG = REPO / "clients" / "t560" / "src" / "panel_config.c"
T560_APP = REPO / "clients" / "t560" / "src" / "application.c"


def _load(name: str, filename: str):
    """Load one integration module without a Home Assistant runtime."""
    spec = importlib.util.spec_from_file_location(name, INTEGRATION / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


profiles = _load("media_controller_profiles_fan", "profiles.py")
transformations = _load("media_controller_transformations_fan", "transformations.py")
registry = _load("media_controller_registry_fan", "registry.py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _case_body(text: str, marker: str) -> str:
    """Return the switch case beginning at `marker`, up to the next one."""
    start = text.index(marker)
    rest = text[start + len(marker):]
    following = [
        rest.index(label) for label in ("case LV_EVENT_",) if label in rest
    ]
    end = min(following) if following else len(rest)
    return rest[:end]


class FanCapabilityTests(unittest.TestCase):
    """What the integration resolves and what it sends the panels."""

    SET_SPEED = 1
    OSCILLATE = 2
    DIRECTION = 4
    PRESET_MODE = 8

    def _controls(self, attributes) -> tuple[str, ...]:
        capabilities = profiles.normalize_capabilities("fan", attributes)
        return profiles.limit_controls(
            capabilities["controls"], profiles.ESP32_S3_PANEL
        )

    def test_a_fan_with_a_speed_reaches_the_panel_whole(self) -> None:
        self.assertEqual(
            self._controls({"supported_features": self.SET_SPEED}),
            ("toggle", "percentage"),
        )

    def test_a_one_speed_fan_keeps_its_toggle_and_nothing_else(self) -> None:
        # The case the whole feature has to not break: a fan exposed as a
        # switch toggled with no slider, and a native one-speed fan must do
        # exactly that rather than gain a control that moves nothing.
        for attributes in (
            {},
            None,
            {"supported_features": 0},
            {"supported_features": None},
            {"supported_features": self.OSCILLATE | self.DIRECTION},
        ):
            with self.subTest(attributes=attributes):
                self.assertEqual(self._controls(attributes), ("toggle",))

    def test_toggle_is_unconditional_unlike_a_cover(self) -> None:
        # A cover gates its toggle on OPEN and CLOSE both being present,
        # because `cover.toggle` reads the state to pick a direction. A fan
        # has no such asymmetry: there is no fan that starts but will not
        # stop, so nothing gates the toggle.
        self.assertEqual(
            profiles.normalize_capabilities("fan", {})["controls"],
            ("toggle",),
        )

    def test_the_speed_step_travels_only_beside_the_control(self) -> None:
        with_speed = profiles.normalize_capabilities(
            "fan", {"supported_features": self.SET_SPEED, "percentage_step": 33}
        )
        self.assertEqual(with_speed["percentage_step"], 33)
        # A step beside a fan that reports no SET_SPEED would be metadata for
        # a slider that is not on the card, exactly as a setpoint bound would.
        toggle_only = profiles.normalize_capabilities(
            "fan", {"supported_features": 0, "percentage_step": 33}
        )
        self.assertEqual(list(toggle_only), ["controls"])

    def test_a_useless_step_is_dropped_not_snapped_to(self) -> None:
        for value in (0, -1, 250, "None", True, float("nan")):
            with self.subTest(value=value):
                self.assertNotIn(
                    "percentage_step",
                    profiles.normalize_capabilities(
                        "fan",
                        {
                            "supported_features": self.SET_SPEED,
                            "percentage_step": value,
                        },
                    ),
                )

    def test_a_future_fan_control_is_ignored_not_mishandled(self) -> None:
        # Oscillation, direction and preset modes set higher bits. A fan that
        # supports them alongside a speed resolves exactly as if they were
        # absent.
        self.assertEqual(
            self._controls(
                {
                    "supported_features": self.SET_SPEED
                    | self.OSCILLATE
                    | self.DIRECTION
                    | self.PRESET_MODE
                }
            ),
            ("toggle", "percentage"),
        )

    def test_the_ceiling_is_still_a_ceiling(self) -> None:
        # A fan's controls arriving does not loosen the profile: colour
        # temperature still needs the long press a lamp spends on brightness.
        self.assertNotIn("color_temp", profiles.ESP32_S3_PANEL.controls)

    def test_the_tablet_draws_the_same_two(self) -> None:
        self.assertEqual(
            profiles.limit_controls(
                ("toggle", "percentage"), profiles.T560
            ),
            ("toggle", "percentage"),
        )

    def test_fan_is_a_registry_group_and_a_drawable_domain(self) -> None:
        self.assertEqual(registry.group_by_slug("fans").domain, "fan")
        self.assertIn("fan", profiles.CARD_DOMAINS)


class FanRoomStateTests(unittest.TestCase):
    """The speed travels as state, in the block a panel can read."""

    def test_the_speed_rides_beside_the_state(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "fan", "on", {"percentage": 60}
            ),
            ["on", 60],
        )

    def test_a_fan_with_no_speed_fabricates_none(self) -> None:
        self.assertEqual(
            transformations.room_state_values("fan", "on", {}), ["on", None]
        )
        self.assertEqual(
            transformations.room_state_values("fan", "off", {"percentage": None}),
            ["off", None],
        )

    def test_a_speed_is_a_whole_percent_in_range(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "fan", "on", {"percentage": 66.6}
            ),
            ["on", 67],
        )
        for reported, expected in ((150, 100), (-5, 0)):
            with self.subTest(reported=reported):
                self.assertEqual(
                    transformations.room_state_values(
                        "fan", "on", {"percentage": reported}
                    ),
                    ["on", expected],
                )

    def test_the_config_sensor_carries_it_for_every_element(self) -> None:
        class _State:
            def __init__(self, state: str, attributes: dict) -> None:
                self.state = state
                self.attributes = attributes

        class _Hass:
            def __init__(self) -> None:
                self.states = self

            def get(self, entity_id: str):
                if entity_id == "fan.ceiling":
                    return _State("on", {"percentage": 40})
                return None

        class _Entry:
            def __init__(self, rid: str, domain: str, entity: str) -> None:
                self.rid = rid
                self.domain = domain
                self.target_entity_id = entity

        states = transformations.render_room_states(
            _Hass(),
            [
                _Entry("1a2b3c4d", "fan", "fan.ceiling"),
                _Entry("5e6f7a8b", "fan", "fan.gone"),
            ],
        )
        self.assertEqual(states["1a2b3c4d"], ["on", 40])
        self.assertEqual(states["5e6f7a8b"], ["unknown"])

    def test_the_step_round_trips_through_storage(self) -> None:
        original = registry.RegistryEntry(
            rid="1a2b3c4d",
            target_entity_id="fan.ceiling",
            domain="fan",
            controls=("toggle", "percentage"),
            percentage_step=33.0,
        )
        restored = registry.stored_entries(
            {"entities": [original.as_stored()]}, "entities"
        )
        self.assertEqual(restored, [original])


class FanFirmwareTests(unittest.TestCase):
    """The rules the paired firmware has to keep, read from its source."""

    def setUp(self) -> None:
        self.text = _read(PAIRED)

    def test_the_speed_action_has_one_script_and_one_service(self) -> None:
        self.assertIn("- id: cmd_entity_set_fan_percentage", self.text)
        self.assertEqual(
            self.text.count('std::string("set_percentage")'), 1
        )
        self.assertEqual(
            self.text.count('std::string("fan"), std::string("set_percentage")'),
            1,
        )

    def test_the_script_will_not_address_another_domain(self) -> None:
        self.assertIn('entity.rfind("fan.", 0) != 0', self.text)

    def test_the_speed_is_sent_once_on_release_and_never_per_tick(self) -> None:
        call = "id(cmd_entity_set_fan_percentage)->execute"
        sweep = _case_body(self.text, "case LV_EVENT_LONG_PRESSED_REPEAT")
        release = _case_body(self.text, "case LV_EVENT_RELEASED")
        self.assertNotIn(call, sweep)
        self.assertIn(call, release)
        self.assertEqual(self.text.count(call), 1)

    def test_the_sweep_moves_the_speed_on_the_device_only_when_on(self) -> None:
        sweep = _case_body(self.text, "case LV_EVENT_LONG_PRESSED_REPEAT")
        self.assertIn("entry->fan_pct = target", sweep)
        # Not while it is off, the thermostat's rule: the fan branch pairs
        # `percentable` with `entry_is_on` the way the setpoint branch pairs
        # `settable_temp` with it.
        fan_branch = sweep[sweep.index("entry->percentable"):]
        self.assertLess(
            fan_branch.index("entry_is_on(*entry)"),
            fan_branch.index("entry->fan_pct = target"),
        )

    def test_the_step_is_the_fans_own_or_four_percent(self) -> None:
        sweep = _case_body(self.text, "case LV_EVENT_LONG_PRESSED_REPEAT")
        self.assertIn("std::isnan(entry->pct_step) ? 4.0f : entry->pct_step", sweep)

    def test_a_fan_with_a_speed_is_a_card_that_acts(self) -> None:
        # `actionable` makes a tile clickable, and an unclickable tile gets
        # no long press. Without this a percentage-only fan would be built
        # unclickable and its sweep would never arrive.
        self.assertIn("entry->percentable);", self.text)

    def test_the_fan_falls_back_to_the_fan_artwork(self) -> None:
        # The default-icon ladder gains a fan branch that points at the
        # artwork already in flash, beside the cover's blind branch.
        ladder = self.text[
            self.text.index("art = id(card_icon_light1)") :
            self.text.index("bool labelled =")
        ]
        self.assertIn(
            "media_controller_grid::DOMAIN_FAN", ladder
        )
        self.assertIn("art = id(card_icon_fan);", ladder)


class FanGridComponentTests(unittest.TestCase):
    """The rules the grid component has to keep, read from its source."""

    def setUp(self) -> None:
        self.cpp = _read(GRID_CPP)
        self.header = _read(GRID_H)

    def test_the_domain_and_control_are_known(self) -> None:
        self.assertIn("DOMAIN_FAN = 7,", self.header)
        self.assertIn("bool percentable;", self.header)
        self.assertIn('strcmp(domain, "fan") == 0', self.cpp)
        self.assertIn('strcmp(value, "percentage") == 0', self.cpp)

    def test_a_capability_change_rebuilds_the_cards(self) -> None:
        self.assertIn("was.percentable != now.percentable", self.cpp)

    def test_the_speed_survives_a_registry_reload(self) -> None:
        self.assertIn("entry.fan_pct = previous->fan_pct;", self.cpp)

    def test_the_poll_leaves_the_held_card_alone(self) -> None:
        self.assertIn(
            "if (!held)\n          fan_pct = room_number(item[1]);", self.cpp
        )

    def test_the_held_list_is_exactly_the_three_swept_values(self) -> None:
        held_guarded = re.findall(r"if \(!held\)\n\s+(\w+) =", self.cpp)
        self.assertEqual(
            sorted(held_guarded), ["fan_pct", "position", "setpoint"]
        )

    def test_a_missing_speed_is_not_printed_and_off_shows_no_number(
        self,
    ) -> None:
        self.assertIn(
            'entry_is_on(entry) && !std::isnan(entry.fan_pct)', self.cpp
        )

    def test_the_editor_is_told_what_a_fan_can_do(self) -> None:
        self.assertIn('item["percentage"] = entry.percentable;', self.cpp)


class FanTabletTests(unittest.TestCase):
    """The T560 half, read from its source the same way -- there is no C
    test harness reachable from here, so the rules are pinned by reading."""

    def setUp(self) -> None:
        self.ui = _read(T560_UI)
        self.config = _read(T560_CONFIG)
        self.app = _read(T560_APP)

    def test_the_tablet_parses_the_percentage_control(self) -> None:
        self.assertIn('g_str_equal(control, "percentage")', self.config)
        self.assertIn("entity->percentage = TRUE", self.config)

    def test_the_tablet_dispatches_fan_set_percentage_once_settled(
        self,
    ) -> None:
        self.assertIn("PANEL_UI_SET_ROOM_PERCENTAGE", self.app)
        self.assertIn('"fan", "set_percentage"', self.app)
        # Guarded on the capability, the way every other room service is.
        self.assertIn("room->percentage", self.app)

    def test_the_tablet_reads_the_speed_off_the_poll(self) -> None:
        self.assertIn(
            'json_object_number(attributes, "percentage", &value)', self.app
        )

    def test_the_speed_is_a_slider_on_the_adjust_sheet(self) -> None:
        self.assertIn("room_percentage_scale", self.ui)
        self.assertIn(
            "gtk_widget_set_visible(ui->room_percentage_box, "
            "entity->percentage)",
            self.ui,
        )
        # Debounced like the cover position: one call when the drag settles.
        self.assertIn("percentage_debounce_source", self.ui)

    def test_a_fan_card_reads_on_with_its_speed(self) -> None:
        self.assertIn('return g_strdup_printf("ON %d%%", card->fan_percentage)',
                      self.ui)


if __name__ == "__main__":
    unittest.main()
