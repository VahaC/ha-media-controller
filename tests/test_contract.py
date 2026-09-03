"""Tests for the rule that decides one panel is running a stale build.

Also for the thing that rule is worthless without: the number itself agreeing
across the three places that hold it — this document's own constant, the
tablet's, and `docs/CONTRACT.md`. A constant that has drifted from the
document is worse than no constant at all, because both halves compare
against it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest

REPO = Path(__file__).parents[1]
MODULE_PATH = (
    REPO / "custom_components" / "media_controller" / "contract.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_contract", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)

CURRENT = contract.CONTRACT_VERSION
GRACE = contract.SILENT_PANEL_GRACE_SECONDS


def verdict(
    *,
    reported_version: int = 0,
    heard_this_run: bool = False,
    heard_before: bool = False,
    seconds_since_load: float = GRACE + 1.0,
) -> str:
    """Ask for a verdict, defaulting to the case this feature exists for."""
    return contract.panel_contract_verdict(
        reported_version=reported_version,
        heard_this_run=heard_this_run,
        heard_before=heard_before,
        seconds_since_load=seconds_since_load,
    )


class VersionAgreementTests(unittest.TestCase):
    """The three copies of the contract version must be the same number."""

    def test_the_document_names_the_version_this_build_implements(
        self,
    ) -> None:
        text = (REPO / "docs" / "CONTRACT.md").read_text(encoding="utf-8")
        match = re.search(r"^Contract version: \*\*(\d+)\*\*", text, re.M)
        self.assertIsNotNone(match, "docs/CONTRACT.md names no version")
        self.assertEqual(int(match.group(1)), CURRENT)

    def test_the_tablet_speaks_the_same_version(self) -> None:
        header = (
            REPO / "clients" / "t560" / "src" / "app_config.h"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"^#define T560_PANEL_CONTRACT_VERSION (\d+)", header, re.M
        )
        self.assertIsNotNone(match, "app_config.h names no contract version")
        self.assertEqual(int(match.group(1)), CURRENT)

    def test_version_6_is_where_the_registry_arrived(self) -> None:
        """Guards against the number moving without the document moving."""
        self.assertGreaterEqual(CURRENT, 6)


class ReadTests(unittest.TestCase):
    """Verify that a claimed contract version is read and not trusted."""

    def test_a_usable_version_is_read(self) -> None:
        self.assertEqual(contract.read_contract_version(4), 4)
        self.assertEqual(contract.read_contract_version(4.0), 4)

    def test_anything_unusable_reads_as_unknown(self) -> None:
        for value in (None, "4", True, False, 0, -1, [], {}):
            with self.subTest(value=value):
                self.assertEqual(
                    contract.read_contract_version(value),
                    contract.CONTRACT_VERSION_UNKNOWN,
                )


class ReportedPanelTests(unittest.TestCase):
    """A panel that reports is judged on what it said, never on silence."""

    def test_a_current_panel_is_fine(self) -> None:
        self.assertEqual(
            verdict(reported_version=CURRENT, heard_this_run=True),
            contract.PANEL_CONTRACT_OK,
        )

    def test_a_newer_panel_is_fine(self) -> None:
        """The other direction is the panel's to report, not this one's."""
        self.assertEqual(
            verdict(reported_version=CURRENT + 1, heard_this_run=True),
            contract.PANEL_CONTRACT_OK,
        )

    def test_an_older_panel_is_outdated(self) -> None:
        self.assertEqual(
            verdict(reported_version=CURRENT - 1, heard_this_run=True),
            contract.PANEL_CONTRACT_OUTDATED,
        )

    def test_a_panel_that_names_no_version_is_outdated(self) -> None:
        """It reports, so it is running; it just predates the field."""
        self.assertEqual(
            verdict(reported_version=0, heard_this_run=True),
            contract.PANEL_CONTRACT_OUTDATED,
        )

    def test_a_report_outweighs_every_heuristic(self) -> None:
        self.assertEqual(
            verdict(
                reported_version=CURRENT,
                heard_this_run=True,
                heard_before=False,
                seconds_since_load=0.0,
            ),
            contract.PANEL_CONTRACT_OK,
        )


class SilentPanelTests(unittest.TestCase):
    """A panel that has said nothing yet, which is the hard case."""

    def test_a_panel_that_has_never_reported_at_all_is_outdated(self) -> None:
        self.assertEqual(verdict(), contract.PANEL_CONTRACT_OUTDATED)

    def test_a_panel_that_reported_before_is_only_switched_off(self) -> None:
        # It carries a software version from an earlier run, so it does
        # report; its contract version is simply not known right now.
        self.assertEqual(
            verdict(heard_before=True),
            contract.PANEL_CONTRACT_UNDECIDED,
        )

    def test_a_panel_still_inside_the_grace_period_is_undecided(self) -> None:
        self.assertEqual(
            verdict(seconds_since_load=GRACE - 1.0),
            contract.PANEL_CONTRACT_UNDECIDED,
        )

    def test_the_grace_period_ends(self) -> None:
        self.assertEqual(
            verdict(seconds_since_load=GRACE),
            contract.PANEL_CONTRACT_OUTDATED,
        )

    def test_a_panel_that_reported_before_stays_undecided_forever(
        self,
    ) -> None:
        """Silence never becomes evidence for a panel known to report."""
        self.assertEqual(
            verdict(heard_before=True, seconds_since_load=GRACE * 100),
            contract.PANEL_CONTRACT_UNDECIDED,
        )


if __name__ == "__main__":
    unittest.main()
