"""Tests for client profiles and room-control capability rules."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import string
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

    def test_a_domain_with_no_card_yet_gets_no_controls(self) -> None:
        # The registry accepts these groups so that they are already there
        # when a card is written; until then a client ignores the element
        # rather than drawing a toggle nothing would honour.
        for domain in ("media_player", "climate", "cover", "weather"):
            with self.subTest(domain=domain):
                self.assertEqual(
                    profiles.normalize_capabilities(domain, {})["controls"],
                    (),
                )

    def test_the_two_drawable_domains_are_named(self) -> None:
        self.assertEqual(profiles.CARD_DOMAINS, ("light", "switch"))

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

    def test_a_panel_has_no_slots_at_all(self) -> None:
        # Contract version 6: a panel reads an unbounded registry instead,
        # and its proxies are gone with its slots.
        for profile in profiles.PANEL_PROFILES:
            with self.subTest(profile=profile.slug):
                self.assertEqual(profile.slots, ())
                self.assertEqual(profile.slot_count, 0)
                self.assertIsNone(profile.spec(1))

    def test_paired_esp32_dims_every_registry_element_but_drops_colour_temp(
        self,
    ) -> None:
        # The firmware has buttons and a brightness long-press, and no
        # control to set a colour temperature with. The ceiling is the
        # profile's now that there are no per-slot specifications.
        controls = profiles.limit_controls(
            ("toggle", "brightness", "color_temp"),
            profiles.ESP32_S3_PANEL,
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
        self.assertEqual(profiles.T560.entity_limit, 100)
        controls = profiles.limit_controls(
            ("toggle", "brightness", "color_temp"), profiles.T560
        )
        self.assertEqual(controls, ("toggle", "brightness", "color_temp"))

    def test_only_a_panel_has_a_registry(self) -> None:
        self.assertFalse(profiles.ESP32_S3.has_registry)
        self.assertEqual(profiles.ESP32_S3.entity_limit, 0)
        for profile in profiles.PANEL_PROFILES:
            with self.subTest(profile=profile.slug):
                self.assertTrue(profile.has_registry)

    def test_the_two_panel_limits_differ(self) -> None:
        # A tablet caches the payload to a file; an ESP32 parses it on the
        # device with no JSON library. The numbers answer different questions.
        self.assertEqual(profiles.T560.entity_limit, 100)
        self.assertEqual(profiles.ESP32_S3_PANEL.entity_limit, 64)

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


class UpdateKindTests(unittest.TestCase):
    """Verify that every panel can be told how to bring itself up to date."""

    ISSUES = ("panel_contract_outdated", "panel_never_reported")

    def _strings(self) -> dict:
        path = (
            Path(__file__).parents[1]
            / "custom_components"
            / "media_controller"
            / "strings.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))["issues"]

    def test_the_two_panels_are_updated_differently(self) -> None:
        # A tablet is rebuilt and copied over SSH; an ESP32 is reflashed.
        self.assertEqual(
            profiles.T560.update_kind, profiles.UPDATE_KIND_TABLET
        )
        self.assertEqual(
            profiles.ESP32_S3_PANEL.update_kind,
            profiles.UPDATE_KIND_FIRMWARE,
        )

    def test_every_panel_has_both_repair_texts(self) -> None:
        """A new profile must not leave a raw translation key on screen."""
        issues = self._strings()
        for profile in profiles.PANEL_PROFILES:
            for issue in self.ISSUES:
                key = f"{issue}_{profile.update_kind}"
                with self.subTest(key=key):
                    self.assertIn(key, issues)
                    self.assertTrue(issues[key]["title"])
                    self.assertTrue(issues[key]["description"])

    def test_the_repair_texts_use_only_offered_placeholders(self) -> None:
        offered = {"name", "panel_contract", "integration_contract"}
        for key, issue in self._strings().items():
            with self.subTest(key=key):
                used = set(
                    field
                    for text in (issue["title"], issue["description"])
                    for _, field, _, _ in string.Formatter().parse(text)
                    if field
                )
                self.assertTrue(used <= offered, used - offered)
