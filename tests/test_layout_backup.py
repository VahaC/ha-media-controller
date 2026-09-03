"""Tests for the copy of its own grid that a panel leaves in Home Assistant.

The endpoint around these rules is ordinary HTTP plumbing and the ownership
check it uses is the status endpoint's, already covered. What is worth testing
is what the store promises: that the blob comes back exactly as it went in,
that one panel cannot see another's, and that the ceiling is real.
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
    / "layout_backup.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_layout_backup", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
layout_backup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = layout_backup
SPEC.loader.exec_module(layout_backup)

PANEL = "t560_1a2b3c4d"
OTHER = "t560_9f8e7d6c"

LAYOUT = (
    '{"v":1,"cols":10,"rows":14,"cards":['
    '{"x":0,"y":0,"w":2,"h":2,"rid":"a3f1c92d","icon":"lightbulb",'
    '"color":"#4dd0e1"}]}'
)


class CeilingTests(unittest.TestCase):
    """Verify the limit on what one panel may store."""

    def test_an_ordinary_layout_is_accepted(self) -> None:
        self.assertFalse(layout_backup.layout_is_too_large(LAYOUT))

    def test_a_layout_at_the_ceiling_is_accepted(self) -> None:
        exactly = "x" * layout_backup.MAX_LAYOUT_BYTES
        self.assertFalse(layout_backup.layout_is_too_large(exactly))

    def test_a_layout_over_the_ceiling_is_refused(self) -> None:
        too_much = "x" * (layout_backup.MAX_LAYOUT_BYTES + 1)
        self.assertTrue(layout_backup.layout_is_too_large(too_much))

    def test_the_ceiling_counts_bytes_and_not_characters(self) -> None:
        """A layout naming Cyrillic rooms is two bytes per letter.

        Counted in characters this would be a different ceiling for different
        people, which is not a limit anybody could reason about.
        """
        cyrillic = "и" * (layout_backup.MAX_LAYOUT_BYTES // 2 + 1)
        self.assertLess(len(cyrillic), layout_backup.MAX_LAYOUT_BYTES)
        self.assertTrue(layout_backup.layout_is_too_large(cyrillic))

    def test_the_ceiling_holds_a_full_grid(self) -> None:
        """A hundred cards is what the T560 profile allows; it has to fit."""
        cards = ",".join(
            '{"x":%d,"y":%d,"w":1,"h":1,"rid":"%08x","icon":"desk-led-strip",'
            '"color":"#4dd0e1"}' % (index % 10, index // 10, index)
            for index in range(100)
        )
        full = '{"v":1,"cols":10,"rows":14,"cards":[%s]}' % cards
        self.assertFalse(layout_backup.layout_is_too_large(full))


class BackupTests(unittest.TestCase):
    """Verify what the collection of saved layouts promises."""

    def test_a_panel_that_never_saved_has_nothing(self) -> None:
        self.assertIsNone(layout_backup.LayoutBackups().get(PANEL))

    def test_a_layout_comes_back_exactly_as_it_went_in(self) -> None:
        """The blob is opaque: Home Assistant stores bytes, not a document."""
        backups = layout_backup.LayoutBackups()
        backups.set(PANEL, LAYOUT)
        self.assertEqual(backups.get(PANEL), LAYOUT)

    def test_something_that_is_not_a_layout_is_stored_anyway(self) -> None:
        """Nothing here parses the blob, so nothing here may reject one.

        The grid format belongs to the client that draws it and may change
        without a change to the contract.
        """
        backups = layout_backup.LayoutBackups()
        backups.set(PANEL, "not a layout at all")
        self.assertEqual(backups.get(PANEL), "not a layout at all")

    def test_one_panel_cannot_see_another(self) -> None:
        backups = layout_backup.LayoutBackups()
        backups.set(PANEL, LAYOUT)
        self.assertIsNone(backups.get(OTHER))

    def test_a_second_save_replaces_the_first(self) -> None:
        backups = layout_backup.LayoutBackups()
        backups.set(PANEL, LAYOUT)
        backups.set(PANEL, "{}")
        self.assertEqual(backups.get(PANEL), "{}")

    def test_an_unchanged_layout_is_not_a_write(self) -> None:
        """A panel sends its copy after every save.

        Rewriting an identical storage file each time would be disk churn for
        a value that did not move.
        """
        backups = layout_backup.LayoutBackups()
        self.assertTrue(backups.set(PANEL, LAYOUT))
        self.assertFalse(backups.set(PANEL, LAYOUT))
        self.assertTrue(backups.set(PANEL, "{}"))

    def test_what_was_read_off_disk_is_restored(self) -> None:
        backups = layout_backup.LayoutBackups({PANEL: LAYOUT, OTHER: "{}"})
        self.assertEqual(backups.get(PANEL), LAYOUT)
        self.assertEqual(backups.get(OTHER), "{}")
        self.assertEqual(
            backups.as_stored(), {PANEL: LAYOUT, OTHER: "{}"}
        )

    def test_an_unusable_storage_file_is_ignored_rather_than_fatal(
        self,
    ) -> None:
        """A store that was hand-edited must not stop the integration."""
        self.assertEqual(layout_backup.LayoutBackups(None).as_stored(), {})
        self.assertEqual(layout_backup.LayoutBackups("nonsense").as_stored(),
                         {})
        self.assertEqual(
            layout_backup.LayoutBackups({PANEL: 42, 7: "x"}).as_stored(), {}
        )

    def test_stored_state_is_a_copy(self) -> None:
        """A caller that mutates what it was handed must not reach inside."""
        backups = layout_backup.LayoutBackups({PANEL: LAYOUT})
        stored = backups.as_stored()
        stored[PANEL] = "tampered"
        self.assertEqual(backups.get(PANEL), LAYOUT)


if __name__ == "__main__":
    unittest.main()
