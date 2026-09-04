"""Tests for the room-state block of the config sensor.

The ESP32 panel cannot ask Home Assistant for card states itself: POST
`/api/template` answers administrators only, and a panel token belongs to a
dedicated non-administrator user by design. The integration therefore renders
one small array per registry element, keyed by rid, into the config sensor it
already serves. See docs/CONTRACT.md, Room states.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "media_controller"
    / "transformations.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_transformations_room_states", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
transformations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transformations
SPEC.loader.exec_module(transformations)


def _panel(**overrides):
    """Return a panel config payload with a usable registry default."""
    defaults = {
        "profile": "esp32_s3_panel",
        "entity_limit": 64,
        "entities": (
            transformations.EntityPayload(
                rid="a3f1c92d",
                entity="light.desk_lamp",
                name="Desk lamp",
                domain="light",
                controls=("toggle", "brightness"),
            ),
        ),
        "player_entity": "media_player.kitchen",
        "queue_entity": "sensor.controller_queue",
        "playlists_entity": "sensor.controller_playlists",
        "contract_version": 7,
    }
    defaults.update(overrides)
    return transformations.ClientConfigPayload(**defaults)


class RoomStateValueTests(unittest.TestCase):
    """Verify one registry element's rendered room state."""

    def test_a_light_travels_as_its_bare_state(self) -> None:
        self.assertEqual(
            transformations.room_state_values("light", "on", {}), ["on"]
        )
        self.assertEqual(
            transformations.room_state_values("light", "off", {}), ["off"]
        )

    def test_a_switch_and_a_cover_travel_the_same_way(self) -> None:
        self.assertEqual(
            transformations.room_state_values("switch", "on", {}), ["on"]
        )
        self.assertEqual(
            transformations.room_state_values("cover", "open", {}), ["open"]
        )
        self.assertEqual(
            transformations.room_state_values("cover", "closed", {}), ["closed"]
        )

    def test_an_unknown_domain_travels_as_a_bare_state(self) -> None:
        self.assertEqual(
            transformations.room_state_values("vacuum", "cleaning", {}),
            ["cleaning"],
        )

    def test_a_missing_entity_reads_as_unknown(self) -> None:
        self.assertEqual(
            transformations.room_state_values("light", None, None), ["unknown"]
        )
        self.assertEqual(
            transformations.room_state_values("climate", None, None), ["unknown"]
        )

    def test_unavailable_is_a_state_not_an_error(self) -> None:
        self.assertEqual(
            transformations.room_state_values("light", "unavailable", {}),
            ["unavailable"],
        )

    def test_a_thermostat_reports_mode_ambient_and_setpoint(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "climate",
                "heat",
                {"current_temperature": 21.5, "temperature": 22.0},
            ),
            ["heat", 21.5, 22.0],
        )

    def test_a_thermostat_without_readings_sends_nulls(self) -> None:
        self.assertEqual(
            transformations.room_state_values("climate", "off", {}),
            ["off", None, None],
        )

    def test_a_thermostat_ignores_non_numeric_readings(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "climate",
                "heat",
                {"current_temperature": "warm", "temperature": True},
            ),
            ["heat", None, None],
        )

    def test_weather_reports_condition_temperature_and_humidity(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "weather",
                "partlycloudy",
                {"temperature": 15.5, "humidity": 62},
            ),
            ["partlycloudy", 15.5, 62],
        )

    def test_weather_without_readings_still_names_the_sky(self) -> None:
        self.assertEqual(
            transformations.room_state_values("weather", "sunny", {}),
            ["sunny", None, None],
        )

    def test_a_sensor_reports_value_and_unit(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "sensor", "21.5", {"unit_of_measurement": "°C"}
            ),
            ["21.5", "°C"],
        )

    def test_a_sensor_without_a_unit_reports_none(self) -> None:
        self.assertEqual(
            transformations.room_state_values("sensor", "on", {}), ["on", None]
        )

    def test_a_missing_unit_is_not_a_unit_called_none(self) -> None:
        for unit in ("None", "unknown", "unavailable", "", "  "):
            with self.subTest(unit=unit):
                self.assertEqual(
                    transformations.room_state_values(
                        "sensor", "21.5", {"unit_of_measurement": unit}
                    ),
                    ["21.5", None],
                )

    def test_unicode_states_survive_intact(self) -> None:
        self.assertEqual(
            transformations.room_state_values(
                "sensor", "Дощ", {"unit_of_measurement": "мм"}
            ),
            ["Дощ", "мм"],
        )


class RoomStatesBlockTests(unittest.TestCase):
    """Verify the room_states block of the config sensor payload."""

    def test_a_panel_is_sent_room_states(self) -> None:
        attributes = _panel(
            room_states={"a3f1c92d": ["on"]}
        ).as_attributes()
        self.assertEqual(attributes["room_states"], {"a3f1c92d": ["on"]})

    def test_the_classic_esp32_is_sent_no_room_states(self) -> None:
        attributes = transformations.ClientConfigPayload(
            profile="esp32_s3",
            slot_count=4,
            slots=(),
            player_entity="media_player.kitchen",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            contract_version=7,
            room_states={"a3f1c92d": ["on"]},
        ).as_attributes()
        self.assertNotIn("room_states", attributes)

    def test_an_empty_block_is_left_out(self) -> None:
        self.assertNotIn("room_states", _panel(room_states={}).as_attributes())
        self.assertNotIn("room_states", _panel().as_attributes())

    def test_room_states_stay_outside_the_revision(self) -> None:
        before = _panel(room_states={"a3f1c92d": ["off"]}).as_attributes()[
            "revision"
        ]
        after = _panel(room_states={"a3f1c92d": ["on"]}).as_attributes()[
            "revision"
        ]
        self.assertEqual(before, after)


def _stub_hass(states: dict[str, tuple[str, dict]]) -> SimpleNamespace:
    """Return a stub whose state machine answers from a plain mapping."""

    def get(entity_id: str) -> SimpleNamespace | None:
        if entity_id not in states:
            return None
        state, attributes = states[entity_id]
        return SimpleNamespace(state=state, attributes=attributes)

    return SimpleNamespace(states=SimpleNamespace(get=get))


def _stub_entry(rid: str, domain: str, entity: str) -> SimpleNamespace:
    """Return the three fields render_room_states reads off an element."""
    return SimpleNamespace(rid=rid, domain=domain, target_entity_id=entity)


class RenderRoomStatesTests(unittest.TestCase):
    """Verify the rid-keyed room-state mapping from live states."""

    def test_renders_every_element_keyed_by_rid(self) -> None:
        hass = _stub_hass({
            "light.desk_lamp": ("on", {}),
            "climate.hall": ("heat", {
                "current_temperature": 21.5,
                "temperature": 22.0,
            }),
        })
        entries = [
            _stub_entry("a3f1c92d", "light", "light.desk_lamp"),
            _stub_entry("7c41b8e0", "climate", "climate.hall"),
        ]
        self.assertEqual(
            transformations.render_room_states(hass, entries),
            {
                "a3f1c92d": ["on"],
                "7c41b8e0": ["heat", 21.5, 22.0],
            },
        )

    def test_a_missing_entity_reads_as_unknown(self) -> None:
        hass = _stub_hass({})
        entries = [_stub_entry("a3f1c92d", "switch", "switch.gone")]
        self.assertEqual(
            transformations.render_room_states(hass, entries),
            {"a3f1c92d": ["unknown"]},
        )

    def test_unicode_states_survive_intact(self) -> None:
        hass = _stub_hass({
            "sensor.rain": ("Дощ", {"unit_of_measurement": "мм"}),
        })
        entries = [_stub_entry("b71f0c2e", "sensor", "sensor.rain")]
        self.assertEqual(
            transformations.render_room_states(hass, entries),
            {"b71f0c2e": ["Дощ", "мм"]},
        )


if __name__ == "__main__":
    unittest.main()
