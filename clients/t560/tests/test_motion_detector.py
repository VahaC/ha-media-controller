import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "t560-motion-detector.py"
SPEC = importlib.util.spec_from_file_location("motion_detector", SCRIPT)
MOTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOTION)

# SIGUSR2 only exists on the tablet and on other POSIX hosts.
POSIX_SIGNALS = hasattr(MOTION.signal, "SIGUSR2")


class CameraSettingsTest(unittest.TestCase):
    def read(self, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(contents, encoding="utf-8")
            return MOTION.camera_settings(str(path))

    def test_uses_the_defaults_without_a_camera_section(self):
        self.assertEqual(self.read("[panel]\npoll_interval_ms=1000\n"),
                         MOTION.DEFAULT_SETTINGS)

    def test_reads_the_configured_values(self):
        settings = self.read(
            "[camera]\n"
            "motion_detection=off\n"
            "device=/dev/video2\n"
            "width=640\n"
            "frame_interval_ms=500\n"
        )
        self.assertFalse(settings["motion_detection"])
        self.assertEqual(settings["device"], "/dev/video2")
        self.assertEqual(settings["width"], 640)
        self.assertEqual(settings["frame_interval_ms"], 500)

    def test_accepts_the_documented_boolean_spellings(self):
        for value in ("on", "true", "YES", "1", "enabled"):
            self.assertTrue(self.read(f"[camera]\nmotion_detection={value}\n")
                            ["motion_detection"])
        for value in ("off", "false", "NO", "0", "disabled"):
            self.assertFalse(self.read(f"[camera]\nmotion_detection={value}\n")
                             ["motion_detection"])

    def test_clamps_out_of_range_values(self):
        settings = self.read(
            "[camera]\n"
            "width=4000\n"
            "height=1\n"
            "motion_area_percent=900\n"
            "cooldown_seconds=0\n"
        )
        self.assertEqual(settings["width"], MOTION.SETTING_LIMITS["width"][1])
        self.assertEqual(settings["height"], MOTION.SETTING_LIMITS["height"][0])
        self.assertEqual(settings["motion_area_percent"], 100)
        self.assertEqual(settings["cooldown_seconds"],
                         MOTION.SETTING_LIMITS["cooldown_seconds"][0])

    def test_keeps_the_defaults_for_invalid_values(self):
        settings = self.read(
            "[camera]\n"
            "motion_detection=sometimes\n"
            "pixel_threshold=high\n"
        )
        self.assertEqual(settings["motion_detection"],
                         MOTION.DEFAULT_SETTINGS["motion_detection"])
        self.assertEqual(settings["pixel_threshold"],
                         MOTION.DEFAULT_SETTINGS["pixel_threshold"])

    def test_falls_back_when_the_file_is_missing(self):
        self.assertEqual(MOTION.camera_settings("/nonexistent/config.ini"),
                         MOTION.DEFAULT_SETTINGS)


class SamplingTest(unittest.TestCase):
    def test_blocks_average_their_own_part_of_the_frame(self):
        width, height = 32, 24
        frame = bytes(
            0 if column < width // 2 else 200
            for _ in range(height) for column in range(width)
        )
        plan = MOTION.sample_plan(width, height, width)
        averages = MOTION.block_averages(frame, plan)

        self.assertEqual(len(averages), MOTION.GRID_COLUMNS * MOTION.GRID_ROWS)
        for row in range(MOTION.GRID_ROWS):
            for column in range(MOTION.GRID_COLUMNS):
                expected = 0 if column < MOTION.GRID_COLUMNS // 2 else 200
                self.assertEqual(averages[row * MOTION.GRID_COLUMNS + column],
                                 expected)

    def test_reads_only_the_luminance_bytes_of_packed_formats(self):
        width, height = 16, 8
        for name, (offset, pixel_bytes) in (
            ("YUYV", MOTION.PLANE_LAYOUTS[MOTION.four_cc("YUYV")]),
            ("UYVY", MOTION.PLANE_LAYOUTS[MOTION.four_cc("UYVY")]),
        ):
            with self.subTest(format=name):
                stride = width * pixel_bytes
                frame = bytearray(250 for _ in range(stride * height))
                for row in range(height):
                    for column in range(width):
                        frame[offset + row * stride + column * pixel_bytes] = 40
                plan = MOTION.sample_plan(width, height, stride, pixel_bytes,
                                          offset)
                self.assertEqual(set(MOTION.block_averages(bytes(frame), plan)),
                                 {40})

    def test_honours_a_padded_row_stride(self):
        width, height, stride = 8, 8, 12
        frame = bytearray(255 for _ in range(stride * height))
        for row in range(height):
            for column in range(width):
                frame[row * stride + column] = 60
        plan = MOTION.sample_plan(width, height, stride, columns=4, rows=4)
        self.assertEqual(set(MOTION.block_averages(bytes(frame), plan)), {60})


class BlockDifferenceTest(unittest.TestCase):
    def test_ignores_a_frame_wide_brightness_change(self):
        previous = [100] * 24
        current = [130] * 24
        self.assertEqual(MOTION.changed_blocks(previous, current, 12), 0)

    def test_counts_blocks_that_move_against_the_frame(self):
        previous = [100] * 24
        current = [100] * 24
        current[3] = 150
        current[4] = 40
        self.assertEqual(MOTION.changed_blocks(previous, current, 12), 2)

    def test_counts_movement_during_a_brightness_change(self):
        previous = [100] * 24
        current = [120] * 24
        current[7] = 200
        self.assertEqual(MOTION.changed_blocks(previous, current, 12), 1)

    def test_required_blocks_never_drops_below_one(self):
        self.assertEqual(MOTION.required_blocks(192, 1), 2)
        self.assertEqual(MOTION.required_blocks(10, 1), 1)
        self.assertEqual(MOTION.required_blocks(192, 100), 192)


class MotionTrackerTest(unittest.TestCase):
    def tracker(self, frames=2, cooldown=2):
        return MOTION.MotionTracker(
            pixel_threshold=12,
            area_percent=10,
            frames=frames,
            cooldown_seconds=cooldown,
        )

    def moved(self, value, count=4):
        blocks = [100] * 20
        for index in range(count):
            blocks[index] = value
        return blocks

    def test_the_first_frame_is_only_a_reference(self):
        tracker = self.tracker()
        self.assertFalse(tracker.update([100] * 20, 0.0))

    def test_requires_the_configured_number_of_frames(self):
        tracker = self.tracker(frames=3)
        self.assertFalse(tracker.update([100] * 20, 0.0))
        self.assertFalse(tracker.update(self.moved(160), 0.4))
        self.assertFalse(tracker.update(self.moved(40), 0.8))
        self.assertTrue(tracker.update(self.moved(160), 1.2))

    def test_a_small_change_is_not_motion(self):
        tracker = self.tracker(frames=1)
        tracker.update([100] * 20, 0.0)
        self.assertFalse(tracker.update(self.moved(160, count=1), 0.4))

    def test_a_quiet_frame_restarts_the_streak(self):
        tracker = self.tracker(frames=2)
        tracker.update([100] * 20, 0.0)
        self.assertFalse(tracker.update(self.moved(160), 0.4))
        self.assertFalse(tracker.update(self.moved(160), 0.8))
        self.assertFalse(tracker.update(self.moved(160), 1.2))

    def test_the_cooldown_limits_the_event_rate(self):
        tracker = self.tracker(frames=1, cooldown=2)
        tracker.update([100] * 20, 0.0)
        self.assertTrue(tracker.update(self.moved(160), 0.4))
        self.assertFalse(tracker.update(self.moved(40), 0.8))
        self.assertFalse(tracker.update(self.moved(160), 1.2))
        self.assertTrue(tracker.update(self.moved(40), 2.6))

    def test_reset_drops_the_reference_frame(self):
        tracker = self.tracker(frames=1)
        tracker.update([100] * 20, 0.0)
        tracker.reset()
        self.assertFalse(tracker.update(self.moved(160), 0.4))


class CameraCandidatesTest(unittest.TestCase):
    def test_uses_the_configured_node_only(self):
        self.assertEqual(MOTION.camera_candidates("/dev/video3"),
                         ["/dev/video3"])

    def test_probes_every_node_in_numeric_order(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("video10", "video2", "video0", "vcs", "videoX"):
                Path(directory, name).write_bytes(b"")
            self.assertEqual(
                MOTION.camera_candidates("auto", directory),
                [f"{directory}/video0", f"{directory}/video2",
                 f"{directory}/video10"],
            )

    def test_reports_a_missing_device_directory(self):
        self.assertEqual(MOTION.camera_candidates("auto", "/nonexistent"), [])


class PowerButtonNotifierTest(unittest.TestCase):
    def fake_proc(self, directory, processes):
        for pid, command in processes.items():
            Path(directory, str(pid)).mkdir()
            Path(directory, str(pid), "cmdline").write_bytes(command)
        Path(directory, "self").mkdir()

    @unittest.skipUnless(POSIX_SIGNALS, "SIGUSR2 is a POSIX signal")
    def test_finds_the_handler_and_signals_it(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, {
                11: b"/usr/bin/tint2\0",
                12: b"python3\0/home/vahac/.local/bin/t560-power-button.py\0",
            })
            notifier = MOTION.PowerButtonNotifier(proc=directory)
            with mock.patch.object(MOTION.os, "kill") as kill:
                self.assertTrue(notifier.notify())
            kill.assert_called_once_with(12, MOTION.signal.SIGUSR2)
            self.assertEqual(notifier.pids, [12])

    @unittest.skipUnless(POSIX_SIGNALS, "SIGUSR2 is a POSIX signal")
    def test_rescans_when_the_handler_was_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, {
                12: b"python3\0/home/vahac/.local/bin/t560-power-button.py\0",
            })
            notifier = MOTION.PowerButtonNotifier(proc=directory)
            notifier.pids = [99]
            with mock.patch.object(MOTION.os, "kill") as kill:
                self.assertTrue(notifier.notify())
            kill.assert_called_once_with(12, MOTION.signal.SIGUSR2)

    def test_reports_a_missing_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, {11: b"/usr/bin/tint2\0"})
            notifier = MOTION.PowerButtonNotifier(proc=directory)
            with mock.patch.object(MOTION.os, "kill") as kill:
                self.assertFalse(notifier.notify())
            kill.assert_not_called()

    def test_never_signals_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, {
                os.getpid(): b"python3\0t560-power-button.py\0",
            })
            notifier = MOTION.PowerButtonNotifier(proc=directory)
            self.assertEqual(notifier.find(), [])

    def test_accepts_a_directly_executed_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, {
                12: b"/home/vahac/.local/bin/t560-power-button.py\0",
            })
            self.assertEqual(
                MOTION.PowerButtonNotifier(proc=directory).find(), [12])

    def test_ignores_an_editor_that_opened_the_handler(self):
        # SIGUSR2 terminates a process that does not expect it.
        with tempfile.TemporaryDirectory() as directory:
            self.fake_proc(directory, {
                13: b"nano\0/home/vahac/.local/bin/t560-power-button.py\0",
                14: b"tail\0-f\0/home/vahac/.local/state/power-button.log\0",
            })
            self.assertEqual(
                MOTION.PowerButtonNotifier(proc=directory).find(), [])


class PixelFormatTest(unittest.TestCase):
    def test_four_character_codes_round_trip(self):
        for name in MOTION.PREFERRED_FORMATS:
            self.assertEqual(MOTION.four_cc_name(MOTION.four_cc(name)), name)

    def test_every_preferred_format_has_a_plane_layout(self):
        for name in MOTION.PREFERRED_FORMATS:
            self.assertIn(MOTION.four_cc(name), MOTION.PLANE_LAYOUTS)

    def test_the_ioctl_numbers_match_the_32_bit_arm_kernel(self):
        self.assertEqual(MOTION.VIDIOC_QUERYCAP, 0x80685600)
        self.assertEqual(MOTION.VIDIOC_ENUM_FMT, 0xC0405602)
        self.assertEqual(MOTION.VIDIOC_S_FMT, 0xC0CC5605)
        self.assertEqual(MOTION.VIDIOC_REQBUFS, 0xC0145608)
        self.assertEqual(MOTION.VIDIOC_QUERYBUF, 0xC0445609)
        self.assertEqual(MOTION.VIDIOC_QBUF, 0xC044560F)
        self.assertEqual(MOTION.VIDIOC_DQBUF, 0xC0445611)
        self.assertEqual(MOTION.VIDIOC_STREAMON, 0x40045612)
        self.assertEqual(MOTION.VIDIOC_STREAMOFF, 0x40045613)
        self.assertEqual(MOTION.VIDIOC_S_PARM, 0xC0CC5616)


class CameraFailureTest(unittest.TestCase):
    def test_a_missing_node_is_not_reported_as_permanent(self):
        settings = dict(MOTION.DEFAULT_SETTINGS, device="/nonexistent/video9")
        camera, permanent = MOTION.open_camera(settings)
        self.assertIsNone(camera)
        self.assertFalse(permanent)

    def test_an_empty_device_directory_is_permanent(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(MOTION, "camera_candidates",
                                   return_value=[]):
                camera, permanent = MOTION.open_camera(
                    dict(MOTION.DEFAULT_SETTINGS, device=directory))
        self.assertIsNone(camera)
        self.assertTrue(permanent)

    @unittest.skipUnless(MOTION.fcntl is not None, "ioctl needs Linux")
    def test_a_failed_ioctl_names_the_call(self):
        read_end, write_end = os.pipe()
        os.close(write_end)
        os.close(read_end)
        with self.assertRaises(MOTION.CameraError) as raised:
            MOTION._ioctl(read_end, MOTION.VIDIOC_QUERYCAP,
                          MOTION.V4L2Capability(), "QUERYCAP")
        self.assertIn("QUERYCAP", str(raised.exception))

    def test_the_driver_limitation_errors_are_permanent(self):
        self.assertIn(MOTION.errno.ENOTTY, MOTION.PERMANENT_ERRNOS)
        self.assertIn(MOTION.errno.ENODEV, MOTION.PERMANENT_ERRNOS)
        self.assertNotIn(MOTION.errno.EBUSY, MOTION.PERMANENT_ERRNOS)
        self.assertNotIn(MOTION.errno.ENOENT, MOTION.PERMANENT_ERRNOS)


if __name__ == "__main__":
    unittest.main()
