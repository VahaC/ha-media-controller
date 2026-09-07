"""Home Assistant refuses a URL inside a translation value.

`hassfest` fails the build with "the string should not contain URLs, please use
description placeholders instead", and it fails it in continuous integration
rather than here, several minutes after the change that caused it. The rule is
small enough to apply locally.

The reason for the rule is worth knowing, because it decides where an address
belongs: a translator would otherwise have to carry every URL through every
language, and an address that moved would have to be found in all of them. So
an address lives in `const.py` and reaches a string as a placeholder — see
`INSTALLER_URL`.

The pattern is hassfest's own, copied rather than imported: Home Assistant is
not a dependency of this test suite. It deliberately matches only a host with
an alphabetic top-level domain, which is why an example IP address in a form
description is allowed and `https://vahac.github.io/...` is not.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

REPO = Path(__file__).parents[1]
COMPONENT = REPO / "custom_components" / "media_controller"

# script/hassfest/translations.py, RE_URL.
RE_URL = re.compile(
    r"(((ftp|ftps|scp|http|https|mqtt|mqtts|socket|socks5):\/\/|www\.)"
    r"[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,5}(:[0-9]{1,5})?(\/.*)?)"
)

# The one place a translation value may not be checked. Service descriptions
# live under `services` and hassfest reads them from services.yaml, but the
# same rule applies to them, so nothing is skipped here.
TRANSLATION_FILES = (
    COMPONENT / "strings.json",
    COMPONENT / "translations" / "en.json",
)


def _values(document: object, path: str = "") -> list[tuple[str, str]]:
    """Return every string in the document, with the key path that reaches it."""
    if isinstance(document, str):
        return [(path, document)]
    if isinstance(document, dict):
        found: list[tuple[str, str]] = []
        for key, value in document.items():
            found += _values(value, f"{path}.{key}" if path else key)
        return found
    if isinstance(document, list):
        found = []
        for index, value in enumerate(document):
            found += _values(value, f"{path}[{index}]")
        return found
    return []


class TranslationUrlTests(unittest.TestCase):
    """Verify that no translation value carries an address."""

    def test_no_translation_value_contains_a_url(self) -> None:
        for path in TRANSLATION_FILES:
            document = json.loads(path.read_text(encoding="utf-8"))
            offenders = [
                (key, value)
                for key, value in _values(document)
                if RE_URL.search(value)
            ]
            with self.subTest(file=path.name):
                self.assertEqual(
                    offenders,
                    [],
                    "put the address in const.py and name it as a "
                    "description placeholder instead",
                )

    def test_the_installer_address_reaches_the_strings(self) -> None:
        # The other half of the rule: a placeholder nothing supplies renders
        # as the literal "{installer_url}" in front of a user.
        for path in TRANSLATION_FILES:
            document = json.loads(path.read_text(encoding="utf-8"))
            named = [
                key
                for key, value in _values(document)
                if "{installer_url}" in value
            ]
            with self.subTest(file=path.name):
                self.assertIn("config.step.panel.description", named)
                self.assertIn(
                    "issues.panel_contract_outdated_firmware.description",
                    named,
                )
                self.assertIn(
                    "issues.panel_never_reported_firmware.description", named
                )

        # Both places that render those strings have to pass it.
        flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        compatibility = (COMPONENT / "compatibility.py").read_text(
            encoding="utf-8"
        )
        for source in (flow, compatibility):
            self.assertIn('"installer_url": INSTALLER_URL', source)

    def test_the_regex_is_the_one_that_matters(self) -> None:
        # Guards the test itself: an example IP address in a form is allowed
        # and a published address is not, and the difference is the only
        # reason the first is still spelled out in a description.
        self.assertIsNone(RE_URL.search("http://192.168.1.10:8123"))
        self.assertIsNone(RE_URL.search("starting with http:// or https://."))
        self.assertIsNotNone(
            RE_URL.search("https://vahac.github.io/ha-media-controller/")
        )


if __name__ == "__main__":
    unittest.main()
