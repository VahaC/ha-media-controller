"""The protocol number the two sides of the contract compare.

`docs/CONTRACT.md` carries a contract version, and until now it existed only
as prose: nothing in code knew it, so nothing could notice that a client and
the integration no longer speak the same protocol. This module puts that
number where it can be compared, and holds the rule that compares it.

The number to compare is the **contract** version, not a release version.
`0.9.1` and `panel-v0.4.0` say when something shipped, not what it can do:
two builds a month apart may implement the same protocol, and two builds an
hour apart may not. The contract version is the only number that answers
"do these two understand each other".

This module deliberately has no Home Assistant imports, so the rule can be
tested without a Home Assistant runtime. The repair issue it feeds lives in
`compatibility.py`.
"""

from __future__ import annotations

from typing import Any

# The version of docs/CONTRACT.md this build implements. Raise it in the same
# change that raises the number in that document, and never separately: a
# client compares the two sides against each other, so a constant that has
# drifted from the document is worse than no constant at all.
CONTRACT_VERSION = 8

# What a payload or a report that names no contract version is taken to
# speak. Every version of the contract before this one was silent about it,
# so "absent" and "older than anything that can say so" are the same fact.
CONTRACT_VERSION_UNKNOWN = 0

# A panel has this long after its entry is loaded to say something before its
# silence is read as a verdict. It reports within seconds of starting, so this
# is generous: it covers a tablet still booting and an entry that was paired a
# moment ago, and nothing else.
SILENT_PANEL_GRACE_SECONDS = 600.0

# What is known about one panel's half of the contract.
PANEL_CONTRACT_OK = "ok"
PANEL_CONTRACT_OUTDATED = "outdated"
# Not enough evidence yet: the panel has simply not been heard from, and a
# tablet that is switched off must not be reported as a stale build.
PANEL_CONTRACT_UNDECIDED = "undecided"


def read_contract_version(value: Any) -> int:
    """Read a reported contract version, using 0 for anything unusable.

    A client that predates this field sends nothing, and a client that sends
    nonsense is treated the same way. Both mean the same thing in practice:
    it cannot prove it speaks the current protocol.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return CONTRACT_VERSION_UNKNOWN
    number = int(value)
    return number if number > 0 else CONTRACT_VERSION_UNKNOWN


def panel_contract_verdict(
    *,
    reported_version: int,
    heard_this_run: bool,
    heard_before: bool,
    seconds_since_load: float,
) -> str:
    """Decide whether one panel is running a build older than this contract.

    Two situations have to be told apart, and only one of them is evidence:

    * a panel that **has reported** names the contract version it speaks, so
      the comparison is a fact and needs no heuristic;
    * a panel that has **never reported at all** is the case this exists for.
      It is invisible otherwise: its battery, screen, page and settings
      entities simply sit unavailable forever with no explanation, and the
      cause is almost always a device running a build from before the status
      endpoint existed.

    Silence alone cannot separate that from a device somebody switched off,
    so it is not what is asked. `heard_before` is: it is true when the panel
    has ever reported in the life of this installation, which the integration
    already records outside its own memory as the device's software version.
    A device that is merely off has spoken at some point and carries one; a
    device that cannot report never has and never will. The grace period then
    covers the one honest gap left — a panel paired minutes ago, or one still
    booting — at the cost of a false report only for a device that was paired
    and then left switched off for the first ten minutes of its life, which
    clears itself the moment it reports.

    Every panel is judged by these same rules. The tablet and the paired
    ESP32 firmware pair, poll and report alike, so nothing here asks which
    one it is looking at; only the remedy differs, and that is the caller's
    business.
    """
    if heard_this_run:
        return (
            PANEL_CONTRACT_OK
            if reported_version >= CONTRACT_VERSION
            else PANEL_CONTRACT_OUTDATED
        )
    if heard_before:
        # It reports, so it will name its contract version the next time it
        # is switched on. Judging it now would mean judging its silence.
        return PANEL_CONTRACT_UNDECIDED
    if seconds_since_load < SILENT_PANEL_GRACE_SECONDS:
        return PANEL_CONTRACT_UNDECIDED
    return PANEL_CONTRACT_OUTDATED
