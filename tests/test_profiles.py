"""Tests for client profiles and room-control capability rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "media_controller"
    / "profiles.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_profiles", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
profiles = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = profiles
SPEC.loader.exec_module(profiles)


class CapabilityTests(unittest.TestCase):
    """Verify what a client is told to draw for a target entity."""

    def test_switch_is_toggle_only(self) -> None:
        capabilities = profiles.normalize_capabilities("switch", {})
        self.assertEqual(capabilities["controls"], ("toggle",))
        self.assertNotIn("min_kelvin", capabilities)

    def test_onoff_light_has_no_brightness(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"supported_color_modes": ["onoff"]}
        )
        self.assertEqual(capabilities["controls"], ("toggle",))

    def test_unknown_colour_mode_has_no_brightness(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"supported_color_modes": ["unknown"]}
        )
        self.assertEqual(capabilities["controls"], ("toggle",))

    def test_missing_attributes_degrade_to_toggle(self) -> None:
        self.assertEqual(
            profiles.normalize_capabilities("light", None)["controls"],
            ("toggle",),
        )

    def test_brightness_light(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"supported_color_modes": ["brightness"]}
        )
        self.assertEqual(capabilities["controls"], ("toggle", "brightness"))

    def test_any_colour_mode_implies_brightness(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"supported_color_modes": ["hs", "rgbww"]}
        )
        self.assertEqual(capabilities["controls"], ("toggle", "brightness"))

    def test_colour_temperature_light_reports_bounds(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light",
            {
                "supported_color_modes": ["color_temp"],
                "min_color_temp_kelvin": 2202,
                "max_color_temp_kelvin": 4000,
            },
        )
        self.assertEqual(
            capabilities["controls"], ("toggle", "brightness", "color_temp")
        )
        self.assertEqual(capabilities["min_kelvin"], 2202)
        self.assertEqual(capabilities["max_kelvin"], 4000)

    def test_colour_temperature_bounds_fall_back(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"supported_color_modes": ["color_temp"]}
        )
        self.assertEqual(capabilities["min_kelvin"], 2000)
        self.assertEqual(capabilities["max_kelvin"], 6535)

    def test_single_colour_mode_as_string(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"supported_color_modes": "brightness"}
        )
        self.assertEqual(capabilities["controls"], ("toggle", "brightness"))


class ProfileTests(unittest.TestCase):
    """Verify the per-slot constraints of each client."""

    def test_esp32_slot_domains_are_fixed(self) -> None:
        self.assertEqual(profiles.ESP32_S3.slot_count, 4)
        self.assertEqual(profiles.ESP32_S3.spec(1).domains, ("light",))
        self.assertEqual(profiles.ESP32_S3.spec(3).domains, ("switch",))

    def test_esp32_switch_slot_cannot_dim(self) -> None:
        # Buttons 3 and 4 have no long-press brightness action in the firmware.
        controls = profiles.limit_controls(
            ("toggle", "brightness", "color_temp"), profiles.ESP32_S3.spec(3)
        )
        self.assertEqual(controls, ("toggle",))

    def test_esp32_light_slot_drops_colour_temperature(self) -> None:
        controls = profiles.limit_controls(
            ("toggle", "brightness", "color_temp"), profiles.ESP32_S3.spec(1)
        )
        self.assertEqual(controls, ("toggle", "brightness"))

    def test_paired_esp32_slot_takes_either_domain(self) -> None:
        # The paired firmware learns a slot's domain at runtime, so nothing
        # ties button 1 to a light or button 3 to a switch any more.
        self.assertEqual(profiles.ESP32_S3_PANEL.slot_count, 4)
        for index in range(1, 5):
            self.assertEqual(
                profiles.ESP32_S3_PANEL.spec(index).domains,
                ("light", "switch"),
            )

    def test_paired_esp32_dims_every_slot_but_drops_colour_temp(self) -> None:
        for index in range(1, 5):
            controls = profiles.limit_controls(
                ("toggle", "brightness", "color_temp"),
                profiles.ESP32_S3_PANEL.spec(index),
            )
            self.assertEqual(controls, ("toggle", "brightness"))

    def test_paired_esp32_is_a_panel_and_the_classic_one_is_not(self) -> None:
        self.assertIn(profiles.ESP32_S3_PANEL, profiles.PANEL_PROFILES)
        self.assertNotIn(profiles.ESP32_S3, profiles.PANEL_PROFILES)
        self.assertIs(profiles.CONTROLLER_PROFILE, profiles.ESP32_S3)
        self.assertIs(
            profiles.panel_profile("esp32_s3_panel"),
            profiles.ESP32_S3_PANEL,
        )

    def test_t560_keeps_the_full_control_set(self) -> None:
        self.assertEqual(profiles.T560.slot_count, 6)
        controls = profiles.limit_controls(
            ("toggle", "brightness", "color_temp"), profiles.T560.spec(6)
        )
        self.assertEqual(controls, ("toggle", "brightness", "color_temp"))

    def test_controls_are_ordered_canonically(self) -> None:
        self.assertEqual(
            profiles.order_controls(["color_temp", "toggle", "toggle"]),
            ("toggle", "color_temp"),
        )

    def test_out_of_range_slot_has_no_spec(self) -> None:
        self.assertIsNone(profiles.ESP32_S3.spec(5))

    def test_panel_profile_falls_back(self) -> None:
        self.assertIs(profiles.panel_profile(None), profiles.T560)
        self.assertIs(profiles.panel_profile("esp32_s3"), profiles.T560)
        self.assertIs(profiles.panel_profile("t560"), profiles.T560)


if __name__ == "__main__":
    unittest.main()
