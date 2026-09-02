import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "t560-power-button.py"
SPEC = importlib.util.spec_from_file_location("power_button", SCRIPT)
POWER_BUTTON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POWER_BUTTON)


class ScreenOffSecondsTest(unittest.TestCase):
    """config.ini is the fallback a tablet uses before it reaches Home
    Assistant, so it keeps its own rules."""

    def read(self, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(contents, encoding="utf-8")
            return POWER_BUTTON.config_screen_off(str(path))

    def test_reads_the_configured_timeout(self):
        self.assertEqual(self.read("[panel]\nscreen_off_seconds=45\n"), 45)

    def test_zero_disables_automatic_screen_off(self):
        self.assertEqual(self.read("[panel]\nscreen_off_seconds=0\n"), 0)
        self.assertEqual(self.read("[panel]\nscreen_off_seconds=-10\n"), 0)

    def test_clamps_out_of_range_values(self):
        self.assertEqual(
            self.read("[panel]\nscreen_off_seconds=1\n"),
            POWER_BUTTON.MIN_SCREEN_OFF_SECONDS,
        )
        self.assertEqual(
            self.read("[panel]\nscreen_off_seconds=99999\n"),
            POWER_BUTTON.MAX_SCREEN_OFF_SECONDS,
        )

    def test_falls_back_to_the_default(self):
        self.assertEqual(
            self.read("[panel]\npoll_interval_ms=1000\n"),
            POWER_BUTTON.DEFAULT_SCREEN_OFF_SECONDS,
        )
        self.assertEqual(
            self.read("[panel]\nscreen_off_seconds=soon\n"),
            POWER_BUTTON.DEFAULT_SCREEN_OFF_SECONDS,
        )
        self.assertEqual(
            POWER_BUTTON.config_screen_off("/nonexistent/config.ini"),
            POWER_BUTTON.DEFAULT_SCREEN_OFF_SECONDS,
        )


class HomeAssistantScreenOffTest(unittest.TestCase):
    """The timeout Home Assistant owns is read out of the panel's own cache,
    so the two processes cannot hold different ideas of it."""

    def read(self, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.json"
            path.write_text(contents, encoding="utf-8")
            return POWER_BUTTON.home_assistant_screen_off(str(path))

    def payload(self, settings):
        return json.dumps({"attributes": {"settings": settings}})

    def test_reads_the_setting(self):
        self.assertEqual(
            self.read(self.payload({"screen_off_seconds": 90})), 90
        )

    def test_zero_disables_automatic_screen_off(self):
        self.assertEqual(
            self.read(self.payload({"screen_off_seconds": 0})), 0
        )

    def test_clamps_out_of_range_values(self):
        self.assertEqual(
            self.read(self.payload({"screen_off_seconds": 2})),
            POWER_BUTTON.MIN_SCREEN_OFF_SECONDS,
        )

    def test_no_setting_means_config_ini_decides(self):
        self.assertIsNone(self.read(self.payload({})))
        self.assertIsNone(self.read(json.dumps({"attributes": {}})))
        self.assertIsNone(self.read("{}"))

    def test_an_unusable_cache_means_config_ini_decides(self):
        self.assertIsNone(self.read("not json"))
        self.assertIsNone(self.read("[]"))
        self.assertIsNone(
            self.read(self.payload({"screen_off_seconds": "soon"}))
        )
        self.assertIsNone(
            self.read(self.payload({"screen_off_seconds": True}))
        )
        self.assertIsNone(
            POWER_BUTTON.home_assistant_screen_off("/nonexistent/layout.json")
        )


class DisplayRequestTest(unittest.TestCase):
    """What the panel asks for is read once and then forgotten, so a request
    that cannot be carried out is not retried forever."""

    def take(self, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-request.ini"
            if contents is not None:
                path.write_text(contents, encoding="utf-8")
            original = POWER_BUTTON.DISPLAY_REQUEST
            POWER_BUTTON.DISPLAY_REQUEST = str(path)
            try:
                return POWER_BUTTON.take_display_request(), path.exists()
            finally:
                POWER_BUTTON.DISPLAY_REQUEST = original

    def test_reads_both_requests(self):
        result, remains = self.take(
            "[display]\nstate=off\nbrightness=40\n"
        )
        self.assertEqual(result, ("off", 40))
        self.assertFalse(remains)

    def test_missing_file_is_not_a_request(self):
        self.assertEqual(self.take(None), ((None, None), False))

    def test_an_unknown_state_is_ignored(self):
        result, _ = self.take("[display]\nstate=dim\n")
        self.assertEqual(result, (None, None))

    def test_an_unusable_brightness_is_ignored(self):
        result, _ = self.take("[display]\nstate=on\nbrightness=bright\n")
        self.assertEqual(result, ("on", None))


class BacklightTest(unittest.TestCase):
    """A backlight this session cannot write must read as absent, so Home
    Assistant shows the control as unavailable instead of doing nothing."""

    def device(self, directory, brightness, maximum):
        path = Path(directory) / "panel"
        path.mkdir()
        (path / "brightness").write_text(f"{brightness}\n", encoding="utf-8")
        (path / "max_brightness").write_text(f"{maximum}\n", encoding="utf-8")
        return path

    def test_percent_is_scaled_from_the_kernel_maximum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.device(directory, 128, 255)
            self.assertEqual(
                POWER_BUTTON.read_backlight_percent(str(path)), 50
            )

    def test_no_device_reads_as_no_backlight(self):
        self.assertEqual(POWER_BUTTON.read_backlight_percent(None), -1)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(POWER_BUTTON.backlight_device(directory))
        self.assertIsNone(POWER_BUTTON.backlight_device("/nonexistent"))

    def test_writing_never_reaches_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.device(directory, 255, 255)
            self.assertTrue(
                POWER_BUTTON.write_backlight_percent(str(path), 1)
            )
            raw = (path / "brightness").read_text(encoding="utf-8").strip()
            self.assertEqual(raw, "3")

    def test_a_maximum_of_zero_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.device(directory, 0, 0)
            self.assertFalse(
                POWER_BUTTON.write_backlight_percent(str(path), 50)
            )
            self.assertEqual(
                POWER_BUTTON.read_backlight_percent(str(path)), -1
            )


class MotionWakeGraceSecondsTest(unittest.TestCase):
    def read(self, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(contents, encoding="utf-8")
            return POWER_BUTTON.motion_wake_grace_seconds(str(path))

    def test_reads_the_configured_grace(self):
        self.assertEqual(self.read("[camera]\nmotion_wake_grace_seconds=45\n"),
                         45)

    def test_zero_wakes_the_display_on_the_first_motion(self):
        self.assertEqual(self.read("[camera]\nmotion_wake_grace_seconds=0\n"),
                         0)

    def test_clamps_out_of_range_values(self):
        self.assertEqual(
            self.read("[camera]\nmotion_wake_grace_seconds=-5\n"),
            POWER_BUTTON.MIN_MOTION_WAKE_GRACE_SECONDS,
        )
        self.assertEqual(
            self.read("[camera]\nmotion_wake_grace_seconds=99999\n"),
            POWER_BUTTON.MAX_MOTION_WAKE_GRACE_SECONDS,
        )

    def test_falls_back_to_the_default(self):
        self.assertEqual(
            self.read("[panel]\nscreen_off_seconds=30\n"),
            POWER_BUTTON.DEFAULT_MOTION_WAKE_GRACE_SECONDS,
        )
        self.assertEqual(
            self.read("[camera]\nmotion_wake_grace_seconds=later\n"),
            POWER_BUTTON.DEFAULT_MOTION_WAKE_GRACE_SECONDS,
        )
        self.assertEqual(
            POWER_BUTTON.motion_wake_grace_seconds("/nonexistent/config.ini"),
            POWER_BUTTON.DEFAULT_MOTION_WAKE_GRACE_SECONDS,
        )


class MotionWakeDelayTest(unittest.TestCase):
    def tearDown(self):
        POWER_BUTTON.display_off_manual = True

    def test_a_power_press_uses_the_configured_grace(self):
        POWER_BUTTON.display_off_manual = True
        self.assertEqual(POWER_BUTTON.motion_wake_delay(30), 30)

    def test_an_automatic_screen_off_only_waits_for_the_backlight(self):
        POWER_BUTTON.display_off_manual = False
        self.assertEqual(POWER_BUTTON.motion_wake_delay(30),
                         POWER_BUTTON.MOTION_SETTLE_SECONDS)


if __name__ == "__main__":
    unittest.main()
