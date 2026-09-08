"""Tests for the panel theme of contract version 9.

The eight colours and four opacities were ESPHome entities until that version,
which meant they existed only for as long as the ESPHome integration did.
Moving them into the contract is what made that integration removable, so what
is protected here is the shape a panel actually receives and the rule that a
value it cannot use never reaches it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).parents[1] / "custom_components" / "media_controller"


def _load(name: str, filename: str):
    """Import one module of the integration without a Home Assistant runtime."""
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


panel_state = _load("media_controller_theme_state", "panel_state.py")
transformations = _load("media_controller_theme_payload", "transformations.py")


class DefaultsTests(unittest.TestCase):
    """A panel that has never been themed still gets a complete theme."""

    def test_nothing_stored_gives_the_values_the_firmware_shipped_with(
        self,
    ) -> None:
        # These are the initial_value of the ESPHome entities this replaced.
        # A device upgraded to contract version 9 must look unchanged until
        # somebody chooses something.
        theme = panel_state.PanelTheme.from_stored(None)
        self.assertEqual(theme.color_arc, "#1a1a35")
        self.assertEqual(theme.color_arc_indicator, "#00cfff")
        self.assertEqual(theme.color_title, "#ffffff")
        self.assertEqual(theme.color_flat_controls, "#d8dce6")
        self.assertEqual(theme.opacity_album_art, 255)
        self.assertEqual(theme.opacity_decoration, 153)

    def test_every_key_is_always_present(self) -> None:
        payload = panel_state.PanelTheme.from_stored({}).as_payload()
        self.assertEqual(set(payload), set(panel_state.THEME_KEYS))

    def test_the_keys_are_the_field_names(self) -> None:
        """An entity reads its own value by name; they must not drift."""
        theme = panel_state.PanelTheme()
        for key in panel_state.THEME_KEYS:
            with self.subTest(key=key):
                self.assertTrue(hasattr(theme, key))


class ColourTests(unittest.TestCase):
    """A colour is `#` and six hexadecimal digits, or it is not a colour."""

    def _colour(self, value):
        return panel_state.PanelTheme.from_stored(
            {"color_title": value}
        ).color_title

    def test_a_valid_colour_survives(self) -> None:
        self.assertEqual(self._colour("#123abc"), "#123abc")

    def test_case_is_normalised(self) -> None:
        self.assertEqual(self._colour("#12ABCD"), "#12abcd")

    def test_a_missing_hash_is_added(self) -> None:
        # The ESPHome entities stored bare hex, so a value carried over from
        # a hand-edited entry can arrive without one.
        self.assertEqual(self._colour("00cfff"), "#00cfff")

    def test_surrounding_space_is_ignored(self) -> None:
        self.assertEqual(self._colour("  #00cfff  "), "#00cfff")

    def test_unusable_values_keep_the_default(self) -> None:
        default = panel_state.THEME_COLOR_DEFAULTS["color_title"]
        for value in (
            "#fff",
            "#1234567",
            "#gggggg",
            "red",
            "",
            None,
            255,
            True,
            ["#ffffff"],
        ):
            with self.subTest(value=value):
                self.assertEqual(self._colour(value), default)

    def test_a_rejected_colour_does_not_take_the_others_with_it(self) -> None:
        theme = panel_state.PanelTheme.from_stored(
            {"color_title": "nonsense", "color_artist": "#010203"}
        )
        self.assertEqual(theme.color_title, "#ffffff")
        self.assertEqual(theme.color_artist, "#010203")


class OpacityTests(unittest.TestCase):
    """An opacity is an integer 0 - 255, clamped rather than refused."""

    def _opacity(self, value):
        return panel_state.PanelTheme.from_stored(
            {"opacity_arc": value}
        ).opacity_arc

    def test_a_value_in_range_survives(self) -> None:
        self.assertEqual(self._opacity(128), 128)

    def test_the_ends_of_the_range_are_valid(self) -> None:
        self.assertEqual(self._opacity(0), 0)
        self.assertEqual(self._opacity(255), 255)

    def test_out_of_range_values_are_clamped(self) -> None:
        self.assertEqual(self._opacity(-40), 0)
        self.assertEqual(self._opacity(9000), 255)

    def test_a_float_is_truncated(self) -> None:
        self.assertEqual(self._opacity(153.9), 153)

    def test_unusable_values_keep_the_default(self) -> None:
        default = panel_state.THEME_OPACITY_DEFAULTS["opacity_arc"]
        for value in ("half", None, True, [200]):
            with self.subTest(value=value):
                self.assertEqual(self._opacity(value), default)


class RoundTripTests(unittest.TestCase):
    """What is stored comes back, and one value changes on its own."""

    def test_a_stored_theme_survives_a_round_trip(self) -> None:
        original = panel_state.PanelTheme.from_stored(
            {"color_buttons": "#abcdef", "opacity_buttons": 40}
        )
        self.assertEqual(
            panel_state.PanelTheme.from_stored(original.as_stored()), original
        )

    def test_one_value_is_replaced_and_revalidated(self) -> None:
        theme = panel_state.PanelTheme()
        changed = theme.with_value("color_volume", "#0a0b0c")
        self.assertEqual(changed.color_volume, "#0a0b0c")
        self.assertEqual(changed.color_title, theme.color_title)

    def test_replacing_a_value_with_nonsense_changes_nothing(self) -> None:
        theme = panel_state.PanelTheme()
        self.assertEqual(theme.with_value("color_volume", "purple"), theme)


class StateTests(unittest.TestCase):
    """The theme travels beside the settings and the commands."""

    def test_it_is_a_block_of_its_own_in_the_payload(self) -> None:
        payload = panel_state.PanelState().as_payload()
        self.assertIn("theme", payload)
        self.assertEqual(set(payload["theme"]), set(panel_state.THEME_KEYS))

    def test_setting_one_value_notifies_the_config_sensor(self) -> None:
        state = panel_state.PanelState()
        seen: list[int] = []
        state.add_config_listener(lambda: seen.append(1))
        state.set_theme_value("color_arc", "#111111")
        self.assertEqual(len(seen), 1)

    def test_setting_the_same_value_notifies_nobody(self) -> None:
        """A poll must not rewrite a state for a value that did not move."""
        state = panel_state.PanelState()
        seen: list[int] = []
        state.add_config_listener(lambda: seen.append(1))
        state.set_theme_value("color_arc", state.theme.color_arc)
        self.assertEqual(seen, [])


class PayloadTests(unittest.TestCase):
    """Who is sent the block, and where it sits in the payload."""

    def _payload(self, **overrides):
        defaults = dict(
            profile="esp32_s3_panel",
            entity_limit=64,
            player_entity="media_player.kitchen",
            queue_entity="sensor.controller_queue",
            playlists_entity="sensor.controller_playlists",
            contract_version=9,
            entities=(),
        )
        defaults.update(overrides)
        return transformations.ClientConfigPayload(**defaults)

    def test_a_client_with_no_theme_is_sent_no_block(self) -> None:
        self.assertNotIn("theme", self._payload().as_attributes())

    def test_a_client_with_a_theme_is_sent_it(self) -> None:
        attributes = self._payload(
            theme={"color_arc": "#1a1a35"}
        ).as_attributes()
        self.assertEqual(attributes["theme"], {"color_arc": "#1a1a35"})

    def test_the_theme_stays_outside_the_revision(self) -> None:
        """Restyling is not layout: a colour must not rebuild the room page."""
        before = self._payload().as_attributes()["revision"]
        after = self._payload(
            theme={"color_arc": "#1a1a35"}
        ).as_attributes()["revision"]
        self.assertEqual(before, after)

    def test_a_different_colour_still_reaches_the_client(self) -> None:
        """Outside the revision is not the same as not sent."""
        first = self._payload(theme={"color_arc": "#000000"}).as_attributes()
        second = self._payload(theme={"color_arc": "#ffffff"}).as_attributes()
        self.assertNotEqual(first["theme"], second["theme"])


if __name__ == "__main__":
    unittest.main()
