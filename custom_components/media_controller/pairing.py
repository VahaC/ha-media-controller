"""The rules a pairing has to satisfy before a token is handed over.

This module deliberately has no Home Assistant imports, so the part that
decides whether a panel may collect a token can be tested without a Home
Assistant runtime. The HTTP endpoint that uses it lives in provision.py.

An approval moves through states rather than existing or not, because the
person and the panel now meet in the middle: the code is typed while the
panel is being added, and the token can only travel once the config entry
that owns it exists. Confirming and collecting are therefore two moments,
and the flow that adds the panel waits for the first one before asking
anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import logging
import secrets
import time

_LOGGER = logging.getLogger(__name__)

# Long enough to walk to the tablet and read its screen, short enough that an
# approved pairing does not stay open.
PAIRING_TIMEOUT = 300.0
MAX_ATTEMPTS = 5
CODE_DIGITS = 6

STATUS_PAIRING_REQUIRED = "pairing_required"
STATUS_PAIRING_PENDING = "pairing_pending"
STATUS_ALREADY_PAIRED = "already_paired"
STATUS_INVALID_CODE = "invalid_code"
STATUS_UNKNOWN_PANEL = "unknown_panel"

# What one approval is doing right now.
STATE_ARMED = "armed"
STATE_CONFIRMED = "confirmed"
STATE_COLLECTED = "collected"
STATE_REJECTED = "rejected"

# The states in which an approval is still open for that panel.
OPEN_STATES = (STATE_ARMED, STATE_CONFIRMED)


def generate_code() -> str:
    """Return a fresh pairing code."""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def is_valid_code(code: str) -> bool:
    """Return whether a typed code has the shape a panel would show."""
    return len(code) == CODE_DIGITS and code.isdigit()


@dataclass(slots=True)
class Pairing:
    """One approved pairing and how far it has got."""

    code: str
    token: str
    expires_at: float
    state: str = STATE_ARMED
    attempts: int = 0


@dataclass(slots=True)
class PairingStore:
    """Every pairing approved but not yet finished.

    Keyed by panel ID, one at a time: a panel is a single device, and a newer
    approval always replaces an older one. A finished record is kept until it
    expires so that the flow which approved it can report what happened.
    """

    pairings: dict[str, Pairing] = field(default_factory=dict)

    @staticmethod
    def _now(now: float | None) -> float:
        """Return the timestamp to judge expiry against."""
        return time.monotonic() if now is None else now

    def _active(self, panel_id: str, now: float | None) -> Pairing | None:
        """Return the record of a panel, dropping it once it has expired."""
        pairing = self.pairings.get(panel_id)
        if pairing is None:
            return None
        if self._now(now) >= pairing.expires_at:
            del self.pairings[panel_id]
            return None
        return pairing

    def arm(
        self,
        panel_id: str,
        code: str,
        token: str = "",
        *,
        now: float | None = None,
    ) -> None:
        """Approve one pairing, replacing any earlier one for that panel.

        The token is optional because the flow that adds a panel has none yet:
        it mints one only when the entry that owns it is about to exist, so an
        abandoned setup leaves nothing usable behind.
        """
        self.pairings[panel_id] = Pairing(
            code=code,
            token=token,
            expires_at=self._now(now) + PAIRING_TIMEOUT,
        )

    def attach_token(
        self,
        panel_id: str,
        token: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Give a confirmed pairing the token it may hand over."""
        pairing = self._active(panel_id, now)
        if pairing is None or pairing.state != STATE_CONFIRMED:
            return False
        pairing.token = token
        return True

    def state(self, panel_id: str, *, now: float | None = None) -> str | None:
        """Return what this panel's pairing is doing, or None if it has none."""
        pairing = self._active(panel_id, now)
        return None if pairing is None else pairing.state

    def is_armed(self, panel_id: str, *, now: float | None = None) -> bool:
        """Return whether an approval is still open for this panel."""
        return self.state(panel_id, now=now) in OPEN_STATES

    def confirm(
        self,
        panel_id: str,
        code: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Record that the panel presented the right code.

        The token is not handed over here: during setup the config entry that
        owns it does not exist yet. Every correct code extends the window, so
        a panel that keeps polling while the rest of the form is filled in
        never runs out of time.
        """
        pairing = self._active(panel_id, now)
        if pairing is None or pairing.state not in OPEN_STATES:
            return False

        if not hmac.compare_digest(pairing.code, code):
            pairing.attempts += 1
            if pairing.attempts >= MAX_ATTEMPTS:
                _LOGGER.warning(
                    "Too many wrong pairing codes for panel %s; "
                    "the approval was cancelled",
                    panel_id,
                )
                pairing.state = STATE_REJECTED
                pairing.token = ""
            return False

        pairing.state = STATE_CONFIRMED
        pairing.expires_at = self._now(now) + PAIRING_TIMEOUT
        return True

    def collect(
        self,
        panel_id: str,
        *,
        now: float | None = None,
    ) -> str | None:
        """Return the token of a confirmed pairing, once.

        Nothing is returned while no token is attached: the panel is simply
        told to keep asking until the setup that mints one is finished.
        """
        pairing = self._active(panel_id, now)
        if (
            pairing is None
            or pairing.state != STATE_CONFIRMED
            or not pairing.token
        ):
            return None

        token, pairing.token = pairing.token, ""
        pairing.state = STATE_COLLECTED
        return token

    def claim(
        self,
        panel_id: str,
        code: str,
        *,
        now: float | None = None,
    ) -> str | None:
        """Confirm and collect in one step, for the right code, once."""
        if not self.confirm(panel_id, code, now=now):
            return None
        return self.collect(panel_id, now=now)

    def discard(self, panel_id: str) -> None:
        """Drop an approval, for a panel that is being removed."""
        self.pairings.pop(panel_id, None)
