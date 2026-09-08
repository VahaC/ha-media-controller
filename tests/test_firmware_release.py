"""The rules that decide whether a panel is offered a firmware.

Everything here runs without a Home Assistant runtime, because
`firmware_release.py` deliberately imports nothing from one. Two separate
things are covered:

* **which build, if any, a panel should be offered.** The index is a file on
  a public web page, so it is treated as untrusted input throughout: a
  malformed entry must mean "no update", never an exception, and never a
  different build than the one asked for;
* **what a download nonce permits.** It is the only thing standing in front
  of the image route, because ESPHome's update client cannot send an
  `Authorization` header, so its single use and its expiry are load-bearing
  rather than tidy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

# Loaded by path, like every other test of a module that has no Home
# Assistant imports: importing it through the package would pull in
# `__init__.py`, which needs a Home Assistant runtime this test does not.
REPO = Path(__file__).parents[1]
MODULE_PATH = (
    REPO / "custom_components" / "media_controller" / "firmware_release.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_firmware_release", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
firmware_release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = firmware_release
SPEC.loader.exec_module(firmware_release)

MAX_IMAGE_BYTES = firmware_release.MAX_IMAGE_BYTES
MIN_OTA_CONTRACT_VERSION = firmware_release.MIN_OTA_CONTRACT_VERSION
NONCE_LENGTH = firmware_release.NONCE_LENGTH
NONCE_TTL_SECONDS = firmware_release.NONCE_TTL_SECONDS
FirmwareRelease = firmware_release.FirmwareRelease
NonceStore = firmware_release.NonceStore
can_update_over_the_air = firmware_release.can_update_over_the_air
is_newer = firmware_release.is_newer
read_index = firmware_release.read_index
read_version = firmware_release.read_version
select_release = firmware_release.select_release

SHA = "a" * 64
MD5 = "b" * 32


def build(
    version: str = "0.6.0",
    contract: int = 8,
    size: int = 2_000_000,
    **overrides: object,
) -> dict:
    """Return one index entry, in the shape the publishing script writes."""
    entry = {
        "version": version,
        "contract_version": contract,
        "manifest": f"firmware/{version}/manifest.json",
        "ota": {
            "path": f"firmware/{version}/media-controller-paired.ota.bin",
            "size": size,
            "sha256": SHA,
            "md5": MD5,
        },
    }
    entry.update(overrides)
    return entry


def index(*entries: dict) -> dict:
    """Return a release index document around some entries."""
    return {"latest": "0.6.0", "builds": list(entries)}


class VersionTests(unittest.TestCase):
    """Reading and comparing the only version format that is released."""

    def test_dotted_numbers_are_read(self) -> None:
        self.assertEqual(read_version("0.6.0"), (0, 6, 0))
        self.assertEqual(read_version(" 1.2 "), (1, 2))

    def test_anything_else_is_refused(self) -> None:
        for value in ("", "0.6.0-dev", "v0.6.0", "latest", "0..1", None, 6):
            with self.subTest(value=value):
                self.assertIsNone(read_version(value))

    def test_a_newer_build_is_newer(self) -> None:
        self.assertTrue(is_newer("0.6.0", "0.5.0"))
        self.assertTrue(is_newer("0.5.1", "0.5.0"))
        self.assertTrue(is_newer("1.0", "0.9.9"))

    def test_the_same_build_written_two_ways_is_not_newer(self) -> None:
        self.assertFalse(is_newer("0.6", "0.6.0"))
        self.assertFalse(is_newer("0.6.0", "0.6"))

    def test_an_unreadable_version_is_never_newer(self) -> None:
        # A panel that has never reported has no version at all, and offering
        # it a firmware on no evidence could install something older than
        # what is already on the device.
        self.assertFalse(is_newer("0.6.0", ""))
        self.assertFalse(is_newer("", "0.5.0"))
        self.assertFalse(is_newer("0.6.0", "garbage"))


class IndexTests(unittest.TestCase):
    """Reading a document downloaded from a public page."""

    def test_a_published_index_is_read(self) -> None:
        releases = read_index(index(build()))
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0].version, "0.6.0")
        self.assertEqual(releases[0].contract_version, 8)
        self.assertEqual(releases[0].sha256, SHA)

    def test_releases_come_back_newest_first(self) -> None:
        releases = read_index(
            index(build("0.5.1"), build("0.7.0"), build("0.6.0"))
        )
        self.assertEqual(
            [release.version for release in releases],
            ["0.7.0", "0.6.0", "0.5.1"],
        )

    def test_a_build_with_no_ota_block_is_not_installable(self) -> None:
        # Every index written before over-the-air updates existed looks like
        # this, and it still describes a build the web installer can flash.
        entry = build()
        del entry["ota"]
        self.assertEqual(read_index(index(entry)), ())

    def test_one_bad_entry_does_not_hide_the_others(self) -> None:
        releases = read_index(index({"version": "0.7.0"}, build("0.6.0")))
        self.assertEqual([release.version for release in releases], ["0.6.0"])

    def test_a_malformed_document_means_no_update(self) -> None:
        for document in (None, [], "", {}, {"builds": "0.6.0"}):
            with self.subTest(document=document):
                self.assertEqual(read_index(document), ())

    def test_an_image_larger_than_a_slot_is_refused(self) -> None:
        # There would be nowhere to write it, and finding that out after two
        # megabytes have moved is finding it out too late.
        self.assertEqual(read_index(index(build(size=MAX_IMAGE_BYTES + 1))), ())

    def test_an_implausibly_small_image_is_refused(self) -> None:
        self.assertEqual(read_index(index(build(size=1024))), ())

    def test_a_digest_that_is_not_one_is_refused(self) -> None:
        for digest in ("", "zz" * 32, SHA[:-1], 42):
            entry = build()
            entry["ota"]["sha256"] = digest
            with self.subTest(digest=digest):
                self.assertEqual(read_index(index(entry)), ())

    def test_a_duplicate_version_is_taken_once(self) -> None:
        releases = read_index(index(build("0.6.0"), build("0.6.0")))
        self.assertEqual(len(releases), 1)


class SelectionTests(unittest.TestCase):
    """Which of the published builds a particular panel is offered."""

    def offer(
        self,
        releases,
        installed: str = "0.5.1",
        panel_contract: int = 8,
        integration_contract: int = 8,
    ):
        return select_release(
            releases,
            installed_version=installed,
            panel_contract=panel_contract,
            integration_contract=integration_contract,
        )

    def test_the_newest_compatible_build_is_offered(self) -> None:
        releases = read_index(index(build("0.6.0"), build("0.7.0")))
        offer = self.offer(releases)
        assert offer is not None
        self.assertEqual(offer.version, "0.7.0")

    def test_a_panel_already_on_the_newest_build_is_offered_nothing(self) -> None:
        releases = read_index(index(build("0.6.0")))
        self.assertIsNone(self.offer(releases, installed="0.6.0"))

    def test_a_panel_ahead_of_the_index_is_offered_nothing(self) -> None:
        releases = read_index(index(build("0.6.0")))
        self.assertIsNone(self.offer(releases, installed="0.7.0"))

    def test_a_build_needing_a_newer_integration_is_held_back(self) -> None:
        # It would install perfectly and then ignore half of what Home
        # Assistant sends it. The upgrade order is the integration first.
        releases = read_index(index(build("0.7.0", contract=9)))
        self.assertIsNone(self.offer(releases, integration_contract=8))

    def test_the_newest_build_the_integration_understands_is_offered(self) -> None:
        releases = read_index(
            index(build("0.7.0", contract=9), build("0.6.0", contract=8))
        )
        offer = self.offer(releases, integration_contract=8)
        assert offer is not None
        self.assertEqual(offer.version, "0.6.0")

    def test_a_panel_from_before_the_update_client_is_offered_nothing(self) -> None:
        # Firmware 0.5.0 has no update client of any kind: there is nothing
        # in it to tell. It has to be moved forward once over USB, and the
        # repair issue is what says so.
        releases = read_index(index(build("0.6.0")))
        self.assertIsNone(
            self.offer(
                releases,
                installed="0.5.0",
                panel_contract=MIN_OTA_CONTRACT_VERSION - 1,
            )
        )

    def test_a_panel_that_has_never_reported_is_offered_nothing(self) -> None:
        releases = read_index(index(build("0.6.0")))
        self.assertIsNone(self.offer(releases, installed="", panel_contract=0))

    def test_the_over_the_air_rule_is_a_named_rule(self) -> None:
        self.assertFalse(can_update_over_the_air(MIN_OTA_CONTRACT_VERSION - 1))
        self.assertTrue(can_update_over_the_air(MIN_OTA_CONTRACT_VERSION))
        self.assertTrue(can_update_over_the_air(MIN_OTA_CONTRACT_VERSION + 1))

    def test_an_empty_index_offers_nothing(self) -> None:
        self.assertIsNone(self.offer(()))


class NonceTests(unittest.TestCase):
    """The single thing standing in front of the unauthenticated image route."""

    def test_a_nonce_is_accepted_once(self) -> None:
        store = NonceStore()
        token = store.issue("aabbcc", "0.6.0", now=0.0)
        permitted = store.consume(token, now=1.0)
        assert permitted is not None
        self.assertEqual(permitted.panel_id, "aabbcc")
        self.assertEqual(permitted.version, "0.6.0")

    def test_a_nonce_is_not_accepted_twice(self) -> None:
        store = NonceStore()
        token = store.issue("aabbcc", "0.6.0", now=0.0)
        self.assertIsNotNone(store.consume(token, now=1.0))
        self.assertIsNone(store.consume(token, now=2.0))

    def test_a_nonce_expires(self) -> None:
        store = NonceStore()
        token = store.issue("aabbcc", "0.6.0", now=0.0)
        self.assertIsNone(store.consume(token, now=NONCE_TTL_SECONDS + 1.0))

    def test_an_unknown_nonce_is_refused(self) -> None:
        store = NonceStore()
        store.issue("aabbcc", "0.6.0", now=0.0)
        self.assertIsNone(store.consume("f" * NONCE_LENGTH, now=1.0))

    def test_a_value_of_the_wrong_shape_is_refused(self) -> None:
        store = NonceStore()
        store.issue("aabbcc", "0.6.0", now=0.0)
        for token in ("", "abc", "f" * (NONCE_LENGTH + 1), None, 12):
            with self.subTest(token=token):
                self.assertIsNone(store.consume(token, now=1.0))

    def test_a_panel_holds_one_nonce_at_a_time(self) -> None:
        # A panel that asks twice invalidates its own first answer, which is
        # what bounds this store by the number of paired panels rather than
        # by how often anything is asked for.
        store = NonceStore()
        first = store.issue("aabbcc", "0.6.0", now=0.0)
        second = store.issue("aabbcc", "0.6.0", now=1.0)
        self.assertNotEqual(first, second)
        self.assertIsNone(store.consume(first, now=2.0))
        self.assertIsNotNone(store.consume(second, now=2.0))

    def test_one_panel_does_not_invalidate_another(self) -> None:
        store = NonceStore()
        first = store.issue("aabbcc", "0.6.0", now=0.0)
        store.issue("ddeeff", "0.6.0", now=1.0)
        permitted = store.consume(first, now=2.0)
        assert permitted is not None
        self.assertEqual(permitted.panel_id, "aabbcc")

    def test_expired_nonces_do_not_accumulate(self) -> None:
        store = NonceStore()
        for panel in range(5):
            store.issue(f"panel{panel}", "0.6.0", now=0.0)
        store.issue("later", "0.6.0", now=NONCE_TTL_SECONDS + 1.0)
        self.assertEqual(len(store.nonces), 1)


class ReleaseShapeTests(unittest.TestCase):
    """The record itself, which is what everything above is built from."""

    def test_a_complete_release_is_usable(self) -> None:
        release = FirmwareRelease(
            version="0.6.0",
            contract_version=8,
            path="firmware/0.6.0/media-controller-paired.ota.bin",
            size=2_000_000,
            sha256=SHA,
            md5=MD5,
        )
        self.assertTrue(release.is_usable)

    def test_a_release_with_no_contract_version_is_not(self) -> None:
        release = FirmwareRelease(
            version="0.6.0",
            contract_version=0,
            path="x.bin",
            size=2_000_000,
            sha256=SHA,
            md5=MD5,
        )
        self.assertFalse(release.is_usable)


if __name__ == "__main__":
    unittest.main()
