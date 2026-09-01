#!/usr/bin/python3

"""Handle the physical Power and Home buttons without blocking the GTK app.

The handler also owns DPMS for the motion detector: SIGUSR2 from
t560-motion-detector.py turns the display on and postpones the automatic
screen off while the camera keeps seeing movement.
"""

import configparser
import ctypes
import os
import select
import signal
import subprocess
import sys
import time


KEY_PRESS = 2
KEY_RELEASE = 3
KEY_PRESS_MASK = 1 << 0
KEY_RELEASE_MASK = 1 << 1
BUTTON_PRESS = 4
BUTTON_RELEASE = 5
BUTTON_PRESS_MASK = 1 << 2
BUTTON_RELEASE_MASK = 1 << 3
GRAB_MODE_ASYNC = 1
GRAB_SUCCESS = 0
ANY_MODIFIER = 1 << 15
XF86_POWER_OFF = 0x1008FF2A
XK_HOME = 0xFF50
XF86_HOME_PAGE = 0x1008FF18
DPMS_MODE_ON = 0
DPMS_MODE_OFF = 3
SCREEN_SAVER_RESET = 0
LONG_PRESS_SECONDS = 1.5
POLL_SECONDS = 0.5
TOUCH_GRAB_SECONDS = 3.0
CONFIG_FILE = "~/.config/t560-music-panel/config.ini"
DEFAULT_SCREEN_OFF_SECONDS = 30
MIN_SCREEN_OFF_SECONDS = 5
MAX_SCREEN_OFF_SECONDS = 3600
DEFAULT_MOTION_WAKE_GRACE_SECONDS = 30
MIN_MOTION_WAKE_GRACE_SECONDS = 0
MAX_MOTION_WAKE_GRACE_SECONDS = 600
# The backlight itself changes what the camera sees. Motion is ignored for
# this long after an automatic screen off so that the transition alone cannot
# turn the display back on.
MOTION_SETTLE_SECONDS = 2.0


class XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x_root", ctypes.c_int),
        ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("keycode", ctypes.c_uint),
        ("same_screen", ctypes.c_int),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xkey", XKeyEvent),
        ("pad", ctypes.c_long * 24),
    ]


class XScreenSaverInfo(ctypes.Structure):
    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("event_mask", ctypes.c_ulong),
    ]


x11 = None
xext = None
xss = None
display = None
root = 0
idle_info = None
pointer_grabbed = False
grab_failure = None
display_off_at = 0.0
display_off_manual = True


def log(message):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def screen_off_seconds(path=CONFIG_FILE):
    """Return the inactivity timeout in seconds; 0 disables automatic off."""
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.expanduser(path), encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error) as error:
        log(f"WARNING: could not read {path}: {error}")
        return DEFAULT_SCREEN_OFF_SECONDS

    value = parser.get("panel", "screen_off_seconds", fallback=None)
    if value is None:
        return DEFAULT_SCREEN_OFF_SECONDS

    try:
        seconds = int(value.strip())
    except ValueError:
        log(f"WARNING: screen_off_seconds is not an integer: {value.strip()!r}")
        return DEFAULT_SCREEN_OFF_SECONDS

    if seconds <= 0:
        return 0
    return min(max(seconds, MIN_SCREEN_OFF_SECONDS), MAX_SCREEN_OFF_SECONDS)


def motion_wake_grace_seconds(path=CONFIG_FILE):
    """Return how long motion is ignored after a deliberate screen off.

    Without the delay, the person who just pressed Power would immediately be
    detected by the motion daemon and would turn the display back on.
    """
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.expanduser(path), encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error) as error:
        log(f"WARNING: could not read {path}: {error}")
        return DEFAULT_MOTION_WAKE_GRACE_SECONDS

    value = parser.get("camera", "motion_wake_grace_seconds", fallback=None)
    if value is None:
        return DEFAULT_MOTION_WAKE_GRACE_SECONDS

    try:
        seconds = int(value.strip())
    except ValueError:
        log("WARNING: motion_wake_grace_seconds is not an integer: "
            f"{value.strip()!r}")
        return DEFAULT_MOTION_WAKE_GRACE_SECONDS

    return min(
        max(seconds, MIN_MOTION_WAKE_GRACE_SECONDS),
        MAX_MOTION_WAKE_GRACE_SECONDS,
    )


def load_x_libraries():
    """Load libX11 and libXext and declare the prototypes used below."""
    global x11, xext

    x11 = ctypes.CDLL("libX11.so.6")
    xext = ctypes.CDLL("libXext.so.6")

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte
    x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
    x11.XGrabKey.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    x11.XGrabPointer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    x11.XGrabPointer.restype = ctypes.c_int
    x11.XUngrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XPending.argtypes = [ctypes.c_void_p]
    x11.XPending.restype = ctypes.c_int
    x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
    x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
    x11.XConnectionNumber.restype = ctypes.c_int
    x11.XForceScreenSaver.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XFlush.argtypes = [ctypes.c_void_p]

    xext.DPMSEnable.argtypes = [ctypes.c_void_p]
    xext.DPMSForceLevel.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
    xext.DPMSInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_int),
    ]


def enable_idle_detection():
    """Prepare the MIT-SCREEN-SAVER idle timer; return False when unavailable."""
    global xss, idle_info

    try:
        xss = ctypes.CDLL("libXss.so.1")
    except OSError as error:
        log(f"idle: libXss is unavailable ({error})")
        xss = None
        return False

    xss.XScreenSaverQueryExtension.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    xss.XScreenSaverAllocInfo.argtypes = []
    xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
    xss.XScreenSaverQueryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(XScreenSaverInfo),
    ]

    event_base = ctypes.c_int(0)
    error_base = ctypes.c_int(0)
    if not xss.XScreenSaverQueryExtension(
        display, ctypes.byref(event_base), ctypes.byref(error_base)
    ):
        log("idle: the X server has no MIT-SCREEN-SAVER extension")
        xss = None
        return False

    idle_info = xss.XScreenSaverAllocInfo()
    if not idle_info:
        log("idle: could not allocate the screen saver info structure")
        xss = None
        return False
    return True


def idle_seconds():
    """Return seconds since the last keyboard or touchscreen input."""
    if not xss.XScreenSaverQueryInfo(display, root, idle_info):
        return 0.0
    return idle_info.contents.idle / 1000.0


def reset_idle_timer():
    """Restart the X server inactivity countdown.

    Without libXss the server applies the screen-off timeout itself, so
    camera motion can only postpone it by resetting the server idle counter.
    """
    x11.XForceScreenSaver(display, SCREEN_SAVER_RESET)
    x11.XFlush(display)


def dpms_level():
    level = ctypes.c_ushort(DPMS_MODE_ON)
    enabled = ctypes.c_int(0)
    if xext.DPMSInfo(display, ctypes.byref(level), ctypes.byref(enabled)):
        return int(level.value)
    return DPMS_MODE_ON


def force_dpms(level):
    xext.DPMSForceLevel(display, level)
    x11.XFlush(display)


def grab_pointer():
    """Keep touch input away from the application while the display is off."""
    global pointer_grabbed, grab_failure

    if pointer_grabbed:
        return

    status = x11.XGrabPointer(
        display,
        root,
        0,
        BUTTON_PRESS_MASK | BUTTON_RELEASE_MASK,
        GRAB_MODE_ASYNC,
        GRAB_MODE_ASYNC,
        0,
        0,
        0,
    )
    x11.XFlush(display)
    if status == GRAB_SUCCESS:
        pointer_grabbed = True
        if grab_failure is not None:
            log("touch: pointer grab recovered")
            grab_failure = None
        return

    if status != grab_failure:
        log(f"WARNING: pointer grab failed with status {status}; "
            "a wake-up tap can reach the application")
        grab_failure = status


def ungrab_pointer():
    """Let touch input reach the application again."""
    global pointer_grabbed

    if not pointer_grabbed:
        return

    x11.XUngrabPointer(display, 0)
    x11.XFlush(display)
    pointer_grabbed = False


def wake_display():
    """Turn the backlight on and dispatch further input normally."""
    force_dpms(DPMS_MODE_ON)
    ungrab_pointer()


def note_display_off(manual):
    """Remember when and why the backlight turned off, for the motion wake."""
    global display_off_at, display_off_manual

    display_off_at = time.monotonic()
    display_off_manual = manual


def motion_wake_delay(manual_grace):
    """Return how long motion stays ignored after the current screen off."""
    return manual_grace if display_off_manual else MOTION_SETTLE_SECONDS


def blank_display(manual=False):
    """Swallow the wake-up tap, then turn the backlight off."""
    grab_pointer()
    force_dpms(DPMS_MODE_OFF)
    note_display_off(manual)


def run_xset(arguments):
    subprocess.run(
        ["xset", *arguments],
        env={**os.environ, "DISPLAY": ":0"},
        check=False,
    )


def toggle_desktop():
    result = subprocess.run(
        ["xdotool", "key", "--clearmodifiers", "Super+d"],
        env={**os.environ, "DISPLAY": ":0"},
        check=False,
    )
    if result.returncode:
        log(f"ERROR: desktop toggle failed with exit code {result.returncode}")
        return
    log("home: toggled application and desktop")


def main():
    global display, root

    load_x_libraries()

    display_name = os.environ.get("DISPLAY", ":0").encode()
    display = x11.XOpenDisplay(display_name)
    if not display:
        log("ERROR: could not open X display")
        sys.exit(1)

    root = x11.XDefaultRootWindow(display)
    keycode = int(x11.XKeysymToKeycode(display, XF86_POWER_OFF))
    if not keycode:
        log("ERROR: XF86PowerOff is not mapped")
        sys.exit(1)

    # Prevent synthetic X autorepeat from looking like multiple short presses.
    run_xset(["-r", str(keycode)])
    for home_keysym in (XK_HOME, XF86_HOME_PAGE):
        home_keycode = int(x11.XKeysymToKeycode(display, home_keysym))
        if home_keycode:
            run_xset(["-r", str(home_keycode)])

    auto_off_seconds = screen_off_seconds()
    motion_grace = motion_wake_grace_seconds()
    idle_detection = auto_off_seconds > 0 and enable_idle_detection()

    # This handler drives DPMS itself whenever the idle timer is readable.
    # Otherwise the X server applies the inactivity timeout on its own.
    server_off_timeout = 0 if idle_detection else auto_off_seconds
    run_xset(["dpms", "0", "0", str(server_off_timeout)])
    xext.DPMSEnable(display)
    x11.XSelectInput(display, root, KEY_PRESS_MASK | KEY_RELEASE_MASK)
    x11.XGrabKey(
        display,
        keycode,
        ANY_MODIFIER,
        root,
        0,
        GRAB_MODE_ASYNC,
        GRAB_MODE_ASYNC,
    )
    x11.XFlush(display)

    monitor_on = dpms_level() == DPMS_MODE_ON
    if not monitor_on:
        grab_pointer()
        note_display_off(manual=True)
    last_motion = None
    motion_hold = False
    grace_logged_at = None
    pressed = False
    press_started = 0.0
    woke_from_off = False
    long_fired = False
    wake_touch = False
    wake_touch_started = 0.0
    next_poll = time.monotonic() + POLL_SECONDS
    connection = x11.XConnectionNumber(display)
    event = XEvent()
    signal_read, signal_write = os.pipe()
    os.set_blocking(signal_read, False)
    os.set_blocking(signal_write, False)
    signal.set_wakeup_fd(signal_write)
    signal.signal(signal.SIGUSR1, lambda _signum, _frame: None)
    # The camera daemon reports motion with SIGUSR2.
    signal.signal(signal.SIGUSR2, lambda _signum, _frame: None)

    if auto_off_seconds == 0:
        auto_off_state = "disabled"
    elif idle_detection:
        auto_off_state = f"{auto_off_seconds}s idle timer"
    else:
        auto_off_state = f"{auto_off_seconds}s X server timeout"
    log(
        f"started: keycode={keycode}, monitor_on={monitor_on}, "
        f"auto screen off={auto_off_state}, "
        f"motion wake grace={motion_grace}s"
    )

    while True:
        now = time.monotonic()
        deadlines = [next_poll]
        if pressed and not long_fired:
            deadlines.append(press_started + LONG_PRESS_SECONDS)
        timeout = max(0.0, min(deadlines) - now)
        readable, _, _ = select.select([connection, signal_read], [], [], timeout)

        if signal_read in readable:
            try:
                pending = os.read(signal_read, 4096)
            except BlockingIOError:
                pending = b""

            for _ in range(pending.count(signal.SIGUSR1)):
                if monitor_on:
                    toggle_desktop()
                else:
                    wake_display()
                    monitor_on = True
                    log("home: woke display without toggling desktop")

            if pending.count(signal.SIGUSR2):
                # Motion counts as activity: it wakes the display and, while
                # it continues, postpones the automatic screen off below.
                now = time.monotonic()
                last_motion = now
                if monitor_on:
                    if not idle_detection:
                        reset_idle_timer()
                else:
                    if now - display_off_at >= motion_wake_delay(motion_grace):
                        wake_display()
                        if not idle_detection:
                            # The server timeout has already elapsed; without
                            # this reset it would blank the display again at
                            # once.
                            reset_idle_timer()
                        monitor_on = True
                        log("motion: backlight on")
                    elif grace_logged_at != display_off_at:
                        grace_logged_at = display_off_at
                        log("motion: ignored for "
                            f"{motion_wake_delay(motion_grace):.0f}s after "
                            "the backlight turned off")

        while x11.XPending(display):
            x11.XNextEvent(display, ctypes.byref(event))
            now = time.monotonic()

            if event.type == KEY_PRESS and int(event.xkey.keycode) == keycode:
                if not pressed:
                    woke_from_off = not monitor_on
                    if woke_from_off:
                        wake_display()
                        monitor_on = True
                    pressed = True
                    long_fired = False
                    press_started = now
                    log(f"press: woke_from_off={woke_from_off}")

            elif event.type == KEY_RELEASE and int(event.xkey.keycode) == keycode:
                if pressed:
                    duration = now - press_started
                    if not long_fired:
                        if woke_from_off:
                            wake_display()
                            monitor_on = True
                            log(f"short release ({duration:.2f}s): backlight on")
                        else:
                            blank_display(manual=True)
                            monitor_on = False
                            log(f"short release ({duration:.2f}s): backlight off")
                    else:
                        log(f"long release ({duration:.2f}s)")
                    pressed = False
                    woke_from_off = False

            elif event.type == BUTTON_PRESS and pointer_grabbed:
                wake_touch = True
                wake_touch_started = now
                force_dpms(DPMS_MODE_ON)
                monitor_on = True
                log("touch: woke the display without dispatching the tap")

            elif event.type == BUTTON_RELEASE and pointer_grabbed:
                # The grab is held for the whole touch sequence so that no part
                # of the wake-up tap is replayed to the application.
                wake_touch = False
                ungrab_pointer()

        now = time.monotonic()
        if pressed and not long_fired and now - press_started >= LONG_PRESS_SECONDS:
            wake_display()
            monitor_on = True
            subprocess.Popen(
                ["/home/vahac/.local/bin/t560-power-menu"],
                env={**os.environ, "DISPLAY": ":0"},
                start_new_session=True,
            )
            long_fired = True
            log("long press: opened power menu")

        if now >= next_poll:
            if not pressed:
                actual_on = dpms_level() == DPMS_MODE_ON
                if actual_on != monitor_on:
                    monitor_on = actual_on
                    if actual_on:
                        # The tap that woke the display may not be dequeued
                        # yet. Keep the grab until its release arrives.
                        if pointer_grabbed and not wake_touch:
                            wake_touch = True
                            wake_touch_started = now
                        log("wake: input turned backlight on")
                    else:
                        note_display_off(manual=True)
                        log("backlight turned off externally")

                if monitor_on and idle_detection:
                    idle = idle_seconds()
                    motion_recent = (last_motion is not None
                                     and now - last_motion < auto_off_seconds)
                    if idle < auto_off_seconds:
                        motion_hold = False
                    elif motion_recent:
                        if not motion_hold:
                            motion_hold = True
                            log(f"idle {idle:.1f}s: screen off postponed "
                                "while there is motion")
                    else:
                        motion_hold = False
                        blank_display()
                        monitor_on = False
                        log(f"idle {idle:.1f}s: backlight off")

                if not monitor_on:
                    grab_pointer()
                elif (not wake_touch or
                      now - wake_touch_started >= TOUCH_GRAB_SECONDS):
                    wake_touch = False
                    ungrab_pointer()
            next_poll = now + POLL_SECONDS


if __name__ == "__main__":
    main()
