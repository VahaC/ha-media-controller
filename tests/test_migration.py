"""Tests for the version 1 to version 2 room-control migration.

The registry half of the migration needs a Home Assistant runtime and is not
covered here; this protects the stored shape, which is what decides whether a
flashed ESP32 keeps its entities.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "media_controller"
    / "transformations.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_transformations_migration", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
transformations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transformations
SPEC.loader.exec_module(transformations)

# Mirrors const.LEGACY_SLOTS. Duplicated deliberately: if the production tuple
# is ever reordered, this test must fail rather than follow it.
LEGACY_SLOTS = (
    (1, "light_1_entity", "light"),
    (2, "light_2_entity", "light"),
    (3, "fan_entity", "switch"),
    (4, "ac_entity", "switch"),
)
SLOTS_KEY = "slots"
PLAYER_KEY = "player_entity"


def migrate(section):
    """Run the migration with the ESP32 controls seeding."""
    return transformations.migrate_v1_section(
        section,
        SLOTS_KEY,
        PLAYER_KEY,
        LEGACY_SLOTS,
        lambda index: ("toggle", "brightness") if index <= 2 else ("toggle",),
    )


class MigrationTests(unittest.TestCase):
    """Verify the version 1 configuration becomes numbered slots."""

    def test_full_v1_entry(self) -> None:
        migrated = migrate(
            {
                PLAYER_KEY: "media_player.kitchen",
                "light_1_entity": "light.ceiling",
                "light_2_entity": "light.wall",
                "fan_entity": "switch.fan",
                "ac_entity": "switch.ac",
            }
        )
        self.assertEqual(migrated[PLAYER_KEY], "media_player.kitchen")
        self.assertEqual(
            [(slot["slot"], slot["entity"], slot["domain"]) for slot in migrated[SLOTS_KEY]],
            [
                (1, "light.ceiling", "light"),
                (2, "light.wall", "light"),
                (3, "switch.fan", "switch"),
                (4, "switch.ac", "switch"),
            ],
        )

    def test_legacy_keys_are_removed(self) -> None:
        migrated = migrate(
            {PLAYER_KEY: "media_player.kitchen", "fan_entity": "switch.fan"}
        )
        for _, legacy_key, _ in LEGACY_SLOTS:
            self.assertNotIn(legacy_key, migrated)

    def test_slot_numbers_do_not_shift_when_a_slot_was_unset(self) -> None:
        # The ESP32 button that reads slot 4 must keep reading slot 4.
        migrated = migrate(
            {
                PLAYER_KEY: "media_player.kitchen",
                "light_1_entity": "light.ceiling",
                "ac_entity": "switch.ac",
            }
        )
        self.assertEqual(
            [slot["slot"] for slot in migrated[SLOTS_KEY]], [1, 4]
        )

    def test_seeded_controls_respect_the_slot(self) -> None:
        migrated = migrate(
            {
                PLAYER_KEY: "media_player.kitchen",
                "light_1_entity": "light.ceiling",
                "fan_entity": "switch.fan",
            }
        )
        slots = {slot["slot"]: slot for slot in migrated[SLOTS_KEY]}
        self.assertEqual(slots[1]["controls"], ["toggle", "brightness"])
        self.assertEqual(slots[3]["controls"], ["toggle"])

    def test_entry_without_room_controls(self) -> None:
        migrated = migrate({PLAYER_KEY: "media_player.kitchen"})
        self.assertEqual(migrated[SLOTS_KEY], [])

    def test_empty_options_stay_empty(self) -> None:
        self.assertEqual(migrate({}), {})
        self.assertEqual(migrate(None), {})

    def test_options_without_a_player_get_no_slots_key(self) -> None:
        # A v1 options mapping that only remapped a room control.
        migrated = migrate({"fan_entity": "switch.fan"})
        self.assertEqual([slot["slot"] for slot in migrated[SLOTS_KEY]], [3])

    def test_migrated_slots_round_trip(self) -> None:
        migrated = migrate(
            {PLAYER_KEY: "media_player.kitchen", "light_1_entity": "light.ceiling"}
        )
        slots = transformations.stored_slots(migrated, SLOTS_KEY)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].target_entity_id, "light.ceiling")
        self.assertEqual(slots[0].domain, "light")
        self.assertEqual(slots[0].label, "")


if __name__ == "__main__":
    unittest.main()
