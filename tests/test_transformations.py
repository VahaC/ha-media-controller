"""Tests for pure Music Assistant payload transformations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "vahac_media_controller"
    / "transformations.py"
)
SPEC = importlib.util.spec_from_file_location("vahac_transformations", MODULE_PATH)
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


if __name__ == "__main__":
    unittest.main()
