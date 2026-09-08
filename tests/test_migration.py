"""Tests for the stored halves of the config-entry migrations.

The entity-registry half needs a Home Assistant runtime and is not covered
here; this protects the stored shape, which is what an entry carries on disk
from one release to the next.
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

REGISTRY_SPEC = importlib.util.spec_from_file_location(
    "media_controller_registry_migration", MODULE_PATH.with_name("registry.py")
)
assert REGISTRY_SPEC is not None and REGISTRY_SPEC.loader is not None
registry = importlib.util.module_from_spec(REGISTRY_SPEC)
sys.modules[REGISTRY_SPEC.name] = registry
REGISTRY_SPEC.loader.exec_module(registry)

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
# What the version 4 migration deletes: the version 2 block and the version 1
# keys that preceded it. Mirrors the set const.CONF_SLOTS and const.LEGACY_SLOTS
# build in __init__._async_migrate_v3_slots.
DEAD_KEYS = (SLOTS_KEY, *(key for _, key, _ in LEGACY_SLOTS))

# Mirrors const.LEGACY_TITLE_PREFIX, and duplicated for the same reason.
# The dash is an en dash, which is what version 2 actually wrote.
LEGACY_TITLE_PREFIX = "Media Controller – "


def migrate(section):
    """Run the version 4 migration over one stored mapping."""
    return transformations.migrate_v3_section(section, DEAD_KEYS)


class SlotRemovalTests(unittest.TestCase):
    """Verify version 4 leaves nothing of the room-control slots behind.

    Contract version 9 deletes them along with the classic firmware that was
    the only thing that ever read one. What has to survive the deletion is the
    rest of the entry: a source is bound to a Music Assistant player, and that
    binding is in the same mapping as the slots being removed.
    """

    def test_a_version_2_entry_loses_its_slots_block(self) -> None:
        section = {
            PLAYER_KEY: "media_player.kitchen",
            SLOTS_KEY: [
                {
                    "slot": 1,
                    "entity": "light.desk_lamp",
                    "domain": "light",
                    "label": "DESK LAMP",
                    "controls": ["toggle", "brightness"],
                }
            ],
        }
        self.assertEqual(
            migrate(section), {PLAYER_KEY: "media_player.kitchen"}
        )

    def test_a_version_1_entry_loses_all_four_named_keys(self) -> None:
        """An installation may have skipped straight from version 1."""
        section = {
            PLAYER_KEY: "media_player.kitchen",
            "light_1_entity": "light.desk_lamp",
            "light_2_entity": "light.hall",
            "fan_entity": "switch.fan",
            "ac_entity": "switch.ac",
        }
        self.assertEqual(
            migrate(section), {PLAYER_KEY: "media_player.kitchen"}
        )

    def test_the_player_binding_survives(self) -> None:
        section = {PLAYER_KEY: "media_player.kitchen", SLOTS_KEY: []}
        self.assertEqual(migrate(section)[PLAYER_KEY], "media_player.kitchen")

    def test_unrelated_keys_are_untouched(self) -> None:
        section = {"entry_type": "controller", PLAYER_KEY: "media_player.a"}
        self.assertEqual(migrate(section), section)

    def test_an_entry_that_never_had_slots_is_unchanged(self) -> None:
        section = {PLAYER_KEY: "media_player.kitchen"}
        self.assertEqual(migrate(section), section)

    def test_empty_options_stay_empty(self) -> None:
        self.assertEqual(migrate({}), {})
        self.assertEqual(migrate(None), {})

    def test_running_it_twice_changes_nothing(self) -> None:
        section = {PLAYER_KEY: "media_player.kitchen", SLOTS_KEY: []}
        once = migrate(section)
        self.assertEqual(migrate(once), once)

    def test_the_source_returned_is_a_copy(self) -> None:
        """The migration must not mutate the mapping it was handed."""
        section = {PLAYER_KEY: "media_player.kitchen", SLOTS_KEY: []}
        migrate(section)
        self.assertIn(SLOTS_KEY, section)


class NothingReadsSlotsAnyMoreTests(unittest.TestCase):
    """Verify the slot vocabulary is gone rather than merely unused.

    A panel entry written under contract version 5 may still carry a `slots`
    block, and a source entry that has not been migrated yet certainly does.
    Neither is read: version 6 refused to turn a panel's slots into registry
    elements — see docs/ROOM_SLOTS.md — and version 9 removed the only client
    that read a source's.
    """

    PANEL_ENTRY = {
        "entry_type": "panel",
        "profile": "t560",
        "panel_id": "t560_1a2b3c4d",
        SLOTS_KEY: [
            {
                "slot": 1,
                "entity": "light.desk_lamp",
                "domain": "light",
                "label": "DESK LAMP",
                "controls": ["toggle", "brightness"],
            }
        ],
    }

    def test_no_migration_turns_slots_into_registry_elements(self) -> None:
        self.assertFalse(
            hasattr(transformations, "migrate_slots_to_entities"),
            "A slots-to-registry migration was added; see ROOM_SLOTS.md, "
            "'Slots to registry: deliberately not migrated'.",
        )

    def test_a_version_5_panel_entry_carries_no_registry(self) -> None:
        self.assertEqual(registry.stored_entries(self.PANEL_ENTRY, "entities"), [])
        self.assertEqual(
            registry.stored_retired_rids(self.PANEL_ENTRY, "retired_rids"), []
        )

    def test_the_stored_slot_reader_is_gone(self) -> None:
        for name in ("stored_slots", "SlotConfig", "SlotPayload"):
            self.assertFalse(
                hasattr(transformations, name),
                f"transformations.{name} came back; contract version 9 has "
                "no room-control slots.",
            )


class TitleMigrationTests(unittest.TestCase):
    """Verify the version 2 title prefix is dropped, and only when intact."""

    def strip(self, title):
        """Run the title migration with the production prefix."""
        return transformations.migrate_v2_title(title, LEGACY_TITLE_PREFIX)

    def test_prefix_is_dropped(self) -> None:
        self.assertEqual(
            self.strip("Media Controller – JBL Bar 91 true"),
            "JBL Bar 91 true",
        )

    def test_an_edited_title_is_left_alone(self) -> None:
        self.assertEqual(self.strip("Living room"), "Living room")

    def test_a_hyphen_is_not_the_prefix(self) -> None:
        # Version 2 wrote an en dash. Anything else was typed by a person.
        self.assertEqual(
            self.strip("Media Controller - Kitchen"),
            "Media Controller - Kitchen",
        )

    def test_a_prefix_in_the_middle_is_left_alone(self) -> None:
        self.assertEqual(
            self.strip("Old Media Controller – Kitchen"),
            "Old Media Controller – Kitchen",
        )

    def test_a_title_that_is_only_the_prefix_is_kept(self) -> None:
        # Stripping it would leave an entry with no name at all.
        self.assertEqual(
            self.strip("Media Controller – "),
            "Media Controller – ",
        )

    def test_running_it_twice_changes_nothing(self) -> None:
        once = self.strip("Media Controller – Kitchen")
        self.assertEqual(self.strip(once), once)


if __name__ == "__main__":
    unittest.main()
