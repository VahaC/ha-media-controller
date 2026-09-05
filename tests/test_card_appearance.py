"""Tests for the two things a person can say about how a card is drawn.

The endpoint around these rules is ordinary HTTP plumbing and the ownership
check it reuses is the status endpoint's, already covered. What is worth
testing is what the rules promise:

* an empty name means **the Home Assistant entity's own name**, which is what
  makes the field clearable without a second control;
* a name survives every script intact, because the payload has been UTF-8
  since the registry existed;
* setting the appearance of one element touches **that element and nothing
  else**, which is the whole security argument for the editor route;
* an element carrying no icon is stored exactly as one saved before icons
  existed, so nothing is rewritten on disk for a feature nobody used.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

INTEGRATION = (
    Path(__file__).parents[1] / "custom_components" / "media_controller"
)


def _load(name: str, filename: str):
    """Load one integration module without a Home Assistant runtime."""
    spec = importlib.util.spec_from_file_location(
        name, INTEGRATION / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


registry = _load("media_controller_registry_cards", "registry.py")
transformations = _load(
    "media_controller_transformations_cards", "transformations.py"
)

CYRILLIC = "Настільна лампа"


def _entry(rid: str, **overrides) -> "registry.RegistryEntry":
    defaults = {
        "rid": rid,
        "target_entity_id": f"light.lamp_{rid}",
        "domain": "light",
    }
    defaults.update(overrides)
    return registry.RegistryEntry(**defaults)


class NameTests(unittest.TestCase):
    """What may be a display name."""

    def test_a_plain_name_is_kept(self) -> None:
        name, failure = registry.normalize_name("Desk lamp")
        self.assertEqual(name, "Desk lamp")
        self.assertEqual(failure, registry.NAME_OK)

    def test_whitespace_is_trimmed(self) -> None:
        name, failure = registry.normalize_name("   Desk lamp\t ")
        self.assertEqual(name, "Desk lamp")
        self.assertEqual(failure, registry.NAME_OK)

    def test_a_name_of_only_whitespace_is_a_cleared_name(self) -> None:
        """Somebody who selects all and types a space means "clear it"."""
        for value in ("", "   ", "\t", " ", None):
            with self.subTest(value=value):
                name, failure = registry.normalize_name(value)
                self.assertEqual(name, "")
                self.assertEqual(failure, registry.NAME_OK)

    def test_every_script_is_a_name(self) -> None:
        for value in (CYRILLIC, "Λάμπα", "デスクランプ", "灯 1", "Lampe 💡"):
            with self.subTest(value=value):
                name, failure = registry.normalize_name(value)
                self.assertEqual(name, value)
                self.assertEqual(failure, registry.NAME_OK)

    def test_control_characters_are_refused_rather_than_stripped(self) -> None:
        for value in ("Desk\nlamp", "Desk\tlamp\rrest", "Desk\x00lamp"):
            with self.subTest(value=value):
                name, failure = registry.normalize_name(value)
                self.assertEqual(name, "")
                self.assertEqual(failure, registry.NAME_UNPRINTABLE)

    def test_a_tab_at_the_end_is_trimmed_not_refused(self) -> None:
        """Trimming happens first, so trailing whitespace is not a control
        character somebody has to be told about."""
        name, failure = registry.normalize_name("Desk lamp\t")
        self.assertEqual(name, "Desk lamp")
        self.assertEqual(failure, registry.NAME_OK)

    def test_the_bound_is_in_characters_and_not_in_bytes(self) -> None:
        """A Cyrillic name may be exactly as long as a Latin one.

        The limit exists to bound what the paired ESP32 holds in RAM, but a
        limit in bytes would let one script be twice as long as another for no
        reason a person could see.
        """
        latin = "a" * registry.MAX_NAME_LENGTH
        cyrillic = "я" * registry.MAX_NAME_LENGTH
        for value in (latin, cyrillic):
            with self.subTest(value=value[:4]):
                name, failure = registry.normalize_name(value)
                self.assertEqual(name, value)
                self.assertEqual(failure, registry.NAME_OK)

    def test_one_character_over_the_bound_is_refused(self) -> None:
        for value in (
            "a" * (registry.MAX_NAME_LENGTH + 1),
            "я" * (registry.MAX_NAME_LENGTH + 1),
        ):
            with self.subTest(value=value[:4]):
                name, failure = registry.normalize_name(value)
                self.assertEqual(name, "")
                self.assertEqual(failure, registry.NAME_TOO_LONG)

    def test_a_combined_accent_counts_as_one_character(self) -> None:
        """Normalized to NFC first, so the same name is the same length
        however it was typed."""
        composed = "é" * registry.MAX_NAME_LENGTH
        decomposed = "é" * registry.MAX_NAME_LENGTH
        name, failure = registry.normalize_name(decomposed)
        self.assertEqual(failure, registry.NAME_OK)
        self.assertEqual(name, composed)

    def test_a_value_that_is_not_a_string_is_refused(self) -> None:
        for value in (3, True, ["a"], {"name": "a"}):
            with self.subTest(value=value):
                _name, failure = registry.normalize_name(value)
                self.assertEqual(failure, registry.NAME_UNPRINTABLE)


class AppearanceTests(unittest.TestCase):
    """Setting the name and the icon of one element."""

    def setUp(self) -> None:
        self.entries = [
            _entry("a3f1c92d", name="Desk lamp"),
            _entry("7c41b8e0", domain="switch", icon="fan"),
        ]

    def test_a_name_is_set_on_the_named_element_only(self) -> None:
        updated, changed = registry.apply_card_appearance(
            self.entries, "a3f1c92d", name=CYRILLIC
        )
        self.assertTrue(changed)
        self.assertEqual(updated[0].name, CYRILLIC)
        self.assertEqual(updated[1], self.entries[1])

    def test_an_icon_is_set_on_the_named_element_only(self) -> None:
        updated, changed = registry.apply_card_appearance(
            self.entries, "a3f1c92d", icon="desk-lamp"
        )
        self.assertTrue(changed)
        self.assertEqual(updated[0].icon, "desk-lamp")
        self.assertEqual(updated[0].name, "Desk lamp")
        self.assertEqual(updated[1], self.entries[1])

    def test_an_absent_argument_leaves_that_half_alone(self) -> None:
        """Changing an icon must not turn an automatic name into a stored one.

        Otherwise the tile would stop following its entity through a rename
        the first time anybody touched its picture.
        """
        entries = [_entry("a3f1c92d")]
        updated, _changed = registry.apply_card_appearance(
            entries, "a3f1c92d", icon="fan"
        )
        self.assertEqual(updated[0].name, "")
        self.assertEqual(updated[0].icon, "fan")

    def test_clearing_a_name_restores_the_entity_name(self) -> None:
        updated, changed = registry.apply_card_appearance(
            self.entries, "a3f1c92d", name=""
        )
        self.assertTrue(changed)
        self.assertEqual(updated[0].name, "")

    def test_clearing_an_icon_is_automatic(self) -> None:
        updated, changed = registry.apply_card_appearance(
            self.entries, "7c41b8e0", icon=""
        )
        self.assertTrue(changed)
        self.assertEqual(updated[1].icon, "")

    def test_setting_what_is_already_set_changes_nothing(self) -> None:
        updated, changed = registry.apply_card_appearance(
            self.entries, "a3f1c92d", name="Desk lamp"
        )
        self.assertFalse(changed)
        self.assertEqual(updated, self.entries)

    def test_an_unknown_rid_touches_nothing(self) -> None:
        updated, changed = registry.apply_card_appearance(
            self.entries, "ffffffff", name="Nowhere", icon="fan"
        )
        self.assertFalse(changed)
        self.assertEqual(updated, self.entries)

    def test_find_entry_is_how_an_unknown_rid_is_recognised(self) -> None:
        self.assertIsNotNone(registry.find_entry(self.entries, "a3f1c92d"))
        self.assertIsNone(registry.find_entry(self.entries, "ffffffff"))

    def test_the_target_entity_is_never_touched(self) -> None:
        """Naming a card is not renaming an entity."""
        updated, _changed = registry.apply_card_appearance(
            self.entries, "a3f1c92d", name=CYRILLIC, icon="desk-lamp"
        )
        self.assertEqual(
            updated[0].target_entity_id, self.entries[0].target_entity_id
        )
        self.assertEqual(updated[0].domain, self.entries[0].domain)
        self.assertEqual(updated[0].rid, self.entries[0].rid)


class StorageTests(unittest.TestCase):
    """What reaches the config entry, and what comes back."""

    def test_an_automatic_icon_is_not_written(self) -> None:
        """An entry saved before icons existed and one whose icon is
        automatic are the same record on disk."""
        self.assertNotIn(
            registry.REGISTRY_KEY_ICON, _entry("a3f1c92d").as_stored()
        )

    def test_a_chosen_icon_round_trips(self) -> None:
        stored = _entry("a3f1c92d", name=CYRILLIC, icon="blind").as_stored()
        self.assertEqual(stored[registry.REGISTRY_KEY_ICON], "blind")
        restored = registry.RegistryEntry.from_stored(stored)
        assert restored is not None
        self.assertEqual(restored.icon, "blind")
        self.assertEqual(restored.name, CYRILLIC)

    def test_a_record_written_before_icons_reads_as_automatic(self) -> None:
        restored = registry.RegistryEntry.from_stored(
            {
                registry.REGISTRY_KEY_RID: "a3f1c92d",
                registry.REGISTRY_KEY_ENTITY: "light.desk_lamp",
                registry.REGISTRY_KEY_DOMAIN: "light",
                registry.REGISTRY_KEY_NAME: "Desk lamp",
                registry.REGISTRY_KEY_CONTROLS: ["toggle"],
            }
        )
        assert restored is not None
        self.assertEqual(restored.icon, "")


class PayloadTests(unittest.TestCase):
    """What a client is sent."""

    def test_an_automatic_icon_is_left_out_of_the_payload(self) -> None:
        """An installation that has chosen no icons pays nothing for the
        feature, on a payload the ESP32 reads out of a fixed buffer."""
        payload = transformations.EntityPayload(
            rid="a3f1c92d",
            entity="light.desk_lamp",
            name="Desk lamp",
            domain="light",
        ).as_dict()
        self.assertNotIn("icon", payload)

    def test_a_chosen_icon_travels(self) -> None:
        payload = transformations.EntityPayload(
            rid="a3f1c92d",
            entity="light.desk_lamp",
            name=CYRILLIC,
            domain="light",
            icon="desk-lamp",
        ).as_dict()
        self.assertEqual(payload["icon"], "desk-lamp")
        self.assertEqual(payload["name"], CYRILLIC)

    def test_the_icon_is_inside_the_revision(self) -> None:
        """Choosing a picture is a layout change, so a client relays it out.

        It sits with `entities` rather than beside `room_states`: it changes
        what a card looks like, which is exactly what `revision` exists to
        make a client notice.
        """
        without = transformations.ClientConfigPayload(
            profile="esp32_s3_panel",
            entity_limit=64,
            entities=(
                transformations.EntityPayload(
                    rid="a3f1c92d",
                    entity="light.desk_lamp",
                    name="Desk lamp",
                    domain="light",
                ),
            ),
        ).as_attributes()
        with_icon = transformations.ClientConfigPayload(
            profile="esp32_s3_panel",
            entity_limit=64,
            entities=(
                transformations.EntityPayload(
                    rid="a3f1c92d",
                    entity="light.desk_lamp",
                    name="Desk lamp",
                    domain="light",
                    icon="desk-lamp",
                ),
            ),
        ).as_attributes()
        self.assertNotEqual(without["revision"], with_icon["revision"])

    def test_the_classic_controller_is_sent_none_of_it(self) -> None:
        """It reads `slots`, which carry no icon and no registry name."""
        payload = transformations.ClientConfigPayload(
            profile="esp32_s3",
            slot_count=4,
            slots=(
                transformations.SlotPayload(
                    slot=1, entity="light.controller_slot_1", label="DESK LAMP"
                ),
            ),
        ).as_attributes()
        self.assertNotIn("entities", payload)
        self.assertNotIn("icon", payload["slots"][0])


if __name__ == "__main__":
    unittest.main()
