"""Tests for the rules that guard the unauthenticated provisioning endpoint.

These decide whether a device on the network may collect an access token, so
they are worth more than the transport around them.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "media_controller"
    / "pairing.py"
)
SPEC = importlib.util.spec_from_file_location("media_controller_pairing", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
pairing = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pairing
SPEC.loader.exec_module(pairing)

PANEL = "t560_1a2b3c4d"
OTHER = "t560_9f8e7d6c"
CODE = "123456"
TOKEN = "a-long-lived-token"


class CodeTests(unittest.TestCase):
    """Verify the shape of a pairing code."""

    def test_generated_code_is_six_digits(self) -> None:
        for _ in range(50):
            code = pairing.generate_code()
            self.assertEqual(len(code), 6)
            self.assertTrue(code.isdigit())

    def test_leading_zeros_are_kept(self) -> None:
        # A code is compared as text, so "000123" must never become "123".
        self.assertTrue(
            all(len(pairing.generate_code()) == 6 for _ in range(200))
        )

    def test_validation(self) -> None:
        self.assertTrue(pairing.is_valid_code("000000"))
        self.assertFalse(pairing.is_valid_code("12345"))
        self.assertFalse(pairing.is_valid_code("1234567"))
        self.assertFalse(pairing.is_valid_code("12345a"))
        self.assertFalse(pairing.is_valid_code(""))


class PairingStoreTests(unittest.TestCase):
    """Verify when a token may be collected, and when it may not."""

    def setUp(self) -> None:
        self.store = pairing.PairingStore()

    def test_token_is_delivered_once(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertEqual(self.store.claim(PANEL, CODE, now=1.0), TOKEN)
        # A second poll, or anyone replaying the request, gets nothing.
        self.assertIsNone(self.store.claim(PANEL, CODE, now=2.0))

    def test_nothing_without_an_approval(self) -> None:
        self.assertIsNone(self.store.claim(PANEL, CODE))
        self.assertFalse(self.store.is_armed(PANEL))

    def test_wrong_code_is_refused(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertIsNone(self.store.claim(PANEL, "654321", now=1.0))
        # The approval survives a typo, so the right code still works.
        self.assertEqual(self.store.claim(PANEL, CODE, now=2.0), TOKEN)

    def test_guessing_cancels_the_approval(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        for attempt in range(pairing.MAX_ATTEMPTS):
            self.assertIsNone(
                self.store.claim(PANEL, "000000", now=float(attempt))
            )
        # Cancelled by the attempts, not by the clock: the time passed here is
        # well inside the timeout.
        self.assertFalse(self.store.is_armed(PANEL, now=10.0))
        self.assertIsNone(self.store.claim(PANEL, CODE, now=10.0))

    def test_approval_expires(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertIsNone(
            self.store.claim(PANEL, CODE, now=pairing.PAIRING_TIMEOUT)
        )
        self.assertFalse(self.store.is_armed(PANEL, now=pairing.PAIRING_TIMEOUT))

    def test_approval_is_valid_up_to_the_timeout(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertEqual(
            self.store.claim(PANEL, CODE, now=pairing.PAIRING_TIMEOUT - 0.1),
            TOKEN,
        )

    def test_panels_do_not_share_approvals(self) -> None:
        # The whole point of a per-device ID: one tablet's approval must never
        # hand a token to another.
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertIsNone(self.store.claim(OTHER, CODE, now=1.0))
        self.assertEqual(self.store.claim(PANEL, CODE, now=1.0), TOKEN)

    def test_two_panels_pair_independently(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.store.arm(OTHER, "654321", "other-token", now=0.0)
        self.assertEqual(self.store.claim(OTHER, "654321", now=1.0), "other-token")
        self.assertEqual(self.store.claim(PANEL, CODE, now=1.0), TOKEN)

    def test_failed_attempts_are_counted_per_panel(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.store.arm(OTHER, CODE, TOKEN, now=0.0)
        for _ in range(pairing.MAX_ATTEMPTS):
            self.store.claim(OTHER, "000000", now=1.0)
        self.assertFalse(self.store.is_armed(OTHER, now=1.0))
        self.assertTrue(self.store.is_armed(PANEL, now=1.0))

    def test_a_new_approval_replaces_the_old_one(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.store.arm(PANEL, "654321", "newer-token", now=0.0)
        self.assertIsNone(self.store.claim(PANEL, CODE, now=1.0))
        self.assertEqual(self.store.claim(PANEL, "654321", now=1.0), "newer-token")

    def test_discard_removes_an_approval(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.store.discard(PANEL)
        self.assertIsNone(self.store.claim(PANEL, CODE, now=1.0))
        # Discarding an unknown panel is not an error.
        self.store.discard("nothing")


if __name__ == "__main__":
    unittest.main()
