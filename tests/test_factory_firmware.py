"""Static checks that the factory image stays universal.

One binary is flashed onto every panel from a public web page, so the rule it
has to keep is unusually blunt: nothing personal to one installation may be in
it. That is a property of a few files rather than of any function, and none of
those files is Python, so it is checked here — before a build, rather than by
reading a 5 MB image afterwards.

`tools/make-web-installer.py` checks the compiled image for the same things
and refuses to publish one that fails. This is the earlier half: it catches a
change to the configuration in the pull request that made it, and it says
which line is wrong.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest

REPO = Path(__file__).parents[1]
FIRMWARE = REPO / "firmware"
FACTORY = FIRMWARE / "media-controller-factory.yaml"
PAIRED = FIRMWARE / "media-controller-paired.yaml"
UI = FIRMWARE / "media-controller-ui.yaml"
INSTALLER = REPO / "installer"
REQUIREMENTS = FIRMWARE / "requirements.txt"
WORKFLOWS = REPO / ".github" / "workflows"

# The image the first updatable panels are running. It is build output and is
# not committed, so anything that reads it skips when it is not there — a
# checkout has no copy, and a maintainer who has just run the packaging
# script does.
RELEASED_IMAGE = (
    INSTALLER / "firmware" / "0.5.0" / "media-controller-factory.factory.bin"
)

SPEC = importlib.util.spec_from_file_location(
    "media_controller_make_web_installer", REPO / "tools" / "make-web-installer.py"
)
assert SPEC is not None and SPEC.loader is not None
make_web_installer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = make_web_installer
SPEC.loader.exec_module(make_web_installer)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FactoryEntrypointTests(unittest.TestCase):
    """Verify that the shipped image carries nothing installation-specific."""

    def test_the_entrypoint_exists(self) -> None:
        self.assertTrue(FACTORY.is_file())

    def test_the_shipped_configuration_is_impersonal(self) -> None:
        # The same rule the publishing script enforces, so a change that
        # breaks it fails here rather than at the end of a fifteen-minute
        # compile.
        self.assertEqual(make_web_installer.check_configuration(), [])

    def test_no_address_is_compiled_in(self) -> None:
        self.assertTrue(
            re.search(r'^\s*ha_url:\s*""\s*$', _read(FACTORY), re.MULTILINE)
        )

    def test_the_interface_is_not_duplicated(self) -> None:
        # The factory image is the paired firmware plus four things. A second
        # copy of the LVGL interface would be two interfaces to keep in step.
        text = _read(FACTORY)
        self.assertIn("!include media-controller-paired.yaml", text)
        self.assertNotIn("media-controller-ui.yaml", text)

    def test_wi_fi_arrives_at_runtime(self) -> None:
        text = _read(FACTORY)
        self.assertIn("improv_serial:", text)
        self.assertIn("captive_portal:", text)

    def test_every_device_gets_its_own_name(self) -> None:
        self.assertIn("name_add_mac_suffix: true", _read(FACTORY))

    def test_the_api_key_is_per_device(self) -> None:
        # `encryption:` with no `key:`. A key written here would be the same
        # on every panel flashed from this image, which is not a key.
        text = _read(FACTORY)
        self.assertTrue(re.search(r"^api:\n\s+encryption:\s*$", text, re.M))
        self.assertIsNone(re.search(r"^\s*key:", text, re.MULTILINE))

    def test_the_toolchain_is_pinned(self) -> None:
        # Not a tidiness rule. ESPHome decides from its own defaults whether
        # the bootloader it builds can roll an update back, and an
        # application update cannot replace a bootloader afterwards. An
        # unpinned toolchain leaves that to whichever release happened to be
        # newest on the day, for a device that goes on a wall.
        self.assertTrue(
            re.search(r"^esphome==\d+\.\d+", _read(REQUIREMENTS), re.MULTILINE)
        )
        for workflow in ("firmware.yml", "installer.yml"):
            with self.subTest(workflow=workflow):
                text = _read(WORKFLOWS / workflow)
                self.assertIn("pip install -r firmware/requirements.txt", text)
                self.assertNotIn("pip install esphome", text)


class OverTheAirTests(unittest.TestCase):
    """Verify that an update is authorised per device and can be undone."""

    def test_the_shipped_image_carries_no_esphome_ota(self) -> None:
        # The platform with a password and a listening socket. A password
        # compiled into a public binary is the same password on every panel
        # flashed from it.
        for path in (FACTORY, PAIRED):
            with self.subTest(path=path.name):
                self.assertIsNone(
                    re.search(
                        r"^\s*-\s*platform:\s*esphome\s*$",
                        _read(path),
                        re.MULTILINE,
                    )
                )

    def test_the_update_client_is_the_one_that_opens_no_port(self) -> None:
        text = _read(PAIRED)
        self.assertIn("- platform: http_request", text)
        self.assertIn("id: panel_ota", text)
        self.assertIn("ota.http_request.flash:", text)

    def test_the_captive_portal_route_is_not_widened(self) -> None:
        # Adding an outbound update client must not touch the one inbound
        # route this image has, which stays narrowed to the recovery access
        # point by this define.
        self.assertIn('-DUSE_WEBSERVER_OTA_DISABLED', _read(FACTORY))

    def test_rollback_is_not_left_to_the_defaults(self) -> None:
        # Both values differ from ESPHome's, and both have to: an orderly
        # restart is not evidence that an image works, and the timer must not
        # confirm an image that verify_new_image is about to roll back.
        block = re.search(
            r"^safe_mode:\n(?:^ .*\n)+", _read(PAIRED), re.MULTILINE
        )
        assert block is not None, "safe_mode is not declared"
        self.assertIn("boot_is_good_on_shutdown: false", block.group(0))
        self.assertIn("boot_is_good_after: 15min", block.group(0))

    def test_an_image_is_confirmed_by_reaching_home_assistant(self) -> None:
        # Not by starting. A build that boots and can never reach Home
        # Assistant again is the failure this whole mechanism exists to undo.
        text = _read(PAIRED)
        self.assertIn("safe_mode.mark_successful:", text)
        self.assertIn("id(config_seen)", text)
        self.assertIn("id(confirm_boot)->execute();", text)

    def test_a_new_image_that_goes_quiet_restarts_itself(self) -> None:
        # The bootloader rolls back on a reset before confirmation, so an
        # image that never resets is never rolled back. This is the reset.
        text = _read(PAIRED)
        self.assertIn("id(update_proving)", text)
        self.assertIn("App.safe_reboot();", text)

    def test_the_target_version_survives_the_update(self) -> None:
        # The only thing the next boot can use to tell an update that worked
        # from one the bootloader undid, so it has to be in flash.
        declaration = re.search(
            r"^  - id: update_target_version\n(?:^ .*\n)+",
            _read(PAIRED),
            re.MULTILINE,
        )
        assert declaration is not None, "update_target_version is not declared"
        self.assertIn("restore_value: true", declaration.group(0))

    def test_the_download_address_is_built_from_the_paired_address(self) -> None:
        # A path from Home Assistant joined to the address this device is
        # already using, and refused unless it is on this route. Nothing
        # arrives from anywhere else.
        text = _read(PAIRED)
        self.assertIn(
            'path.rfind(\n                                         '
            '"/api/media_controller/panel_firmware/",',
            text,
        )
        self.assertIn("id(update_url) = id(ha_base) + path;", text)


class PartitionTableTests(unittest.TestCase):
    """Verify the one thing no later code change could repair.

    An update writes the inactive application slot and nothing else. So there
    have to be two of them, they have to be large enough, and none of the
    partitions may move — NVS holds the Wi-Fi credentials, the pairing token
    and the room layout of every panel already installed.
    """

    def test_two_application_slots_are_expected(self) -> None:
        names = [name for name, *_rest in make_web_installer.EXPECTED_PARTITIONS]
        self.assertIn("app0", names)
        self.assertIn("app1", names)
        self.assertIn("otadata", names)
        self.assertIn("nvs", names)

    def test_the_expected_table_matches_the_released_image(self) -> None:
        if not RELEASED_IMAGE.is_file():
            self.skipTest("the released image is build output and is absent")
        table = make_web_installer.read_partition_table(
            RELEASED_IMAGE.read_bytes()
        )
        self.assertEqual(
            table, list(make_web_installer.EXPECTED_PARTITIONS)
        )

    def test_a_moved_table_is_refused(self) -> None:
        if not RELEASED_IMAGE.is_file():
            self.skipTest("the released image is build output and is absent")
        image = bytearray(RELEASED_IMAGE.read_bytes())
        # Move nvs by one flash sector, which is exactly the change that
        # would destroy every installed panel's pairing.
        entry = make_web_installer.PARTITION_TABLE_OFFSET + 4 * 32
        image[entry + 4] = (image[entry + 4] + 0x10) & 0xFF
        problems = make_web_installer.check_partitions(bytes(image), 2_000_000)
        self.assertEqual(len(problems), 1)
        self.assertIn("partition table has changed", problems[0])

    def test_an_image_too_large_for_a_slot_is_refused(self) -> None:
        if not RELEASED_IMAGE.is_file():
            self.skipTest("the released image is build output and is absent")
        problems = make_web_installer.check_partitions(
            RELEASED_IMAGE.read_bytes(), 9_000_000
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("application slot", problems[0])

    def test_the_contract_version_is_read_from_the_firmware(self) -> None:
        self.assertGreaterEqual(make_web_installer.contract_version(), 8)


class PairedFirmwareTests(unittest.TestCase):
    """Verify that the paired firmware learns its address instead of holding it."""

    def test_the_address_is_a_runtime_global(self) -> None:
        # Declared, and restored: a device that boots while Home Assistant is
        # down has to know where to ask once it comes back.
        declaration = re.search(
            r"^  - id: ha_base\n(?:^ .*\n)+", _read(PAIRED), re.MULTILINE
        )
        assert declaration is not None, "ha_base is not declared"
        self.assertIn("restore_value: true", declaration.group(0))

    def test_nothing_builds_a_url_out_of_the_substitution(self) -> None:
        # ${ha_url} survives only in the boot lambda that copies a
        # compile-time address into the global, which is what keeps existing
        # package-based installations behaving as they always did. Every other
        # use would be an address that a factory image cannot have.
        bootstrap_lines = {
            'if (std::string("${ha_url}").size() > 0) {',
            'id(ha_base) = "${ha_url}";',
        }
        offenders = [
            line
            for line in _read(PAIRED).splitlines()
            if "${ha_url}" in line
            and line.strip() not in bootstrap_lines
            and not line.strip().startswith("#")
            and not line.strip().startswith("ha_url:")
        ]
        self.assertEqual(offenders, [])

    def test_the_provisioning_endpoint_is_declared(self) -> None:
        text = _read(PAIRED)
        self.assertIn("media_controller_provision:", text)
        self.assertIn("components: [media_controller_grid, "
                      "media_controller_provision]", text)
        self.assertIn("set_apply_handler", text)

    def test_the_endpoint_is_told_every_time_the_state_changes(self) -> None:
        # It answers only while the device is unpaired, and it learns which it
        # is from here. A path that stores a token without saying so would
        # leave the endpoint open on a paired device — so all three are
        # asserted rather than the fact that the call exists somewhere.
        text = _read(PAIRED)
        self.assertEqual(text.count("set_state("), 3)
        # Pairing by being polled, pairing by being pushed to, and the one
        # place that reopens it: show_start_page, which forget_token calls.
        self.assertIn(
            "id(panel_provision)->set_state(!id(ha_token).empty(),", text
        )
        self.assertEqual(
            text.count("id(panel_provision)->set_state(true, std::string());"),
            2,
        )

    def test_the_discovery_record_names_the_port_it_serves(self) -> None:
        # Home Assistant decides the direction of pairing from this: port 0
        # means "waits to be polled", which is what the T560 tablet is.
        text = _read(PAIRED)
        match = re.search(
            r"- service: _media-controller\n\s+protocol: _tcp\n\s+port: (\d+)",
            text,
        )
        assert match is not None, "the mDNS service record was not found"
        self.assertEqual(match.group(1), "80")

    def test_polling_stops_when_no_address_is_known(self) -> None:
        # A factory device has no address to poll, and a request-per-three-
        # seconds against nothing would be a log line per three seconds.
        self.assertIn("if (id(ha_base).empty()) {", _read(PAIRED))


class InterfacePackageTests(unittest.TestCase):
    """Verify that the shared interface names no address at all."""

    def test_only_the_asset_substitution_is_used(self) -> None:
        used = set(re.findall(r"\$\{([a-z_0-9]+)\}", _read(UI)))
        self.assertEqual(used, {"asset_base_url"})

    def test_the_album_art_placeholder_is_unroutable(self) -> None:
        # online_image needs a URL at compile time and the real one is written
        # at runtime. 0.0.0.0 fails loudly rather than reaching a stranger.
        self.assertEqual(_read(UI).count('url: "http://0.0.0.0/"'), 2)


class InstallerSiteTests(unittest.TestCase):
    """Verify the page that flashes the image."""

    def test_the_page_exists(self) -> None:
        self.assertTrue((INSTALLER / "index.html").is_file())

    def test_the_page_reads_a_versioned_manifest(self) -> None:
        text = _read(INSTALLER / "index.html")
        self.assertIn("versions.json", text)
        self.assertIn("esp-web-install-button", text)

    def test_the_page_checks_the_browser(self) -> None:
        text = _read(INSTALLER / "index.html")
        self.assertIn('"serial" in navigator', text)
        self.assertIn("isSecureContext", text)

    def test_the_page_says_what_it_needs_to(self) -> None:
        text = _read(INSTALLER / "index.html")
        for phrase in (
            "ESP32-S3-4848S040",
            "BOOT",
            "RESET",
            "Chrome",
            "Edge",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_no_build_output_is_committed(self) -> None:
        # The binary, its manifest and the version index are produced by the
        # workflow; a copy in the repository would go stale the first time the
        # firmware changed. Checked against .gitignore rather than the working
        # tree, because a maintainer who has just run the packaging script has
        # them on disk and is not doing anything wrong.
        ignored = _read(REPO / ".gitignore")
        self.assertIn("installer/firmware/", ignored)
        self.assertIn("installer/versions.json", ignored)


class ImageScanTests(unittest.TestCase):
    """Verify the scan that stands between a build and a published binary."""

    def test_a_clean_image_passes(self) -> None:
        self.assertEqual(make_web_installer.check_image(b"\x00" * 4096), [])

    def test_an_address_is_caught(self) -> None:
        problems = make_web_installer.check_image(
            b"junk http://homeassistant.local:8123 junk"
        )
        self.assertEqual(len(problems), 1)

    def test_a_token_is_caught(self) -> None:
        problems = make_web_installer.check_image(
            b"\x00eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhYmMifQ.c2ln\x00"
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("token", problems[0])

    def test_a_validation_wrapper_is_caught(self) -> None:
        # If this ever fires, a continuous-integration wrapper was compiled
        # and published instead of the factory entrypoint.
        self.assertNotEqual(
            make_web_installer.check_image(b"ci-validation-password"), []
        )

    def test_the_version_is_read_from_the_firmware(self) -> None:
        self.assertRegex(make_web_installer.firmware_version(), r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
