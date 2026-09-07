"""Nobody types a panel ID.

An ESP32 panel's identifier is its MAC address and the device never puts it on
screen; a T560's is a hash of its own hardware, in a file. Neither is a thing
a person can read off a panel, so a form that asked for one could only be
answered by guessing. Both roads into the integration therefore carry the
identifier themselves — the mDNS record, or the poll a panel with no token has
to make anyway — and these tests hold that shut.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

REPO = Path(__file__).parents[1]
COMPONENT = REPO / "custom_components" / "media_controller"

SPEC = importlib.util.spec_from_file_location(
    "media_controller_profiles_identity", COMPONENT / "profiles.py"
)
assert SPEC is not None and SPEC.loader is not None
profiles = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = profiles
SPEC.loader.exec_module(profiles)

TRANSLATION_FILES = (
    COMPONENT / "strings.json",
    COMPONENT / "translations" / "en.json",
)


class ProfileFromPanelIdTests(unittest.TestCase):
    """What a panel ID says about the hardware behind it."""

    def test_a_tablet_is_read_from_its_prefix(self) -> None:
        profile = profiles.profile_from_panel_id("t560_1a2b3c4d")
        self.assertIs(profile, profiles.T560)

    def test_a_mac_address_is_an_esp32_panel(self) -> None:
        profile = profiles.profile_from_panel_id("a0b7657c1234")
        self.assertIs(profile, profiles.ESP32_S3_PANEL)

    def test_the_prefix_is_matched_the_way_it_arrives(self) -> None:
        # The endpoint lowercases nothing before this is called, and the
        # tablet writes the prefix in lower case; an ID that reached Home
        # Assistant with different case is still that tablet.
        self.assertIs(
            profiles.profile_from_panel_id("  T560_1A2B3C4D "), profiles.T560
        )

    def test_the_answer_is_always_a_panel(self) -> None:
        # Whatever arrives, the guess is only ever the default of a question
        # the pairing form still asks, so it may never be the controller
        # profile, which is not a panel at all.
        for panel_id in ("", "?", "esp32_s3", "t561_1a2b3c4d"):
            with self.subTest(panel_id=panel_id):
                self.assertIn(
                    profiles.profile_from_panel_id(panel_id),
                    profiles.PANEL_PROFILES,
                )


class NoPanelIdIsAskedForTests(unittest.TestCase):
    """No form offers a field for it, and no step exists to hold one."""

    def test_no_form_field_carries_the_panel_id(self) -> None:
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        offenders = re.findall(
            r"vol\.(?:Required|Optional)\(\s*CONF_PANEL_ID", source
        )
        self.assertEqual(
            offenders,
            [],
            "a panel ID reaches the flow from discovery, never from a person",
        )

    def test_no_translation_labels_a_panel_id_field(self) -> None:
        for path in TRANSLATION_FILES:
            document = json.loads(path.read_text(encoding="utf-8"))
            steps = document["config"]["step"]
            with self.subTest(file=path.name):
                self.assertNotIn("panel", steps)
                for name, step in steps.items():
                    self.assertNotIn(
                        "panel_id",
                        step.get("data", {}),
                        f"{name} asks for an identifier no panel displays",
                    )

    def test_the_menu_offers_no_way_to_add_one_by_hand(self) -> None:
        for path in TRANSLATION_FILES:
            document = json.loads(path.read_text(encoding="utf-8"))
            options = document["config"]["step"]["user"]["menu_options"]
            with self.subTest(file=path.name):
                self.assertNotIn("panel", options)

    def test_the_poll_of_an_unknown_panel_offers_it(self) -> None:
        # The other half: with no manual step, a panel that mDNS never
        # reached has exactly one way in, and it is this one.
        source = (COMPONENT / "provision.py").read_text(encoding="utf-8")
        self.assertIn("SOURCE_INTEGRATION_DISCOVERY", source)
        self.assertIn("_async_offer(panel_id)", source)
        flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("async def async_step_integration_discovery", flow)


if __name__ == "__main__":
    unittest.main()
