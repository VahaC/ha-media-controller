"""Tests for a panel's unbounded entity registry.

Everything the registry decides lives in a module with no Home Assistant
imports, for the same reason the payloads and the profiles do: these are the
rules a released client depends on, and they must be testable without a Home
Assistant runtime.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

COMPONENT = (
    Path(__file__).parents[1] / "custom_components" / "media_controller"
)


def _load(name: str, filename: str):
    """Import one module of the integration on its own."""
    spec = importlib.util.spec_from_file_location(name, COMPONENT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


registry = _load("media_controller_registry", "registry.py")
profiles = _load("media_controller_registry_profiles", "profiles.py")

RegistryEntry = registry.RegistryEntry


def counter_rids(prefix: str = "rid"):
    """Return a rid source that is predictable instead of random."""
    state = {"next": 0}

    def source(taken):
        while True:
            state["next"] += 1
            candidate = f"{prefix}{state['next']:05d}"
            if candidate not in taken:
                return candidate

    return source


def entry(rid: str, entity_id: str, name: str = "") -> RegistryEntry:
    """Build one element without repeating the domain every time."""
    return RegistryEntry(
        rid=rid,
        target_entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
    )


class RidTests(unittest.TestCase):
    """A rid is eight hex characters, unique, and never handed out twice."""

    def test_a_rid_is_eight_lowercase_hex_characters(self) -> None:
        for _ in range(50):
            rid = registry.new_rid(())
            with self.subTest(rid=rid):
                self.assertEqual(len(rid), registry.RID_LENGTH)
                self.assertEqual(rid, rid.lower())
                int(rid, 16)

    def test_a_taken_rid_is_never_returned(self) -> None:
        draws = iter([0x0000002A, 0x0000002A, 0x000000FF])
        rid = registry.new_rid(
            {"0000002a"}, _random=lambda _bits: next(draws)
        )
        self.assertEqual(rid, "000000ff")

    def test_the_whole_space_is_drawn_from(self) -> None:
        """A rid must not look like a counter a client could order by."""
        seen = {registry.new_rid(()) for _ in range(200)}
        self.assertGreater(len(seen), 190)


class GroupTests(unittest.TestCase):
    """The groups, and the order they are rendered in."""

    def test_every_group_maps_to_one_domain(self) -> None:
        self.assertEqual(
            [group.domain for group in registry.GROUPS],
            ["light", "switch", "climate", "cover", "weather"],
        )

    def test_a_retired_group_is_no_longer_offered(self) -> None:
        """A panel plays from its source, so it never listed one twice."""
        self.assertNotIn("media_player", registry.GROUP_DOMAINS)
        self.assertIsNone(registry.group_by_slug("media_players"))
        self.assertIn("media_player", registry.RETIRED_GROUP_DOMAINS)

    def test_a_group_is_found_by_its_form_slug(self) -> None:
        self.assertEqual(registry.group_by_slug("switches").domain, "switch")
        self.assertIsNone(registry.group_by_slug("nothing"))

    def test_elements_are_ordered_by_group_then_by_addition(self) -> None:
        ordered = registry.sort_entries(
            [
                entry("c", "switch.fan"),
                entry("a", "light.desk"),
                entry("d", "cover.blind"),
                entry("b", "light.hall"),
            ]
        )
        self.assertEqual(
            [element.rid for element in ordered], ["a", "b", "c", "d"]
        )

    def test_an_unknown_domain_sorts_last_and_is_kept(self) -> None:
        """A registry written by a newer build stays readable by this one."""
        ordered = registry.sort_entries(
            [entry("z", "fan.ceiling"), entry("a", "light.desk")]
        )
        self.assertEqual([element.rid for element in ordered], ["a", "z"])


class GroupEditingTests(unittest.TestCase):
    """Adding and removing entities in one group."""

    def setUp(self) -> None:
        self.registry = [
            entry("aaaaaaaa", "light.desk", "Desk"),
            entry("bbbbbbbb", "switch.fan", "Fan"),
        ]

    def test_an_added_entity_gets_a_new_element(self) -> None:
        result, retired = registry.replace_group(
            self.registry,
            "light",
            ["light.desk", "light.hall"],
            rid_source=counter_rids(),
        )
        self.assertEqual(retired, [])
        self.assertEqual(
            [element.target_entity_id for element in result],
            ["light.desk", "light.hall", "switch.fan"],
        )

    def test_a_kept_entity_keeps_its_rid_and_its_label(self) -> None:
        result, _ = registry.replace_group(
            self.registry,
            "light",
            ["light.hall", "light.desk"],
            rid_source=counter_rids(),
        )
        desk = next(
            element
            for element in result
            if element.target_entity_id == "light.desk"
        )
        self.assertEqual(desk.rid, "aaaaaaaa")
        self.assertEqual(desk.name, "Desk")

    def test_a_removed_entity_is_deleted_and_its_rid_retired(self) -> None:
        result, retired = registry.replace_group(
            self.registry, "light", [], rid_source=counter_rids()
        )
        self.assertEqual(retired, ["aaaaaaaa"])
        self.assertEqual(
            [element.rid for element in result], ["bbbbbbbb"]
        )

    def test_a_retired_rid_is_never_handed_out_again(self) -> None:
        """A device keys its own grid layout on a rid; reuse would move a tile."""
        result, retired = registry.replace_group(
            self.registry, "light", [], rid_source=counter_rids()
        )
        again, _ = registry.replace_group(
            result,
            "light",
            ["light.desk"],
            retired=retired,
            rid_source=lambda taken: registry.new_rid(taken),
        )
        desk = next(
            element
            for element in again
            if element.target_entity_id == "light.desk"
        )
        self.assertNotIn(desk.rid, retired)

    def test_editing_one_group_leaves_the_others_alone(self) -> None:
        result, _ = registry.replace_group(
            self.registry, "light", [], rid_source=counter_rids()
        )
        self.assertEqual(
            [element.target_entity_id for element in result], ["switch.fan"]
        )

    def test_a_repeated_entity_is_only_added_once(self) -> None:
        result, _ = registry.replace_group(
            [],
            "light",
            ["light.desk", "light.desk"],
            rid_source=counter_rids(),
        )
        self.assertEqual(len(result), 1)

    def test_the_current_selection_is_what_the_form_shows(self) -> None:
        self.assertEqual(
            registry.group_selection(self.registry, "light"), ["light.desk"]
        )
        self.assertEqual(registry.group_selection(self.registry, "cover"), [])


class EmptyRegistryTests(unittest.TestCase):
    """A panel with no room entities is a valid panel."""

    def test_nothing_stored_reads_as_nothing(self) -> None:
        self.assertEqual(registry.stored_entries({}, "entities"), [])
        self.assertEqual(
            registry.stored_entries({"entities": None}, "entities"), []
        )

    def test_a_group_can_be_left_empty(self) -> None:
        result, retired = registry.replace_group(
            [], "light", [], rid_source=counter_rids()
        )
        self.assertEqual(result, [])
        self.assertEqual(retired, [])

    def test_no_retired_rids_stored(self) -> None:
        self.assertEqual(registry.stored_retired_rids({}, "retired_rids"), [])


class LimitTests(unittest.TestCase):
    """The per-profile limits, and the boundary itself."""

    def test_the_two_panels_have_different_limits(self) -> None:
        # The tablet parses the payload with json-glib and caches it to a
        # file; the ESP32 parses it on the device by brace depth.
        self.assertEqual(profiles.T560.entity_limit, 100)
        self.assertEqual(profiles.ESP32_S3_PANEL.entity_limit, 64)

    def test_the_classic_controller_has_no_registry(self) -> None:
        self.assertEqual(profiles.ESP32_S3.entity_limit, 0)
        self.assertFalse(profiles.ESP32_S3.has_registry)
        for profile in profiles.PANEL_PROFILES:
            with self.subTest(profile=profile.slug):
                self.assertTrue(profile.has_registry)

    def test_panels_no_longer_carry_slots(self) -> None:
        for profile in profiles.PANEL_PROFILES:
            with self.subTest(profile=profile.slug):
                self.assertEqual(profile.slots, ())
                self.assertEqual(profile.slot_count, 0)
        self.assertEqual(profiles.ESP32_S3.slot_count, 4)

    def _fill(self, count: int):
        """Build a registry of `count` light elements."""
        entries, _ = registry.replace_group(
            [],
            "light",
            [f"light.lamp_{index}" for index in range(count)],
            rid_source=counter_rids(),
        )
        return entries

    def test_a_registry_exactly_at_the_limit_is_accepted(self) -> None:
        limit = profiles.ESP32_S3_PANEL.entity_limit
        entries = self._fill(limit)
        self.assertEqual(len(entries), limit)
        self.assertLessEqual(len(entries), limit)

    def test_one_past_the_limit_is_visible_as_such(self) -> None:
        # replace_group does not clamp: the caller refuses the form, so the
        # user is told rather than having an entity silently dropped.
        limit = profiles.ESP32_S3_PANEL.entity_limit
        entries = self._fill(limit + 1)
        self.assertGreater(len(entries), limit)

    def test_every_rid_stays_unique_across_a_full_registry(self) -> None:
        entries = self._fill(profiles.T560.entity_limit)
        self.assertEqual(
            len({element.rid for element in entries}), len(entries)
        )


class LabelTests(unittest.TestCase):
    """Labels are applied by rid, and survive any script.

    No form asks for one any more, but a stored label is still read and still
    preferred over the entity's own name, so the rule stays covered.
    """

    def test_a_label_is_applied_by_rid(self) -> None:
        entries = registry.apply_names(
            [entry("aaaaaaaa", "light.desk")], {"aaaaaaaa": "Desk lamp"}
        )
        self.assertEqual(entries[0].name, "Desk lamp")

    def test_a_cyrillic_label_survives_a_round_trip(self) -> None:
        entries = registry.apply_names(
            [entry("aaaaaaaa", "light.desk")],
            {"aaaaaaaa": "Настільна лампа"},
        )
        restored = registry.stored_entries(
            {"entities": [element.as_stored() for element in entries]},
            "entities",
        )
        self.assertEqual(restored[0].name, "Настільна лампа")

    def test_a_label_is_trimmed_and_may_be_cleared(self) -> None:
        entries = registry.apply_names(
            [entry("aaaaaaaa", "light.desk", "Desk")],
            {"aaaaaaaa": "  "},
        )
        self.assertEqual(entries[0].name, "")

    def test_an_element_the_form_did_not_mention_is_left_alone(self) -> None:
        entries = registry.apply_names(
            [
                entry("aaaaaaaa", "light.desk", "Desk"),
                entry("bbbbbbbb", "switch.fan", "Fan"),
            ],
            {"aaaaaaaa": "Study lamp"},
        )
        self.assertEqual(entries[1].name, "Fan")


class RenameTests(unittest.TestCase):
    """A rid outlives the entity ID it points at."""

    def test_an_element_follows_its_entity_through_a_rename(self) -> None:
        entries = [
            RegistryEntry(
                rid="aaaaaaaa",
                target_entity_id="light.desk_lamp",
                domain="light",
                name="Desk",
                registry_id="row-1",
            )
        ]
        followed = registry.resolve_entity_ids(
            entries, lambda _entry: ("light.study_lamp", "row-1")
        )
        self.assertEqual(followed[0].rid, "aaaaaaaa")
        self.assertEqual(followed[0].name, "Desk")
        self.assertEqual(followed[0].target_entity_id, "light.study_lamp")

    def test_an_element_whose_row_is_gone_keeps_what_it_had(self) -> None:
        entries = [entry("aaaaaaaa", "light.desk", "Desk")]
        followed = registry.resolve_entity_ids(
            entries, lambda _entry: ("", "")
        )
        self.assertEqual(followed[0].target_entity_id, "light.desk")
        self.assertEqual(followed[0].rid, "aaaaaaaa")

    def test_a_rename_is_recorded_with_its_row_id(self) -> None:
        entries = [entry("aaaaaaaa", "light.desk")]
        followed = registry.resolve_entity_ids(
            entries, lambda _entry: ("light.desk", "row-9")
        )
        self.assertEqual(followed[0].registry_id, "row-9")


class StorageTests(unittest.TestCase):
    """What survives being written to a config entry and read back."""

    def test_a_full_element_round_trips(self) -> None:
        original = RegistryEntry(
            rid="a3f1c92d",
            target_entity_id="light.desk_lamp",
            domain="light",
            name="Настільна лампа",
            registry_id="row-1",
            controls=("toggle", "brightness", "color_temp"),
            min_kelvin=2200,
            max_kelvin=6500,
        )
        restored = registry.stored_entries(
            {"entities": [original.as_stored()]}, "entities"
        )
        self.assertEqual(restored, [original])

    def test_a_thermostat_round_trips(self) -> None:
        original = RegistryEntry(
            rid="7c41b8e0",
            target_entity_id="climate.hall",
            domain="climate",
            name="Передпокій",
            registry_id="row-2",
            controls=("toggle", "target_temperature"),
            min_temp=16.5,
            max_temp=30.0,
            target_temp_step=0.5,
        )
        restored = registry.stored_entries(
            {"entities": [original.as_stored()]}, "entities"
        )
        self.assertEqual(restored, [original])

    def test_kelvin_bounds_are_omitted_where_they_do_not_apply(self) -> None:
        stored = entry("aaaaaaaa", "switch.fan").as_stored()
        self.assertNotIn("min_kelvin", stored)
        self.assertNotIn("max_kelvin", stored)

    def test_setpoint_bounds_are_omitted_where_they_do_not_apply(self) -> None:
        """The same rule, so a lamp never carries a thermostat's numbers."""
        stored = entry("aaaaaaaa", "switch.fan").as_stored()
        self.assertNotIn("min_temp", stored)
        self.assertNotIn("max_temp", stored)
        self.assertNotIn("target_temp_step", stored)

    def test_an_incomplete_record_is_ignored(self) -> None:
        restored = registry.stored_entries(
            {
                "entities": [
                    {"rid": "aaaaaaaa"},
                    {"entity": "light.desk"},
                    "not a mapping",
                    {"rid": "bbbbbbbb", "entity": "light.hall"},
                ]
            },
            "entities",
        )
        self.assertEqual([element.rid for element in restored], ["bbbbbbbb"])

    def test_a_missing_domain_is_derived_from_the_entity_id(self) -> None:
        restored = registry.stored_entries(
            {"entities": [{"rid": "aaaaaaaa", "entity": "cover.blind"}]},
            "entities",
        )
        self.assertEqual(restored[0].domain, "cover")

    def test_a_repeated_rid_is_dropped(self) -> None:
        """Two tiles a client cannot tell apart is worse than one tile."""
        restored = registry.stored_entries(
            {
                "entities": [
                    {"rid": "aaaaaaaa", "entity": "light.desk"},
                    {"rid": "aaaaaaaa", "entity": "light.hall"},
                ]
            },
            "entities",
        )
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].target_entity_id, "light.desk")

    def test_retired_rids_round_trip(self) -> None:
        self.assertEqual(
            registry.stored_retired_rids(
                {"retired_rids": ["aaaaaaaa", "", "bbbbbbbb"]}, "retired_rids"
            ),
            ["aaaaaaaa", "bbbbbbbb"],
        )


if __name__ == "__main__":
    unittest.main()
