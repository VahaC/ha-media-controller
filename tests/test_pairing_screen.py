"""The pairing code has to still be there when somebody arrives.

A panel that has not been set up yet is a panel nobody is touching, and the
inactivity timeout does not know the difference between that and a panel
nobody wants. It used to take the screen away a minute after boot and leave
the six digits behind a black backlight — on the one screen whose entire job
is to be read by somebody walking over to it with a phone.

The fix is a flag the shared interface package offers and the paired firmware
sets. It is checked here rather than in a compile because the failure it
guards against is silent: the flag being set in one place and cleared in only
one of the two ways pairing can finish still passes every build, and the panel
simply never sleeps again.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

FIRMWARE = Path(__file__).parents[1] / "firmware"
UI = FIRMWARE / "media-controller-ui.yaml"
PAIRED = FIRMWARE / "media-controller-paired.yaml"

FLAG = "screen_keep_awake"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _script(source: str, name: str) -> str:
    """Return one script's block, from its id to the next id at that indent."""
    start = source.index(f"  - id: {name}\n")
    following = source.find("\n  - id: ", start + 1)
    return source[start : following if following != -1 else len(source)]


class SleepTimeoutTests(unittest.TestCase):
    """The one place a backlight is turned off has to honour the flag."""

    def test_the_flag_exists_in_the_shared_package(self) -> None:
        # It belongs to the file that owns the timeout, not to the firmware
        # that sets it: the classic firmware includes the same package and
        # simply never sets it.
        self.assertIn(f"  - id: {FLAG}\n", _read(UI))

    def test_the_sleep_condition_checks_it_first(self) -> None:
        source = _read(UI)
        condition = source[
            source.index("uint32_t timeout_ms") - 600 : source.index(
                "- light.turn_off: backlight"
            )
        ]
        self.assertIn(f"if (id({FLAG})) return false;", condition)

    def test_the_timeout_is_the_only_thing_the_flag_has_to_beat(self) -> None:
        # The guard is worth nothing if a second path can sleep the screen
        # behind its back. There is exactly one other place a backlight is
        # turned off, and it is Home Assistant asking for it through the
        # config sensor — which an unpaired device does not read at all.
        self.assertEqual(
            len(re.findall(r"light\.turn_off:\s*backlight", _read(UI))), 1
        )
        commanded = _script(_read(PAIRED), "apply_commands")
        self.assertIn("light.turn_off: backlight", commanded)
        self.assertEqual(
            len(
                re.findall(
                    r"light\.turn_off:\s*backlight", _read(PAIRED)
                )
            ),
            1,
        )


class PairedFirmwareTests(unittest.TestCase):
    """Set where the code goes up, cleared on both ways out."""

    def test_showing_the_code_holds_the_screen_on(self) -> None:
        block = _script(_read(PAIRED), "show_start_page")
        self.assertIn("lvgl.page.show: page_pairing", block)
        self.assertIn(f"id({FLAG}) = true;", block)
        # A device asleep when its token was revoked reaches here too, and a
        # flag alone would leave it dark.
        self.assertIn("light.turn_on: backlight", block)

    def test_both_ways_of_finishing_release_it(self) -> None:
        source = _read(PAIRED)
        for name in ("accept_bootstrap", "poll_pairing"):
            with self.subTest(script=name):
                block = _script(source, name)
                self.assertIn(f"id({FLAG}) = false;", block)
                # Otherwise the timeout starts from whenever the panel was
                # last touched, which for a new one is never.
                self.assertIn("id(screen_last_active_ms) = millis();", block)

    def test_every_screen_that_holds_the_backlight_on_lets_go_of_it(
        self,
    ) -> None:
        """Only two screens may hold it, and each has to release it.

        The flag has no timeout of its own: whatever sets it owns turning it
        off again, and a path that sets it and never clears it is a panel
        that never sleeps for the rest of its life. So the two screens
        allowed to hold it are named here rather than counted, and each one's
        release is asserted separately.

        The second screen is the update screen, added with contract version
        8. It has the same claim as the pairing code: a person is meant to be
        reading it, and it stays up for the whole of a firmware write, during
        which nothing on this device runs — including the timeout that would
        otherwise have taken the backlight away in the middle.
        """
        source = _read(PAIRED)
        setters = re.findall(
            rf"^  - id: (\w+)$|id\({FLAG}\) = true;", source, re.MULTILINE
        )
        holding = []
        script = ""
        for name, in [(match,) for match in setters]:
            if name:
                script = name
            elif script not in holding:
                holding.append(script)
        self.assertEqual(holding, ["show_start_page", "install_firmware"])

    def test_the_update_screen_lets_go_both_ways(self) -> None:
        # An update ends in one of exactly two places, and a panel left on
        # the "do not switch this off" screen with the backlight pinned on is
        # the worst of the two failures to leave behind.
        source = _read(PAIRED)
        self.assertIn(f"id({FLAG}) = false;", _script(source, "confirm_boot"))
        # The failure path is the OTA component's own on_error, which is not
        # a script, so it is asserted against the block that declares it.
        ota = source[source.index("ota:\n  - platform: http_request") :]
        ota = ota[: ota.index("\nsafe_mode:")]
        self.assertIn(f"id({FLAG}) = false;", ota)
        self.assertIn("script.execute: show_home_page", ota)


if __name__ == "__main__":
    unittest.main()
