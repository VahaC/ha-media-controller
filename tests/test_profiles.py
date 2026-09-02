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

    def test_light_group_brightness_attribute_is_a_fallback(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"brightness": 180}
        )
        self.assertEqual(capabilities["controls"], ("toggle", "brightness"))

    def test_light_group_colour_temperature_attribute_is_a_fallback(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"color_temp_kelvin": 3000}
        )
        self.assertEqual(
            capabilities["controls"], ("toggle", "brightness", "color_temp")
        )

    def test_removed_mired_attribute_does_not_add_colour_temperature(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light", {"color_temp": 333}
        )
        self.assertEqual(capabilities["controls"], ("toggle",))

    def test_capability_signature_ignores_power_state_attributes(self) -> None:
        self.assertEqual(
            profiles.capability_signature(
                {"supported_color_modes": ["brightness"], "brightness": 180}
            ),
            profiles.capability_signature(
                {"supported_color_modes": ["brightness"], "brightness": 100}
            ),
        )

    def test_capability_signature_detects_new_group_capabilities(self) -> None:
        self.assertNotEqual(
            profiles.capability_signature({"supported_color_modes": ["onoff"]}),
            profiles.capability_signature(
                {"supported_color_modes": ["brightness", "color_temp"]}
            ),
        )

    def test_light_group_attributes_override_onoff_only_modes(self) -> None:
        capabilities = profiles.normalize_capabilities(
            "light",
            {
                "supported_color_modes": ["onoff"],
                "brightness": 180,
                "color_temp_kelvin": 3000,
            },
        )
        self.assertEqual(
            capabilities["controls"], ("toggle", "brightness", "color_temp")
        )


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


class SkinTests(unittest.TestCase):
    """Every client offers its own layouts, and only its own."""

    def test_a_client_that_draws_one_interface_offers_no_skins(self) -> None:
        # The classic ESP32 is a controller, not a panel: it applies nothing
        # at runtime and is never sent a settings block at all.
        self.assertEqual(profiles.ESP32_S3.skins, ())

    def test_each_panel_offers_its_own_layouts(self) -> None:
        self.assertEqual(profiles.T560.skins, ("modern", "cassette"))
        self.assertEqual(
            profiles.ESP32_S3_PANEL.skins,
            ("classic", "minimal_ring", "cover_card"),
        )

    def test_a_client_does_not_know_another_client_s_layouts(self) -> None:
        self.assertTrue(profiles.T560.knows_skin("cassette"))
        self.assertFalse(profiles.T560.knows_skin("cover_card"))
        self.assertTrue(profiles.ESP32_S3_PANEL.knows_skin("cover_card"))
        self.assertFalse(profiles.ESP32_S3_PANEL.knows_skin("cassette"))

    def test_the_first_layout_is_the_one_a_client_starts_from(self) -> None:
        for profile in profiles.PANEL_PROFILES:
            with self.subTest(profile=profile.slug):
                self.assertTrue(profile.skins)
                self.assertTrue(profile.knows_skin(profile.skins[0]))
