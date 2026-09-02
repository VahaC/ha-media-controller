"""Telling a person that one half of the contract is behind the other.

The integration and the panel are released separately, so one of them can be
older than the other and both directions fail quietly. An old panel never
calls the status endpoint and never reads `settings` or `commands`, which
leaves Battery, Screen, Page and the rest sitting unavailable with nothing to
explain them. This module turns that into a repair issue that names the panel
and says what to do about it.

Every panel is checked the same way, because every panel behaves the same
way: the tablet and the paired ESP32 firmware both pair, both poll the config
sensor and both report. Only the remedy differs — a tablet is rebuilt and
copied over SSH, an ESP32 is reflashed — so the profile picks the wording of
the issue and nothing else.

The other direction — a new panel against an old integration — cannot be
reported here at all, because an old integration is by definition a build
without this file in it. Each panel notices that one itself and says so where
its own user looks: the tablet on its status line, in `update_config` in
`clients/t560/src/application.c`, and the paired firmware in its ESPHome log,
in `ui_load_room_config` in `firmware/media-controller-paired.yaml`.

The rule being applied lives in `contract.py`, which has no Home Assistant
imports and is tested on its own. Everything here is the Home Assistant half:
reading the evidence out of the registries and writing the issue.
"""

from __future__ import annotations

import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import CONF_PROFILE, DOMAIN
from .contract import (
    CONTRACT_VERSION,
    PANEL_CONTRACT_OK,
    PANEL_CONTRACT_OUTDATED,
    panel_contract_verdict,
)
from .panel_state import PanelState
from .profiles import UPDATE_KIND_FIRMWARE, UPDATE_KIND_TABLET, panel_profile

# Where each update procedure is written down. The issue text names the step;
# these are for the reader who wants the whole thing.
REPOSITORY_URL = "https://github.com/VahaC/ha-media-controller/blob/main"
DOCUMENTATION_URL = {
    UPDATE_KIND_TABLET: (
        f"{REPOSITORY_URL}/clients/t560/docs/BUILD_AND_INSTALL.md"
    ),
    UPDATE_KIND_FIRMWARE: (
        f"{REPOSITORY_URL}/docs/ESP32_PAIRED_CONTROLLER.md"
    ),
}

# One issue per case per kind of client. The two cases are the same defect
# with different evidence, and the two kinds need different instructions.
ISSUE_PANEL_OUTDATED = "panel_contract_outdated"
ISSUE_PANEL_SILENT = "panel_never_reported"


@callback
def async_panel_issue_id(entry: ConfigEntry) -> str:
    """Return the issue ID one panel entry owns."""
    return f"panel_contract_{entry.entry_id}"


@callback
def async_update_panel_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: PanelState,
    *,
    loaded_at: float,
    now: float | None = None,
) -> None:
    """Raise or clear the repair issue for one panel's build.

    An undecided verdict deliberately changes nothing. Every Home Assistant
    restart begins with no report and a grace period that has not run out, so
    clearing on undecided would make a real issue disappear for ten minutes
    after every restart and then come back, which reads as a bug rather than
    as a finding.
    """
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    verdict = panel_contract_verdict(
        reported_version=state.status.contract_version,
        heard_this_run=state.reported_at is not None,
        # The device's software version is the only record of a panel having
        # ever reported that survives a restart, and it is written by the
        # status endpoint from the report itself. A device that is merely
        # switched off carries one; a device on a build that cannot report
        # never has.
        heard_before=bool(device is not None and device.sw_version),
        seconds_since_load=(time.monotonic() if now is None else now)
        - loaded_at,
    )
    issue_id = async_panel_issue_id(entry)

    if verdict == PANEL_CONTRACT_OK:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    if verdict != PANEL_CONTRACT_OUTDATED:
        return

    reported = state.status.contract_version
    kind = panel_profile(entry.data.get(CONF_PROFILE)).update_kind
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        # A panel that has never said anything and a panel that named an older
        # version are the same defect with different evidence, and a person
        # fixing them needs to be told which one they are looking at — and
        # which of the two update procedures theirs is.
        translation_key=(
            f"{ISSUE_PANEL_OUTDATED if reported else ISSUE_PANEL_SILENT}"
            f"_{kind}"
        ),
        translation_placeholders={
            "name": entry.title,
            "panel_contract": str(reported),
            "integration_contract": str(CONTRACT_VERSION),
        },
        learn_more_url=DOCUMENTATION_URL.get(
            kind, DOCUMENTATION_URL[UPDATE_KIND_FIRMWARE]
        ),
    )


@callback
def async_clear_panel_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the issue of a panel that no longer exists."""
    ir.async_delete_issue(hass, DOMAIN, async_panel_issue_id(entry))
