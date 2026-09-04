"""Regression test for ArduinoJson range-for over a temporary.

GCC with -Wdangling-reference (ESP-IDF 5.5 / GCC 13+) warns on:

    for (JsonVariant c : element["controls"].as<JsonArray>())
    for (JsonObject e : root["cards"].as<JsonArray>())

because .as<T>() returns a temporary wrapper and the range-for holds a
reference to it. The wrapper itself is cheap and the backing store lives
in the JsonDocument, so the loop works, but the warning hides real
lifetime bugs. The rule is: bind the array to a named local first, then
range over the name. This test scans the firmware components for the
inline-temporary form so the warning cannot be reintroduced.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).parents[1]
COMPONENTS = REPO / "components"

# A range-for whose collection expression calls .as<T>() inline, e.g.
#   for (JsonObject element : root["cards"].as<JsonArray>())
FOR_OVER_TEMPORARY = re.compile(
    r"for\s*\([^;:]*:\s*[^;]*\.as\s*<\s*\w+\s*>\s*\(\s*\)",
    re.MULTILINE,
)


def _code_without_comments(text: str) -> str:
    """Strip block comments, line comments, and string literals."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return text


class JsonRangeForStyleTests(unittest.TestCase):
    """The firmware must not range-for over an ArduinoJson temporary."""

    def test_no_range_for_over_as_temporary(self) -> None:
        offenders: list[str] = []
        sources = sorted(COMPONENTS.rglob("*.cpp")) + sorted(
            COMPONENTS.rglob("*.h")
        )
        self.assertTrue(sources, "no component sources found to scan")
        for path in sources:
            code = _code_without_comments(
                path.read_text(encoding="utf-8")
            )
            for match in FOR_OVER_TEMPORARY.finditer(code):
                line = code.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}")
        self.assertEqual(
            offenders,
            [],
            "range-for over .as<T>() temporary (bind to a named "
            "JsonArray first): " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
