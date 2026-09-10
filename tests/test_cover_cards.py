"""Tests for the cover card of the paired ESP32 panel.

The T560 has drawn covers since contract version 7. The paired ESP32 drew
only half of one: it toggled, said OPEN or CLOSED, and had `position` and
`stop` stripped from its payload by its own panel profile because the
firmware had no gesture to spend on them. It has two, and a blind is the one
card type that spends neither on anything else -- there is no brightness to
sweep and no setpoint, and a tap on a blind that is already travelling means
something a toggle cannot express.

What is worth testing here is what could quietly come apart:

* the integration must send the two controls to this panel now, and must
  still refuse the one there is genuinely no gesture for;
* the position must reach Home Assistant **once**, on release. A blind is a
  motor on a mechanism, and a call per sweep tick would be an instruction to
  set off towards a place the finger has already left;
* a tap on a moving blind must stop it rather than toggle it, and only where
  Home Assistant said `stop` is available;
* the once-a-second config poll must not write Home Assistant's position back
  over the one a finger is choosing, which on a *travelling* blind would be a
  different number every second.

The firmware half is asserted by reading the sources, the way
`test_factory_firmware.py` and `test_firmware_json_style.py` do: the ESP32
component has no C++ test harness in this repository, and a rule that is not
checked anywhere is a rule that comes apart.
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


def _load(name: str, filename: str):
    """Load one integration module without a Home Assistant runtime."""
    spec = importlib.util.spec_from_file_location(name, INTEGRATION / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


profiles = _load("media_controller_profiles_cover", "profiles.py")
transformations = _load(
    "media_controller_transformations_cover", "transformations.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _case_body(text: str, marker: str) -> str:
    """Return the switch case beginning at `marker`, up to the next one.

    The room card's gesture handler is one switch over the LVGL event codes,
    and several of the rules below are about which of its cases something
    happens in. Slicing on the case labels is what lets a test say "not from
    the sweep, from the release" rather than merely "somewhere in the file".
    """
    start = text.index(marker)
    rest = text[start + len(marker):]
    following = [
        rest.index(label)
        for label in ("case LV_EVENT_",)
        if label in rest
    ]
    end = min(following) if following else len(rest)
    return rest[:end]


class CoverCapabilityTests(unittest.TestCase):
    """What the integration resolves and what it sends this panel."""

    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8

    def _controls(self, features: int) -> tuple[str, ...]:
        capabilities = profiles.normalize_capabilities(
            "cover", {"supported_features": features}
        )
        return profiles.limit_controls(
            capabilities["controls"], profiles.ESP32_S3_PANEL
        )

    def test_a_full_blind_reaches_the_panel_whole(self) -> None:
        self.assertEqual(
            self._controls(
                self.OPEN | self.CLOSE | self.SET_POSITION | self.STOP
            ),
            ("toggle", "position", "stop"),
        )

    def test_a_blind_that_only_opens_and_closes_keeps_its_toggle(self) -> None:
        # The commonest blind there is, and the one that must go on behaving
        # exactly as it did before the panel learned the other two.
        self.assertEqual(
            self._controls(self.OPEN | self.CLOSE), ("toggle",)
        )

    def test_stop_and_position_are_claimed_only_on_evidence(self) -> None:
        self.assertEqual(
            self._controls(self.OPEN | self.CLOSE | self.STOP),
            ("toggle", "stop"),
        )
        self.assertEqual(
            self._controls(self.OPEN | self.CLOSE | self.SET_POSITION),
            ("toggle", "position"),
        )

    def test_a_cover_that_reports_nothing_is_a_card_with_no_action(
        self,
    ) -> None:
        self.assertEqual(self._controls(0), ())

    def test_a_cover_sends_no_bounds_because_a_percentage_has_none(
        self,
    ) -> None:
        capabilities = profiles.normalize_capabilities(
            "cover", {"supported_features": self.SET_POSITION}
        )
        self.assertEqual(list(capabilities), ["controls"])

    def test_the_ceiling_is_still_a_ceiling(self) -> None:
        # Two controls arriving is not the profile giving up: colour
        # temperature needs the long press a lamp already spends on
        # brightness, and there is still no third gesture to give it.
        self.assertNotIn("color_temp", profiles.ESP32_S3_PANEL.controls)


class CoverRoomStateTests(unittest.TestCase):
    """The position travels as state, in the block a panel can read."""

    def test_the_position_rides_beside_the_state(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "cover", "closing", {"current_position": 65}
            ),
            ["closing", 65],
        )

    def test_a_blind_with_no_position_fabricates_none(self) -> None:
        self.assertEqual(
            transformations.room_state_values("cover", "open", {}),
            ["open", None],
        )

    def test_the_config_sensor_carries_it_for_every_element(self) -> None:
        # render_room_states reads hass only through states.get, so a stub
        # serves. What matters is that the cover branch is reached through
        # the real entry point and not only through room_state_values.
        class _State:
            def __init__(self, state: str, attributes: dict) -> None:
                self.state = state
                self.attributes = attributes

        class _Hass:
            def __init__(self) -> None:
                self.states = self

            def get(self, entity_id: str):
                if entity_id == "cover.blind":
                    return _State("open", {"current_position": 30})
                return None

        class _Entry:
            def __init__(self, rid: str, domain: str, entity: str) -> None:
                self.rid = rid
                self.domain = domain
                self.target_entity_id = entity

        states = transformations.render_room_states(
            _Hass(),
            [
                _Entry("3f9a01cd", "cover", "cover.blind"),
                _Entry("b71f0c2e", "cover", "cover.gone"),
            ],
        )
        self.assertEqual(states["3f9a01cd"], ["open", 30])
        # A cover whose entity is gone reads as unknown and claims no
        # position, rather than keeping a stale one.
        self.assertEqual(states["b71f0c2e"], ["unknown"])


class CoverFirmwareTests(unittest.TestCase):
    """The rules the paired firmware has to keep, read from its source."""

    def setUp(self) -> None:
        self.text = _read(PAIRED)

    def test_each_cover_action_has_one_script_and_one_service(self) -> None:
        self.assertIn("- id: cmd_entity_set_position", self.text)
        self.assertIn("- id: cmd_entity_stop_cover", self.text)
        for service in ("set_cover_position", "stop_cover"):
            with self.subTest(service=service):
                self.assertEqual(
                    self.text.count(f'std::string("{service}")'), 1
                )

    def test_neither_script_will_address_another_domain(self) -> None:
        # The entity comes out of the payload, and a service named for a
        # domain has to match the entity it is called on.
        self.assertEqual(self.text.count('entity.rfind("cover.", 0) != 0'), 2)

    def test_the_position_is_sent_once_on_release_and_never_per_tick(
        self,
    ) -> None:
        call = "id(cmd_entity_set_position)->execute"
        sweep = _case_body(self.text, "case LV_EVENT_LONG_PRESSED_REPEAT")
        release = _case_body(self.text, "case LV_EVENT_RELEASED")
        # The call and not the name: the sweep names the script in a comment,
        # to say which one it is deliberately not reaching for.
        self.assertNotIn(call, sweep)
        self.assertIn(call, release)
        # And exactly one call site, so a second path cannot appear without
        # this test noticing.
        self.assertEqual(self.text.count(call), 1)

    def test_the_sweep_moves_the_position_on_the_device(self) -> None:
        sweep = _case_body(self.text, "case LV_EVENT_LONG_PRESSED_REPEAT")
        self.assertIn("entry->positionable", sweep)
        self.assertIn("entry->position = target", sweep)

    def test_a_tap_on_a_moving_blind_stops_it_instead_of_toggling(
        self,
    ) -> None:
        clicked = _case_body(self.text, "case LV_EVENT_CLICKED")
        # Both guards, and in this order: the stop is offered only where
        # Home Assistant said the entity has one, and only while the blind
        # is actually travelling. Everything else is still a toggle.
        self.assertIn("entry->stoppable", clicked)
        self.assertIn("entry_is_moving(*entry)", clicked)
        self.assertLess(
            clicked.index("cmd_entity_stop_cover"),
            clicked.index("cmd_entity_toggle"),
        )

    def test_a_cover_with_only_a_position_is_still_a_card_that_acts(
        self,
    ) -> None:
        # `actionable` is what makes a tile clickable at all, and a tile that
        # is not clickable gets no long press either. A blind that reports
        # SET_POSITION but neither OPEN nor CLOSE would otherwise be built
        # unclickable and its sweep would never arrive.
        self.assertIn("entry->positionable ||", self.text)
        self.assertIn("entry->stoppable", self.text)

    def test_the_held_card_is_named_on_press_and_released_afterwards(
        self,
    ) -> None:
        pressed = _case_body(self.text, "case LV_EVENT_PRESSED")
        self.assertIn("hold_card(placed[index].rid)", pressed)
        for marker in ("case LV_EVENT_RELEASED", "case LV_EVENT_PRESS_LOST"):
            with self.subTest(marker=marker):
                self.assertIn(
                    "release_card()", _case_body(self.text, marker)
                )

    def test_losing_the_press_releases_the_hold_and_decides_nothing_else(
        self,
    ) -> None:
        # This is the last event the card hears: lv_indev.c moves `act_obj`
        # on before the release, so RELEASED goes to whatever the finger
        # landed on instead. Hence the hold must be given up here, or the
        # poll would skip this card's value for the life of the session. The
        # abandoned sweep is dropped rather than sent, which is what has
        # always happened to a setpoint abandoned the same way.
        lost = _case_body(self.text, "case LV_EVENT_PRESS_LOST")
        self.assertIn("release_card()", lost)
        self.assertNotIn("id(room_card_swept) =", lost)
        self.assertNotIn("->execute", lost)


class CoverGridComponentTests(unittest.TestCase):
    """The rules the grid component has to keep, read from its source."""

    def setUp(self) -> None:
        self.cpp = _read(GRID_CPP)
        self.header = _read(GRID_H)

    def test_both_controls_are_parsed_out_of_the_payload(self) -> None:
        self.assertIn('strcmp(value, "position") == 0', self.cpp)
        self.assertIn('strcmp(value, "stop") == 0', self.cpp)
        self.assertIn("bool positionable;", self.header)
        self.assertIn("bool stoppable;", self.header)

    def test_a_capability_change_rebuilds_the_cards(self) -> None:
        # A blind that gains or loses one of them has to reach the tiles:
        # `actionable` and the tap both read these, and a payload compared
        # without them would leave a card that no longer acts still clickable.
        self.assertIn("was.positionable != now.positionable", self.cpp)
        self.assertIn("was.stoppable != now.stoppable", self.cpp)

    def test_the_position_survives_a_registry_reload(self) -> None:
        # A rename in Home Assistant rebuilds every entry. Without this the
        # cards would blank their percentage until the next state poll.
        self.assertIn("entry.position = previous->position;", self.cpp)

    def test_the_poll_leaves_the_held_card_alone(self) -> None:
        self.assertIn(
            "const bool held = this->holding_ && entry.rid == this->held_rid_;",
            self.cpp,
        )
        self.assertIn("if (!held)\n          position = room_number(item[1]);", self.cpp)

    def test_the_poll_may_still_move_the_held_card_state(self) -> None:
        # Only the swept number is pinned. A blind that reaches its end stop
        # under a finger must still be allowed to say CLOSED, or the tap that
        # follows would be deciding from a state a second out of date. The
        # fan's speed joined the same list; see test_fan_cards.py.
        self.assertIn("entry.state = state;", self.cpp)
        held_guarded = re.findall(r"if \(!held\)\n\s+(\w+) =", self.cpp)
        self.assertEqual(
            sorted(held_guarded), ["fan_pct", "position", "setpoint"]
        )

    def test_the_card_says_which_way_a_moving_blind_is_going(self) -> None:
        self.assertIn('text = "OPENING";', self.cpp)
        self.assertIn('text = "CLOSING";', self.cpp)
        self.assertIn('entry_is_on(entry) ? "OPEN" : "CLOSED"', self.cpp)

    def test_a_missing_position_is_not_printed_as_a_percentage(self) -> None:
        # The whole reason the reading is NAN rather than zero: a blind that
        # cannot say and a blind that is shut are not the same card.
        self.assertIn("if (!std::isnan(entry.position)) {", self.cpp)

    def test_moving_is_a_cover_question_and_needs_a_known_state(self) -> None:
        self.assertIn(
            "return entry.domain == DOMAIN_COVER && entry_is_known(entry) &&",
            self.cpp,
        )

    def test_the_editor_is_told_what_a_cover_can_do(self) -> None:
        self.assertIn('item["position"] = entry.positionable;', self.cpp)
        self.assertIn('item["stop"] = entry.stoppable;', self.cpp)


if __name__ == "__main__":
    unittest.main()
