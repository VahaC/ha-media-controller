"""Tests for the panel settings, commands, and status report rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "media_controller"
    / "panel_state.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_panel_state", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
panel_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = panel_state
SPEC.loader.exec_module(panel_state)


class SettingsTests(unittest.TestCase):
    """Verify that a stored settings record is always usable."""

    def test_defaults_when_nothing_is_stored(self) -> None:
        settings = panel_state.PanelSettings.from_stored(None)
        self.assertEqual(settings.poll_interval_ms, 1000)
        self.assertEqual(settings.playlist_poll_interval_ms, 60000)
        self.assertEqual(settings.screen_off_seconds, 30)

    def test_out_of_range_values_are_clamped(self) -> None:
        settings = panel_state.PanelSettings.from_stored(
            {
                "poll_interval_ms": 1,
                "playlist_poll_interval_ms": 99999999,
                "screen_off_seconds": 2,
            }
        )
        self.assertEqual(settings.poll_interval_ms, 500)
        self.assertEqual(settings.playlist_poll_interval_ms, 3600000)
        self.assertEqual(settings.screen_off_seconds, 5)

    def test_zero_screen_off_means_never(self) -> None:
        settings = panel_state.PanelSettings.from_stored(
            {"screen_off_seconds": 0}
        )
        self.assertEqual(settings.screen_off_seconds, 0)

    def test_unusable_values_fall_back(self) -> None:
        settings = panel_state.PanelSettings.from_stored(
            {"poll_interval_ms": "soon", "screen_off_seconds": None}
        )
        self.assertEqual(settings.poll_interval_ms, 1000)
        self.assertEqual(settings.screen_off_seconds, 30)

    def test_one_value_is_replaced_and_revalidated(self) -> None:
        settings = panel_state.PanelSettings().with_value(
            panel_state.SETTING_POLL_INTERVAL, 10
        )
        self.assertEqual(settings.poll_interval_ms, 500)
        self.assertEqual(settings.playlist_poll_interval_ms, 60000)


class CommandTests(unittest.TestCase):
    """Verify the timestamped command channel a polling client reads."""

    def test_no_command_is_sent_before_one_is_issued(self) -> None:
        state = panel_state.PanelState()
        self.assertEqual(state.commands.as_payload(), {})

    def test_display_command_carries_state_and_moment(self) -> None:
        state = panel_state.PanelState()
        state.request_display(False, at=1700)
        self.assertEqual(
            state.commands.as_payload()["display"],
            {"state": "off", "at": 1700},
        )

    def test_display_command_updates_the_switch_optimistically(self) -> None:
        state = panel_state.PanelState()
        state.request_display(True, at=1700)
        self.assertTrue(state.status.display_on)
        self.assertTrue(state.status.display_known)

    def test_brightness_is_clamped_before_it_is_sent(self) -> None:
        state = panel_state.PanelState()
        state.request_brightness(400, at=1700)
        self.assertEqual(
            state.commands.as_payload()["brightness"],
            {"value": 100, "at": 1700},
        )

    def test_restart_only_carries_a_moment(self) -> None:
        state = panel_state.PanelState()
        state.request_restart(at=1700)
        self.assertEqual(
            state.commands.as_payload()["restart"], {"at": 1700}
        )

    def test_a_later_command_replaces_the_earlier_one(self) -> None:
        state = panel_state.PanelState()
        state.request_display(False, at=1700)
        state.request_display(True, at=1800)
        self.assertEqual(
            state.commands.as_payload()["display"],
            {"state": "on", "at": 1800},
        )


class PageCommandTests(unittest.TestCase):
    """Verify that only a page the clients know can be requested."""

    def test_a_known_page_is_sent(self) -> None:
        state = panel_state.PanelState()
        self.assertTrue(state.request_page("room", at=1700))
        self.assertEqual(
            state.commands.as_payload()["page"],
            {"value": "room", "at": 1700},
        )
        self.assertEqual(state.status.page, "room")

    def test_an_unknown_page_is_refused(self) -> None:
        state = panel_state.PanelState()
        self.assertFalse(state.request_page("settings", at=1700))
        self.assertEqual(state.commands.as_payload(), {})
        self.assertEqual(state.status.page, "")

    def test_every_offered_page_is_accepted(self) -> None:
        for page in panel_state.PAGES:
            state = panel_state.PanelState()
            self.assertTrue(state.request_page(page, at=1))


class UptimeTests(unittest.TestCase):
    """Verify that the start time stays still while the panel does."""

    def test_the_start_time_is_derived_from_the_uptime(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({"uptime_seconds": 600}, now=1.0, wall=10_000.0)
        self.assertEqual(state.started_at, 9400.0)

    def test_a_small_drift_does_not_move_the_start_time(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({"uptime_seconds": 600}, now=1.0, wall=10_000.0)
        # A second later the tablet reports the same second of uptime; the
        # implied start moved by one second, which is rounding, not a restart.
        state.apply_report({"uptime_seconds": 600}, now=2.0, wall=10_001.0)
        self.assertEqual(state.started_at, 9400.0)

    def test_a_restart_moves_the_start_time(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({"uptime_seconds": 600}, now=1.0, wall=10_000.0)
        state.apply_report({"uptime_seconds": 5}, now=2.0, wall=10_010.0)
        self.assertEqual(state.started_at, 10_005.0)

    def test_no_uptime_means_no_start_time(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({"uptime_seconds": -5}, now=1.0, wall=10_000.0)
        self.assertIsNone(state.started_at)
        state.apply_report({}, now=2.0, wall=10_000.0)
        self.assertIsNone(state.started_at)

    def test_the_arrival_time_is_recorded(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({}, now=1.0, wall=10_000.0)
        self.assertEqual(state.reported_wall_at, 10_000.0)


class StatusReportTests(unittest.TestCase):
    """Verify that a report from the tablet is validated, not trusted."""

    def test_full_report(self) -> None:
        status = panel_state.PanelStatus.from_report(
            {
                "battery": {
                    "available": True,
                    "percent": 82,
                    "charging": True,
                },
                "display": {"available": True, "on": True, "brightness": 55},
                "version": "0.3.0",
                "page": "room",
                "uptime_seconds": 4210,
                "wifi_dbm": -53,
                "temperature_c": 31.5,
            }
        )
        self.assertEqual(status.battery_percent, 82)
        self.assertTrue(status.battery_charging)
        self.assertTrue(status.display_on)
        self.assertTrue(status.display_known)
        self.assertEqual(status.brightness, 55)
        self.assertEqual(status.app_version, "0.3.0")
        self.assertEqual(status.page, "room")
        self.assertEqual(status.uptime_seconds, 4210)
        self.assertEqual(status.wifi_dbm, -53)
        self.assertEqual(status.temperature_c, 31.5)

    def test_empty_report_reads_as_nothing_known(self) -> None:
        status = panel_state.PanelStatus.from_report({})
        self.assertEqual(status.battery_percent, -1)
        self.assertFalse(status.display_known)
        self.assertEqual(status.brightness, -1)
        self.assertEqual(status.page, "")
        self.assertIsNone(status.uptime_seconds)
        self.assertIsNone(status.wifi_dbm)
        self.assertIsNone(status.temperature_c)

    def test_a_page_this_installation_does_not_have_is_dropped(self) -> None:
        # A newer client reporting a page Home Assistant has no option for
        # would otherwise put the select entity into an invalid state.
        status = panel_state.PanelStatus.from_report({"page": "settings"})
        self.assertEqual(status.page, "")

    def test_diagnostics_outside_their_range_are_discarded(self) -> None:
        status = panel_state.PanelStatus.from_report(
            {"wifi_dbm": 40, "temperature_c": 900}
        )
        self.assertIsNone(status.wifi_dbm)
        self.assertIsNone(status.temperature_c)

    def test_diagnostics_of_the_wrong_type_are_discarded(self) -> None:
        status = panel_state.PanelStatus.from_report(
            {"wifi_dbm": "-53 dBm", "temperature_c": True}
        )
        self.assertIsNone(status.wifi_dbm)
        self.assertIsNone(status.temperature_c)

    def test_a_battery_that_is_not_available_reports_no_charge(self) -> None:
        status = panel_state.PanelStatus.from_report(
            {"battery": {"available": False, "percent": 82, "charging": True}}
        )
        self.assertEqual(status.battery_percent, -1)
        self.assertFalse(status.battery_charging)

    def test_impossible_values_are_discarded(self) -> None:
        status = panel_state.PanelStatus.from_report(
            {
                "battery": {"available": True, "percent": 180},
                "display": {"available": True, "brightness": "bright"},
            }
        )
        self.assertEqual(status.battery_percent, -1)
        self.assertEqual(status.brightness, -1)

    def test_a_malformed_section_is_ignored(self) -> None:
        status = panel_state.PanelStatus.from_report(
            {"battery": "82%", "display": None}
        )
        self.assertEqual(status.battery_percent, -1)
        self.assertFalse(status.display_known)

    def test_a_truthy_value_is_not_a_flag(self) -> None:
        # A client sending 1 rather than true must not turn a charger on.
        status = panel_state.PanelStatus.from_report(
            {"battery": {"available": 1, "percent": 50, "charging": 1}}
        )
        self.assertEqual(status.battery_percent, -1)


class PresenceTests(unittest.TestCase):
    """Verify when a panel stops being believed."""

    def test_a_panel_that_never_reported_is_offline(self) -> None:
        self.assertFalse(panel_state.PanelState().is_online())

    def test_a_recent_report_is_online(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({}, now=1000.0)
        self.assertTrue(state.is_online(now=1010.0))

    def test_an_old_report_is_offline(self) -> None:
        state = panel_state.PanelState()
        state.apply_report({}, now=1000.0)
        self.assertFalse(
            state.is_online(now=1000.0 + panel_state.REPORT_TIMEOUT_SECONDS)
        )


class ListenerTests(unittest.TestCase):
    """Verify that every change reaches the entities."""

    def test_listeners_are_called_and_can_be_removed(self) -> None:
        state = panel_state.PanelState()
        calls: list[int] = []
        remove = state.add_listener(lambda: calls.append(1))

        state.set_setting(panel_state.SETTING_SCREEN_OFF, 60)
        state.request_restart(at=1)
        state.apply_report({}, now=1.0)
        self.assertEqual(len(calls), 3)

        remove()
        state.request_restart(at=2)
        self.assertEqual(len(calls), 3)

    def test_a_report_does_not_disturb_the_config_sensor(self) -> None:
        # The config sensor subscribes separately: what a tablet reports back
        # changes nothing the tablet needs to read.
        state = panel_state.PanelState()
        entity: list[int] = []
        config: list[int] = []
        state.add_listener(lambda: entity.append(1))
        state.add_config_listener(lambda: config.append(1))

        state.apply_report({}, now=1.0)
        state.notify()
        self.assertEqual(len(entity), 2)
        self.assertEqual(config, [])

        state.request_restart(at=1)
        self.assertEqual(len(entity), 3)
        self.assertEqual(len(config), 1)

    def test_an_unchanged_setting_notifies_nobody(self) -> None:
        state = panel_state.PanelState()
        calls: list[int] = []
        state.add_listener(lambda: calls.append(1))
        state.set_setting(
            panel_state.SETTING_POLL_INTERVAL,
            state.settings.poll_interval_ms,
        )
        self.assertEqual(calls, [])


class PayloadTests(unittest.TestCase):
    """Verify the block a panel reads from its config sensor."""

    def test_payload_carries_settings_and_commands(self) -> None:
        state = panel_state.PanelState()
        state.request_display(False, at=1700)
        payload = state.as_payload()
        self.assertEqual(
            payload["settings"][panel_state.SETTING_SCREEN_OFF], 30
        )
        self.assertEqual(payload["commands"]["display"]["state"], "off")


if __name__ == "__main__":
    unittest.main()
