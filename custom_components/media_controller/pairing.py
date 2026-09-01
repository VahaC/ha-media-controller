"""The rules a pairing has to satisfy before a token is handed over.

This module deliberately has no Home Assistant imports, so the part that
decides whether a panel may collect a token can be tested without a Home
Assistant runtime. The HTTP endpoint that uses it lives in provision.py.
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
STATUS_INVALID_CODE = "invalid_code"
STATUS_UNKNOWN_PANEL = "unknown_panel"


def generate_code() -> str:
    """Return a fresh pairing code."""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def is_valid_code(code: str) -> bool:
    """Return whether a typed code has the shape a panel would show."""
    return len(code) == CODE_DIGITS and code.isdigit()


@dataclass(slots=True)
class ArmedPairing:
    """One approved pairing, waiting for the panel to collect its token."""

    code: str
    token: str
    expires_at: float
    attempts: int = 0


@dataclass(slots=True)
class PairingStore:
    """Every pairing approved but not yet collected.

    Keyed by panel ID, one at a time: a panel is a single device, and a newer
    approval always replaces an older one.
    """

    armed: dict[str, ArmedPairing] = field(default_factory=dict)

    @staticmethod
    def _now(now: float | None) -> float:
        """Return the timestamp to judge expiry against."""
        return time.monotonic() if now is None else now

    def arm(
        self,
        panel_id: str,
        code: str,
        token: str,
        *,
        now: float | None = None,
    ) -> None:
        """Approve one pairing, replacing any earlier one for that panel."""
        self.armed[panel_id] = ArmedPairing(
            code=code,
            token=token,
            expires_at=self._now(now) + PAIRING_TIMEOUT,
        )

    def is_armed(self, panel_id: str, *, now: float | None = None) -> bool:
        """Return whether an approval is still open for this panel."""
        pairing = self.armed.get(panel_id)
        if pairing is None:
            return False
        if self._now(now) >= pairing.expires_at:
            del self.armed[panel_id]
            return False
        return True

    def claim(
        self,
        panel_id: str,
        code: str,
        *,
        now: float | None = None,
    ) -> str | None:
        """Return the token once, for the right code, before it expires."""
        if not self.is_armed(panel_id, now=now):
            return None
        pairing = self.armed[panel_id]

        if not hmac.compare_digest(pairing.code, code):
            pairing.attempts += 1
            if pairing.attempts >= MAX_ATTEMPTS:
                _LOGGER.warning(
                    "Too many wrong pairing codes for panel %s; "
                    "the approval was cancelled",
                    panel_id,
                )
                del self.armed[panel_id]
            return None

        del self.armed[panel_id]
        return pairing.token

    def discard(self, panel_id: str) -> None:
        """Drop an approval, for a panel that is being removed."""
        self.armed.pop(panel_id, None)
