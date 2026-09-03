"""Tests for pure Music Assistant payload transformations."""

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
    "media_controller_transformations", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
transformations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transformations
SPEC.loader.exec_module(transformations)


class QueueTransformationTests(unittest.TestCase):
    """Verify bounded queue compatibility behavior."""

    def test_beginning_of_queue_offset(self) -> None:
        self.assertEqual(transformations.calculate_queue_offset(2, 5), 0)

    def test_middle_of_queue_offset_and_local_index(self) -> None:
        offset = transformations.calculate_queue_offset(537, 5)
        payload = transformations.transform_queue_items(
            [
                {
                    "media_title": f"Track {index}",
                    "media_artist": "Artist",
                    "queue_item_id": str(index),
                }
                for index in range(532, 582)
            ],
            global_current_index=537,
            offset=offset,
        )
        self.assertEqual(offset, 532)
        self.assertEqual(payload.current_index, 5)
        self.assertEqual(payload.count, 50)

    def test_empty_queue(self) -> None:
        payload = transformations.transform_queue_items(
            [], global_current_index=0, offset=0
        )
        self.assertEqual(payload.as_dict(), {
            "titles": [],
            "artists": [],
            "queue_ids": [],
            "current_index": 0,
            "count": 0,
        })

    def test_invalid_current_index(self) -> None:
        self.assertEqual(transformations.calculate_queue_offset("bad", 5), 0)
        payload = transformations.transform_queue_items(
            [{"media_title": "Only", "queue_item_id": "id"}],
            global_current_index=-10,
            offset=0,
        )
        self.assertEqual(payload.current_index, 0)

    def test_missing_response(self) -> None:
        payload = transformations.transform_queue_items(
            None, global_current_index=None, offset=0
        )
        self.assertEqual(payload.count, 0)

    def test_short_queue_clamps_current_index(self) -> None:
        payload = transformations.transform_queue_items(
            [{"media_title": "One"}, {"media_title": "Two"}],
            global_current_index=99,
            offset=90,
        )
        self.assertEqual(payload.current_index, 1)

    def test_unicode_metadata_is_not_ascii_escaped(self) -> None:
        payload = transformations.transform_queue_items(
            [{
                "media_title": "Океан Ельзи – Без бою",
                "media_artist": "Святослав Вакарчук",
                "queue_item_id": "черга-1",
            }],
            global_current_index=0,
            offset=0,
        )
        encoded = payload.as_json()
        self.assertIn("Океан Ельзи", encoded)
        self.assertNotIn("\\u", encoded)


class PlaylistTransformationTests(unittest.TestCase):
    """Verify playlist filtering and compatibility behavior."""

    def test_normal_list_and_uri_extraction(self) -> None:
        payload = transformations.transform_playlists(
            [
                {"name": "Morning", "uri": "library://playlist/1"},
                {"name": "Evening", "uri": "library://playlist/2"},
            ],
            limit=50,
        )
        self.assertEqual(payload.names, ("Morning", "Evening"))
        self.assertEqual(
            payload.uris,
            ("library://playlist/1", "library://playlist/2"),
        )

    def test_empty_and_missing_items(self) -> None:
        self.assertEqual(
            transformations.transform_playlists([], limit=50).count, 0
        )
        self.assertEqual(
            transformations.transform_playlists(None, limit=50).count, 0
        )

    def test_unicode_names(self) -> None:
        payload = transformations.transform_playlists(
            [{"name": "Українські хіти", "uri": "uri://ua"}],
            limit=50,
        )
        self.assertEqual(payload.names, ("Українські хіти",))

    def test_from_library_filter_is_preserved(self) -> None:
        payload = transformations.transform_playlists(
            [
                {"name": "Artist (from library)", "uri": "uri://generated"},
                {"name": "Keep me", "uri": "uri://keep"},
            ],
            limit=50,
        )
        self.assertEqual(payload.names, ("Keep me",))

    def test_missing_fields_are_safe(self) -> None:
        payload = transformations.transform_playlists([{}], limit=50)
        self.assertEqual(payload.names, ("",))
        self.assertEqual(payload.uris, ("",))

    def test_limit_applies_after_filtering(self) -> None:
        payload = transformations.transform_playlists(
            [
                {"name": "Skip (from library)", "uri": "uri://skip"},
                {"name": "One", "uri": "uri://1"},
                {"name": "Two", "uri": "uri://2"},
            ],
            limit=1,
        )
        self.assertEqual(payload.names, ("One",))

    def test_zero_limit_is_empty(self) -> None:
        payload = transformations.transform_playlists(
            [{"name": "One", "uri": "uri://1"}],
            limit=0,
        )
        self.assertEqual(payload.count, 0)


class ClientConfigTests(unittest.TestCase):
    """Verify the payload each client reads from its config sensor."""

    def _payload(self):
        return transformations.ClientConfigPayload(
            profile="esp32_s3",
            slot_count=6,
            player_entity="media_player.kitchen",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            slots=(
                transformations.SlotPayload(
                    slot=1,
                    entity="light.controller_slot_1",
                    label="DESK LAMP",
                    controls=("toggle", "brightness", "color_temp"),
                    min_kelvin=2000,
                    max_kelvin=6535,
                ),
                transformations.SlotPayload(
                    slot=3,
                    entity="switch.controller_slot_3",
                    label="FAN",
                    controls=("toggle",),
                ),
            ),
        )

    def test_unconfigured_slots_are_omitted(self) -> None:
        attributes = self._payload().as_attributes()
        self.assertEqual(attributes["slot_count"], 6)
        self.assertEqual([slot["slot"] for slot in attributes["slots"]], [1, 3])

    def test_controller_entities_travel_with_the_layout(self) -> None:
        # A client bootstraps from a URL, a token, and its panel ID only.
        attributes = self._payload().as_attributes()
        self.assertEqual(attributes["player"], "media_player.kitchen")
        self.assertEqual(attributes["queue"], "sensor.controller_queue")
        self.assertEqual(
            attributes["playlists"], "sensor.controller_playlists"
        )

    def test_revision_changes_with_a_controller_entity(self) -> None:
        before = self._payload().as_attributes()["revision"]
        moved = transformations.ClientConfigPayload(
            profile="esp32_s3",
            slot_count=6,
            player_entity="media_player.bedroom",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            slots=self._payload().slots,
        )
        self.assertNotEqual(before, moved.as_attributes()["revision"])

    def test_contract_version_is_published(self) -> None:
        """Every client is told which protocol the integration speaks."""
        payload = transformations.ClientConfigPayload(
            contract_version=4,
            player_entity="media_player.kitchen",
        )
        self.assertEqual(payload.as_attributes()["contract_version"], 4)

    def test_contract_version_is_not_part_of_the_revision(self) -> None:
        """It is not layout, and must not restart a panel to redraw one."""
        before = self._payload().as_attributes()["revision"]
        after = transformations.ClientConfigPayload(
            profile="esp32_s3",
            slot_count=6,
            player_entity="media_player.kitchen",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            contract_version=9,
            slots=self._payload().slots,
        ).as_attributes()["revision"]
        self.assertEqual(before, after)

    def test_kelvin_bounds_only_where_they_apply(self) -> None:
        slots = self._payload().as_attributes()["slots"]
        self.assertEqual(slots[0]["min_kelvin"], 2000)
        self.assertNotIn("min_kelvin", slots[1])
        self.assertNotIn("max_kelvin", slots[1])

    def test_a_controller_with_no_slots_configured_still_sends_the_block(
        self,
    ) -> None:
        attributes = transformations.ClientConfigPayload(
            profile="esp32_s3", slot_count=4, slots=()
        ).as_attributes()
        self.assertEqual(attributes["slots"], [])
        self.assertEqual(attributes["slot_count"], 4)
        self.assertNotIn("entities", attributes)

    def test_revision_is_stable_for_equal_configuration(self) -> None:
        first = self._payload().as_attributes()["revision"]
        second = self._payload().as_attributes()["revision"]
        self.assertEqual(first, second)

    def test_revision_changes_with_the_configuration(self) -> None:
        before = self._payload().as_attributes()["revision"]
        after = transformations.ClientConfigPayload(
            profile="esp32_s3",
            slot_count=6,
            slots=(
                transformations.SlotPayload(
                    slot=1,
                    entity="light.controller_slot_1",
                    label="READING LAMP",
                    controls=("toggle", "brightness", "color_temp"),
                    min_kelvin=2000,
                    max_kelvin=6535,
                ),
            ),
        ).as_attributes()["revision"]
        self.assertNotEqual(before, after)


class RegistryPayloadTests(unittest.TestCase):
    """Verify the `entities` block, and who is sent which block at all."""

    def _panel(self, **overrides):
        """Build the payload a panel reads."""
        defaults = dict(
            profile="t560",
            entity_limit=100,
            player_entity="media_player.kitchen",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            contract_version=6,
            entities=(
                transformations.EntityPayload(
                    rid="a3f1c92d",
                    entity="light.desk_lamp",
                    name="Настільна лампа",
                    domain="light",
                    controls=("toggle", "brightness", "color_temp"),
                    min_kelvin=2200,
                    max_kelvin=6500,
                ),
                transformations.EntityPayload(
                    rid="7c04b1e9",
                    entity="switch.fan",
                    name="FAN",
                    domain="switch",
                    controls=("toggle",),
                ),
            ),
        )
        defaults.update(overrides)
        return transformations.ClientConfigPayload(**defaults)

    def _controller(self, **overrides):
        """Build the payload the classic ESP32 firmware reads."""
        defaults = dict(
            profile="esp32_s3",
            slot_count=4,
            player_entity="media_player.kitchen",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            contract_version=6,
            slots=(
                transformations.SlotPayload(
                    slot=1,
                    entity="light.controller_slot_1",
                    label="DESK LAMP",
                    controls=("toggle", "brightness"),
                ),
            ),
        )
        defaults.update(overrides)
        return transformations.ClientConfigPayload(**defaults)

    def test_a_panel_is_sent_entities_and_no_slots(self) -> None:
        attributes = self._panel().as_attributes()
        self.assertIn("entities", attributes)
        self.assertIn("entity_limit", attributes)
        self.assertNotIn("slots", attributes)
        self.assertNotIn("slot_count", attributes)

    def test_the_classic_esp32_is_sent_slots_and_no_entities(self) -> None:
        attributes = self._controller().as_attributes()
        self.assertIn("slots", attributes)
        self.assertIn("slot_count", attributes)
        self.assertNotIn("entities", attributes)
        self.assertNotIn("entity_limit", attributes)

    def test_the_classic_esp32_payload_is_otherwise_unchanged(self) -> None:
        """Version 6 must be invisible to a device already in the field."""
        attributes = self._controller().as_attributes()
        self.assertEqual(
            attributes["slots"],
            [
                {
                    "slot": 1,
                    "entity": "light.controller_slot_1",
                    "label": "DESK LAMP",
                    "controls": ["toggle", "brightness"],
                }
            ],
        )
        self.assertEqual(attributes["slot_count"], 4)

    def test_an_element_carries_its_identity_and_its_domain(self) -> None:
        element = self._panel().as_attributes()["entities"][0]
        self.assertEqual(element["rid"], "a3f1c92d")
        self.assertEqual(element["domain"], "light")
        # The real entity, never a proxy: a panel has none.
        self.assertEqual(element["entity"], "light.desk_lamp")

    def test_a_cyrillic_name_survives(self) -> None:
        element = self._panel().as_attributes()["entities"][0]
        self.assertEqual(element["name"], "Настільна лампа")

    def test_kelvin_bounds_only_where_they_apply(self) -> None:
        elements = self._panel().as_attributes()["entities"]
        self.assertEqual(elements[0]["min_kelvin"], 2200)
        self.assertNotIn("min_kelvin", elements[1])
        self.assertNotIn("max_kelvin", elements[1])

    def test_an_empty_registry_is_valid(self) -> None:
        attributes = self._panel(entities=()).as_attributes()
        self.assertEqual(attributes["entities"], [])
        self.assertEqual(attributes["entity_limit"], 100)

    def test_a_domain_with_no_card_yet_travels_with_no_controls(self) -> None:
        attributes = self._panel(
            entities=(
                transformations.EntityPayload(
                    rid="11112222",
                    entity="weather.home",
                    name="Home",
                    domain="weather",
                ),
            )
        ).as_attributes()
        self.assertEqual(attributes["entities"][0]["controls"], [])
        self.assertEqual(attributes["entities"][0]["domain"], "weather")

    def test_the_registry_is_part_of_the_revision(self) -> None:
        """It is layout, so a change to it must trigger a re-layout."""
        before = self._panel().as_attributes()["revision"]
        after = self._panel(
            entities=self._panel().entities[:1]
        ).as_attributes()["revision"]
        self.assertNotEqual(before, after)

    def test_a_renamed_element_changes_the_revision(self) -> None:
        before = self._panel().as_attributes()["revision"]
        renamed = list(self._panel().entities)
        renamed[0] = transformations.EntityPayload(
            rid=renamed[0].rid,
            entity=renamed[0].entity,
            name="Desk lamp",
            domain=renamed[0].domain,
            controls=renamed[0].controls,
            min_kelvin=renamed[0].min_kelvin,
            max_kelvin=renamed[0].max_kelvin,
        )
        after = self._panel(entities=tuple(renamed)).as_attributes()[
            "revision"
        ]
        self.assertNotEqual(before, after)

    def test_the_revision_is_stable_for_an_equal_registry(self) -> None:
        self.assertEqual(
            self._panel().as_attributes()["revision"],
            self._panel().as_attributes()["revision"],
        )

    def test_the_contract_version_stays_outside_the_revision(self) -> None:
        before = self._panel().as_attributes()["revision"]
        after = self._panel(contract_version=99).as_attributes()["revision"]
        self.assertEqual(before, after)

    def test_a_panel_is_told_which_entity_holds_its_skin(self) -> None:
        attributes = self._panel(
            skin_select_entity="select.kitchen_tablet_player_skin"
        ).as_attributes()
        self.assertEqual(
            attributes["skin_select"], "select.kitchen_tablet_player_skin"
        )

    def test_a_panel_with_no_skin_select_is_sent_no_key(self) -> None:
        """A panel that was told none simply offers no local skin picker."""
        self.assertNotIn("skin_select", self._panel().as_attributes())

    def test_the_classic_esp32_is_never_sent_a_skin_select(self) -> None:
        """It is not a panel: it is sent no settings and nothing to write."""
        attributes = self._controller(
            skin_select_entity="select.anything"
        ).as_attributes()
        self.assertNotIn("skin_select", attributes)

    def test_the_skin_select_stays_outside_the_revision(self) -> None:
        """Which entity holds the skin is not layout.

        It is assigned once, when the select is added, and folding it into the
        checksum would spend a re-layout on a fact that changes nothing on
        screen.
        """
        before = self._panel().as_attributes()["revision"]
        after = self._panel(
            skin_select_entity="select.kitchen_tablet_player_skin"
        ).as_attributes()["revision"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
