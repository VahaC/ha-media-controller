"""Tests for the card-artwork catalog the integration publishes.

The endpoints around these rules are ordinary HTTP plumbing and the ownership
check they reuse is the status endpoint's, already covered. What is worth
testing is what the catalog promises:

* an identifier is a **key and never a path**, so no spelling of `..` can
  become a filename;
* the catalog is **not the order**, so reordering it moves nobody's icon;
* the pre-rendered variant is exactly the shape it claims, because the
  firmware points `lv_image_dsc_t` at it without decoding anything.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

INTEGRATION = (
    Path(__file__).parents[1] / "custom_components" / "media_controller"
)
MODULE_PATH = INTEGRATION / "icon_catalog.py"
SPEC = importlib.util.spec_from_file_location(
    "media_controller_icon_catalog", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
icon_catalog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = icon_catalog
SPEC.loader.exec_module(icon_catalog)


class IdentifierTests(unittest.TestCase):
    """What may be an icon identifier, and what may not."""

    def test_every_published_identifier_is_usable(self) -> None:
        for icon_id in icon_catalog.icon_ids():
            with self.subTest(icon_id=icon_id):
                self.assertIsNotNone(icon_catalog.find_icon(icon_id))
                self.assertTrue(icon_catalog.is_known_icon(icon_id))

    def test_the_two_clients_built_in_names_are_all_published(self) -> None:
        """Nothing anybody has already chosen loses its picture.

        These are the names the ESP32 firmware and the T560 panel carried
        compiled in, and the names their layout documents already contain. The
        migration for an existing layout is that there is none, and this is
        what keeps it that way.
        """
        for icon_id in (
            "light-1",
            "light-2",
            "desk-lamp",
            "desk-led-strip",
            "fan",
            "ac",
            "blind",
            "weather",
        ):
            with self.subTest(icon_id=icon_id):
                self.assertTrue(icon_catalog.is_known_icon(icon_id))

    def test_a_path_is_never_an_identifier(self) -> None:
        for value in (
            "../secrets.yaml",
            "..%2fsecrets.yaml",
            "../../custom_components/media_controller/const.py",
            "icons/../../secrets",
            "/etc/passwd",
            "fan/../../fan",
            "fan.png",
            ".",
            "..",
            "",
            "-fan",
            "FAN",
            "fan ",
            "f" * 33,
        ):
            with self.subTest(value=value):
                self.assertIsNone(icon_catalog.find_icon(value))
                self.assertFalse(icon_catalog.is_known_icon(value))

    def test_a_non_string_is_never_an_identifier(self) -> None:
        for value in (None, 3, True, ["fan"], {"id": "fan"}):
            with self.subTest(value=value):
                self.assertIsNone(icon_catalog.find_icon(value))

    def test_normalizing_falls_back_to_automatic(self) -> None:
        """An identifier the catalog dropped reads as automatic, not as an error.

        It is what reads values off disk as well as off the wire: an icon
        removed from the catalog must leave its card drawing the domain's own
        artwork, never stop a panel from loading.
        """
        self.assertEqual(icon_catalog.normalize_icon_id("fan"), "fan")
        self.assertEqual(icon_catalog.normalize_icon_id("  fan  "), "fan")
        self.assertEqual(icon_catalog.normalize_icon_id(""), "")
        self.assertEqual(icon_catalog.normalize_icon_id(None), "")
        self.assertEqual(icon_catalog.normalize_icon_id("gone"), "")
        self.assertEqual(icon_catalog.normalize_icon_id("../gone"), "")


class VariantTests(unittest.TestCase):
    """Which sizes a client may ask for."""

    def test_only_published_sizes_are_accepted(self) -> None:
        self.assertTrue(icon_catalog.is_supported_size(40))
        self.assertTrue(icon_catalog.is_supported_size("40"))

    def test_an_open_size_parameter_is_refused(self) -> None:
        for value in (0, -40, 41, 4096, "40.0", "0x28", "", None, True, "png"):
            with self.subTest(value=value):
                self.assertFalse(icon_catalog.is_supported_size(value))

    def test_the_esp32_header_names_the_size_twice(self) -> None:
        header = icon_catalog.esp32_header(40)
        self.assertEqual(len(header), icon_catalog.ESP32_HEADER_BYTES)
        self.assertTrue(header.startswith(icon_catalog.ESP32_MAGIC))
        # Little-endian, twice: a firmware that reads only the first pair
        # still learns what it was sent.
        self.assertEqual(header[4:6], b"\x28\x00")
        self.assertEqual(header[6:8], b"\x28\x00")

    def test_the_variant_length_is_exact(self) -> None:
        """A client refuses a truncated download by length alone."""
        self.assertEqual(
            icon_catalog.esp32_variant_bytes(40), 8 + 40 * 40 * 4
        )
        self.assertEqual(
            icon_catalog.ESP32_VARIANT_BYTES,
            icon_catalog.esp32_variant_bytes(icon_catalog.ESP32_ICON_SIZE),
        )


class CatalogTests(unittest.TestCase):
    """What the catalog document says, and what it must not."""

    def test_catalog_fits_maintained_panel_limits(self) -> None:
        payload = icon_catalog.catalog_payload()
        self.assertLessEqual(len(payload["icons"]), 512)
        self.assertLessEqual(len(json.dumps(payload).encode("utf-8")), 49152)

    def test_the_document_carries_no_image_data(self) -> None:
        """It is fetched on a schedule, so it has to stay small."""
        payload = icon_catalog.catalog_payload()
        for row in payload["icons"]:
            self.assertEqual(set(row), {"id", "label"})

    def test_the_document_names_the_identifiers_and_the_sizes(self) -> None:
        payload = icon_catalog.catalog_payload()
        self.assertEqual(
            [row["id"] for row in payload["icons"]],
            list(icon_catalog.icon_ids()),
        )
        self.assertEqual(payload["sizes"], [40])
        self.assertEqual(
            payload["esp32_bytes"], icon_catalog.ESP32_VARIANT_BYTES
        )

    def test_the_revision_is_stable_and_moves_with_the_catalog(self) -> None:
        first = icon_catalog.catalog_revision()
        self.assertEqual(first, icon_catalog.catalog_revision())

        original = icon_catalog.ICONS
        try:
            icon_catalog.ICONS = original + (
                icon_catalog.CatalogIcon("kettle", "Kettle"),
            )
            self.assertNotEqual(first, icon_catalog.catalog_revision())
        finally:
            icon_catalog.ICONS = original
        self.assertEqual(first, icon_catalog.catalog_revision())

    def test_reordering_the_catalog_moves_no_identifier(self) -> None:
        """The point of the whole exercise.

        A card used to store a 1-based index into an array compiled into the
        firmware, so reordering that array moved everybody's icons. Nothing
        here depends on a position.
        """
        original = icon_catalog.ICONS
        try:
            icon_catalog.ICONS = tuple(reversed(original))
            for icon in original:
                with self.subTest(icon_id=icon.icon_id):
                    found = icon_catalog.find_icon(icon.icon_id)
                    self.assertIsNotNone(found)
                    assert found is not None
                    self.assertEqual(found.icon_id, icon.icon_id)
        finally:
            icon_catalog.ICONS = original


class AssetTests(unittest.TestCase):
    """The files the catalog names, as they are shipped."""

    def test_a_filename_is_built_from_the_record_only(self) -> None:
        icon = icon_catalog.find_icon("desk-lamp")
        assert icon is not None
        self.assertEqual(icon.png_name, "desk-lamp.png")
        self.assertEqual(icon.esp32_name(40), "desk-lamp-40.bin")

    def test_every_published_icon_ships_both_variants(self) -> None:
        root = INTEGRATION / icon_catalog.ASSET_DIRECTORY
        for icon in icon_catalog.ICONS:
            with self.subTest(icon_id=icon.icon_id):
                self.assertTrue((root / icon.png_name).is_file())
                for size in icon_catalog.SUPPORTED_SIZES:
                    self.assertTrue(
                        (
                            root
                            / icon_catalog.ESP32_ASSET_DIRECTORY
                            / icon.esp32_name(size)
                        ).is_file()
                    )

    def test_every_pre_rendered_variant_is_exactly_its_declared_shape(
        self,
    ) -> None:
        """The firmware points LVGL at these bytes without decoding them.

        A file of the wrong length, or with the wrong header, is a buffer of
        the wrong shape handed to a renderer, so it is worth proving here
        rather than discovering on a device.
        """
        root = (
            INTEGRATION
            / icon_catalog.ASSET_DIRECTORY
            / icon_catalog.ESP32_ASSET_DIRECTORY
        )
        for icon in icon_catalog.ICONS:
            for size in icon_catalog.SUPPORTED_SIZES:
                with self.subTest(icon_id=icon.icon_id, size=size):
                    payload = (root / icon.esp32_name(size)).read_bytes()
                    self.assertEqual(
                        len(payload), icon_catalog.esp32_variant_bytes(size)
                    )
                    self.assertEqual(
                        payload[: icon_catalog.ESP32_HEADER_BYTES],
                        icon_catalog.esp32_header(size),
                    )


if __name__ == "__main__":
    unittest.main()
