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


class TwoPhasePairingTests(unittest.TestCase):
    """Verify confirming and collecting as the two moments they are.

    The person types the code before the panel's config entry exists, so the
    right code has to be recognised well before the token may travel.
    """

    def setUp(self) -> None:
        self.store = pairing.PairingStore()

    def test_states_walk_from_armed_to_collected(self) -> None:
        self.assertIsNone(self.store.state(PANEL))
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertEqual(self.store.state(PANEL, now=1.0), pairing.STATE_ARMED)

        self.assertTrue(self.store.confirm(PANEL, CODE, now=1.0))
        self.assertEqual(
            self.store.state(PANEL, now=1.0), pairing.STATE_CONFIRMED
        )
        # Confirming does not hand anything over; the flow only learns that
        # the right device is listening.
        self.assertTrue(self.store.is_armed(PANEL, now=1.0))

        self.assertEqual(self.store.collect(PANEL, now=2.0), TOKEN)
        self.assertEqual(
            self.store.state(PANEL, now=2.0), pairing.STATE_COLLECTED
        )
        self.assertFalse(self.store.is_armed(PANEL, now=2.0))

    def test_the_token_is_not_collected_twice(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.store.confirm(PANEL, CODE, now=1.0)
        self.assertEqual(self.store.collect(PANEL, now=1.0), TOKEN)
        self.assertIsNone(self.store.collect(PANEL, now=1.0))
        self.assertIsNone(self.store.claim(PANEL, CODE, now=1.0))

    def test_nothing_is_collected_before_the_code_arrives(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.assertIsNone(self.store.collect(PANEL, now=1.0))
        # And the approval is still open for the panel that has the code.
        self.assertEqual(self.store.claim(PANEL, CODE, now=1.0), TOKEN)

    def test_polling_with_the_right_code_keeps_the_window_open(self) -> None:
        # The panel polls every three seconds while the rest of the form is
        # filled in, so a slow setup must not expire underneath it.
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        elapsed = 0.0
        while elapsed < pairing.PAIRING_TIMEOUT * 2:
            elapsed += 3.0
            self.assertTrue(self.store.confirm(PANEL, CODE, now=elapsed))
        self.assertEqual(self.store.collect(PANEL, now=elapsed), TOKEN)

    def test_a_confirmed_approval_still_expires_when_left_alone(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        self.store.confirm(PANEL, CODE, now=1.0)
        self.assertIsNone(
            self.store.collect(PANEL, now=1.0 + pairing.PAIRING_TIMEOUT)
        )

    def test_rejection_is_reported_until_the_record_expires(self) -> None:
        # The flow that is waiting reads this to tell "wrong code" apart from
        # "the panel never answered".
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        for _ in range(pairing.MAX_ATTEMPTS):
            self.store.confirm(PANEL, "000000", now=1.0)
        self.assertEqual(
            self.store.state(PANEL, now=1.0), pairing.STATE_REJECTED
        )
        self.assertIsNone(self.store.collect(PANEL, now=1.0))
        self.assertIsNone(self.store.state(PANEL, now=pairing.PAIRING_TIMEOUT))

    def test_a_rejected_approval_keeps_no_token(self) -> None:
        self.store.arm(PANEL, CODE, TOKEN, now=0.0)
        for _ in range(pairing.MAX_ATTEMPTS):
            self.store.confirm(PANEL, "000000", now=1.0)
        self.assertEqual(self.store.pairings[PANEL].token, "")

    def test_confirming_an_unknown_panel_changes_nothing(self) -> None:
        self.assertFalse(self.store.confirm(PANEL, CODE, now=1.0))
        self.assertIsNone(self.store.state(PANEL, now=1.0))


class LateTokenTests(unittest.TestCase):
    """Verify an approval that is opened before a token exists.

    The flow that adds a panel arms the pairing with the typed code and mints
    the token only when the config entry is about to exist, so a setup that is
    closed halfway through leaves nothing usable in Home Assistant.
    """

    def setUp(self) -> None:
        self.store = pairing.PairingStore()

    def test_nothing_is_handed_over_until_a_token_is_attached(self) -> None:
        self.store.arm(PANEL, CODE, now=0.0)
        self.assertTrue(self.store.confirm(PANEL, CODE, now=1.0))
        self.assertIsNone(self.store.collect(PANEL, now=1.0))
        # Still confirmed, so the panel keeps its place in the queue.
        self.assertEqual(
            self.store.state(PANEL, now=1.0), pairing.STATE_CONFIRMED
        )

        self.assertTrue(self.store.attach_token(PANEL, TOKEN, now=2.0))
        self.assertEqual(self.store.collect(PANEL, now=2.0), TOKEN)
        self.assertIsNone(self.store.collect(PANEL, now=2.0))

    def test_a_token_is_not_attached_before_the_code_arrives(self) -> None:
        self.store.arm(PANEL, CODE, now=0.0)
        self.assertFalse(self.store.attach_token(PANEL, TOKEN, now=1.0))
        self.assertIsNone(self.store.claim(PANEL, CODE, now=1.0))

    def test_a_token_is_not_attached_to_a_cancelled_approval(self) -> None:
        self.store.arm(PANEL, CODE, now=0.0)
        for _ in range(pairing.MAX_ATTEMPTS):
            self.store.confirm(PANEL, "000000", now=1.0)
        self.assertFalse(self.store.attach_token(PANEL, TOKEN, now=1.0))

    def test_a_token_is_not_attached_to_an_expired_approval(self) -> None:
        self.store.arm(PANEL, CODE, now=0.0)
        self.store.confirm(PANEL, CODE, now=1.0)
        self.assertFalse(
            self.store.attach_token(
                PANEL, TOKEN, now=1.0 + pairing.PAIRING_TIMEOUT
            )
        )

    def test_an_unknown_panel_takes_no_token(self) -> None:
        self.assertFalse(self.store.attach_token(PANEL, TOKEN, now=1.0))


if __name__ == "__main__":
    unittest.main()
