"""What one panel reports, and what Home Assistant asks it to do.

This module deliberately has no Home Assistant imports, so the settings, the
command channel, and the validation of a status report can all be tested
without a Home Assistant runtime. The entities that expose them live in
`number.py`, `switch.py`, `button.py`, `sensor.py`, and `binary_sensor.py`;
the endpoint a panel reports to lives in `status.py`.

A panel polls; nothing can be pushed to it. Two ideas follow from that:

* **Settings** are a desired configuration. They travel in the config sensor
  and the panel adopts whatever it last read, so they need no acknowledgement.
* **Commands** are moments — turn the display off, restart the application.
  Each carries the millisecond timestamp at which it was issued, and a panel
  acts on one only when that timestamp is newer than the last it applied. The
  timestamp is what makes the channel safe over a poll: a command is applied
  once, a panel that was off while it was issued still sees it, and a panel
  that restarts does not replay the command that restarted it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import time
from typing import Any
from urllib.parse import urlsplit

# Every bound below is the one the panel itself clamps to. They are repeated
# here so that a number entity cannot offer a value the tablet would silently
# refuse, which would leave Home Assistant showing something untrue.
POLL_INTERVAL_MIN_MS = 500
POLL_INTERVAL_MAX_MS = 30000
PLAYLIST_POLL_INTERVAL_MIN_MS = 10000
PLAYLIST_POLL_INTERVAL_MAX_MS = 3600000
# 0 disables the automatic screen off entirely; anything else is clamped into
# the range the button handler accepts.
SCREEN_OFF_MIN_SECONDS = 5
SCREEN_OFF_MAX_SECONDS = 3600
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 100

DEFAULT_POLL_INTERVAL_MS = 1000
DEFAULT_PLAYLIST_POLL_INTERVAL_MS = 60000
DEFAULT_SCREEN_OFF_SECONDS = 30

# A panel is considered present while a report arrived within this many
# seconds. It reports every minute, so two missed reports mark it offline.
REPORT_TIMEOUT_SECONDS = 180.0

# Keys of the stored settings record and of the payload a panel reads. They
# appear in config entries on disk and in the client contract, so they may not
# be renamed casually.
SETTING_POLL_INTERVAL = "poll_interval_ms"
SETTING_PLAYLIST_POLL_INTERVAL = "playlist_poll_interval_ms"
SETTING_SCREEN_OFF = "screen_off_seconds"
SETTING_PLAYER_SKIN = "player_skin"

# How a client draws itself. The names are the client's own — the tablet has
# two and the ESP32 three, and neither would know what to do with the other's
# — so the vocabulary lives on the client profile and this module only checks
# the shape. An empty value means Home Assistant has not chosen: the key is
# then left out of the payload and the client keeps whatever it falls back to
# on its own, `config.ini` on the tablet and a restoring select on the ESP32.
PLAYER_SKIN_UNSET = ""
PLAYER_SKIN_MAX_LENGTH = 32

DISPLAY_ON = "on"
DISPLAY_OFF = "off"

# The address of the layout editor a panel serves on its own hardware. It is
# reported rather than derived: the port is the client's to choose, a panel
# that has the editor switched off has no address at all, and the panel
# already knows which of its own interfaces a phone can reach it on.
#
# It is checked here rather than passed to the device registry as it arrives.
# The registry refuses a scheme it does not know by raising, so an unusable
# value would turn one malformed report into a failed report instead of an
# ignored field.
EDITOR_URL_MAX_LENGTH = 255
EDITOR_URL_SCHEMES = ("http", "https")

# The pages a panel can be sent to. They are the names the T560 application
# gives its own stack children, and a page this list does not know is refused
# here rather than sent to a client that would ignore it.
PAGE_PLAYER = "player"
PAGE_QUEUE = "queue"
PAGE_PLAYLISTS = "playlists"
PAGE_ROOM = "room"
PAGES: tuple[str, ...] = (PAGE_PLAYER, PAGE_QUEUE, PAGE_PLAYLISTS, PAGE_ROOM)

# Bounds a reported diagnostic has to fall inside to be believed. Both are
# generous: they exist to reject a parse that went wrong on the tablet, not to
# judge the reading.
WIFI_MIN_DBM = -120
WIFI_MAX_DBM = 0
TEMPERATURE_MIN_C = -50.0
TEMPERATURE_MAX_C = 150.0

# An uptime is republished only when the start time it implies moves by more
# than this. Every report would otherwise shift it by a second or two, purely
# from rounding and network delay, and the sensor would never sit still.
UPTIME_TOLERANCE_SECONDS = 15.0


def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    """Return an integer inside the bounds, or the fallback when unusable."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(number, maximum))


def _percent(value: Any) -> int:
    """Read a reported percentage, using -1 for a value that is not one."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return -1
    return number if 0 <= number <= 100 else -1


def _player_skin(value: Any) -> str:
    """Read the requested skin, checking its shape and not its meaning.

    Which names are real is the client profile's business; the select entity
    offers only what its own client draws. Anything that could not be a layout
    name at all is dropped here so that a hand-edited config entry cannot put
    nonsense into the payload every client then has to defend against.
    """
    if not isinstance(value, str):
        return PLAYER_SKIN_UNSET
    skin = value.strip().lower()
    if not skin or len(skin) > PLAYER_SKIN_MAX_LENGTH:
        return PLAYER_SKIN_UNSET
    if not all(character.isalnum() or character in "_-" for character in skin):
        return PLAYER_SKIN_UNSET
    return skin


def _editor_url(value: Any) -> str:
    """Read the editor address a panel serves, using "" for none.

    Only the shape is checked, and deliberately narrowly: an ordinary
    `http` or `https` address of a host, with nothing in front of it. A panel
    reports where its own editor answers, and that is the whole of what this
    field may become — anything else would be a link Home Assistant offers to
    click on the strength of one HTTP request.
    """
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or len(url) > EDITOR_URL_MAX_LENGTH:
        return ""
    if any(character.isspace() for character in url):
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme not in EDITOR_URL_SCHEMES or not parsed.hostname:
        return ""
    # Credentials in the address would be stored in the device registry and
    # shown to anybody who opens the device page.
    if "@" in parsed.netloc:
        return ""
    return url


def _flag(value: Any) -> bool:
    """Read a reported boolean without trusting its type."""
    return value is True


def _contract_version(value: Any) -> int:
    """Read the contract version a client claims, using 0 for none.

    What the number means — which version is current, and what an older one
    should lead to — belongs to `contract.py`. All that happens here is
    reading it out of a report that cannot be trusted to carry one: a panel
    built before the field existed sends nothing at all.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    number = int(value)
    return number if number > 0 else 0


def _bounded(value: Any, minimum: float, maximum: float) -> float | None:
    """Read a reported measurement, using None for one that is not usable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if minimum <= value <= maximum else None


def now_ms() -> int:
    """Return the timestamp a command is issued at."""
    return int(time.time() * 1000)


def _subscribe(
    listeners: list[Callable[[], None]],
    listener: Callable[[], None],
) -> Callable[[], None]:
    """Add a listener and return the function that removes it again."""
    listeners.append(listener)

    def remove() -> None:
        if listener in listeners:
            listeners.remove(listener)

    return remove


@dataclass(frozen=True, slots=True)
class PanelSettings:
    """The tablet-local settings Home Assistant owns.

    They used to live in `config.ini` on the tablet, which meant editing a
    file over SSH. The file still holds them, as the fallback a panel starts
    from before it has read Home Assistant even once.
    """

    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS
    playlist_poll_interval_ms: int = DEFAULT_PLAYLIST_POLL_INTERVAL_MS
    screen_off_seconds: int = DEFAULT_SCREEN_OFF_SECONDS
    player_skin: str = PLAYER_SKIN_UNSET

    @classmethod
    def from_stored(cls, stored: Mapping[str, Any] | None) -> PanelSettings:
        """Read the settings of a config entry, repairing bad values."""
        source = stored or {}
        return cls(
            poll_interval_ms=_clamp(
                source.get(SETTING_POLL_INTERVAL),
                POLL_INTERVAL_MIN_MS,
                POLL_INTERVAL_MAX_MS,
                DEFAULT_POLL_INTERVAL_MS,
            ),
            playlist_poll_interval_ms=_clamp(
                source.get(SETTING_PLAYLIST_POLL_INTERVAL),
                PLAYLIST_POLL_INTERVAL_MIN_MS,
                PLAYLIST_POLL_INTERVAL_MAX_MS,
                DEFAULT_PLAYLIST_POLL_INTERVAL_MS,
            ),
            screen_off_seconds=_screen_off(source.get(SETTING_SCREEN_OFF)),
            player_skin=_player_skin(source.get(SETTING_PLAYER_SKIN)),
        )

    def with_value(self, key: str, value: Any) -> PanelSettings:
        """Return these settings with one key replaced and re-validated."""
        stored = dict(self.as_stored())
        stored[key] = value
        return PanelSettings.from_stored(stored)

    def as_stored(self) -> dict[str, Any]:
        """Return the config-entry representation of these settings."""
        return {
            SETTING_POLL_INTERVAL: self.poll_interval_ms,
            SETTING_PLAYLIST_POLL_INTERVAL: self.playlist_poll_interval_ms,
            SETTING_SCREEN_OFF: self.screen_off_seconds,
            SETTING_PLAYER_SKIN: self.player_skin,
        }

    def as_payload(self) -> dict[str, Any]:
        """Return what a panel reads from its config sensor.

        A skin nobody has chosen is left out rather than sent as an empty
        string, so a client that has never been configured keeps its own
        fallback instead of being handed a name it would have to reject.
        """
        payload = self.as_stored()
        if not self.player_skin:
            payload.pop(SETTING_PLAYER_SKIN, None)
        return payload


def _screen_off(value: Any) -> int:
    """Read the screen-off timeout, where 0 means never."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SCREEN_OFF_SECONDS
    if seconds <= 0:
        return 0
    return max(SCREEN_OFF_MIN_SECONDS, min(seconds, SCREEN_OFF_MAX_SECONDS))


@dataclass(frozen=True, slots=True)
class PanelCommands:
    """The moments a panel has been asked to act on.

    Every timestamp is milliseconds since the epoch. A zero means the command
    has never been issued in this Home Assistant run, and the panel then has
    nothing to compare against and does nothing.
    """

    display_state: str = ""
    display_at: int = 0
    brightness: int = 0
    brightness_at: int = 0
    restart_at: int = 0
    page: str = ""
    page_at: int = 0

    def as_payload(self) -> dict[str, Any]:
        """Return the command block of the config sensor.

        A command that was never issued is omitted rather than sent as a zero,
        so the attribute stays empty on a panel nobody has touched.
        """
        payload: dict[str, Any] = {}
        if self.display_at:
            payload["display"] = {
                "state": self.display_state,
                "at": self.display_at,
            }
        if self.brightness_at:
            payload["brightness"] = {
                "value": self.brightness,
                "at": self.brightness_at,
            }
        if self.restart_at:
            payload["restart"] = {"at": self.restart_at}
        if self.page_at:
            payload["page"] = {"value": self.page, "at": self.page_at}
        return payload


@dataclass(frozen=True, slots=True)
class PanelStatus:
    """The last report one panel sent about itself.

    Every field has a value that means "not reported": -1 for a percentage,
    False for a flag. A panel that has never reported is simply all of them,
    which is what makes the entities unavailable rather than wrong.
    """

    battery_percent: int = -1
    battery_charging: bool = False
    display_on: bool = False
    display_known: bool = False
    brightness: int = -1
    app_version: str = ""
    # Where the editor this panel serves answers, and "" for a panel that
    # serves none. It becomes the link on the panel's device page.
    editor_url: str = ""
    # The protocol the client says it speaks, and 0 for one that says
    # nothing. `app_version` is a release number and answers a different
    # question: it says when this build shipped, not what it understands.
    contract_version: int = 0
    page: str = ""
    uptime_seconds: float | None = None
    wifi_dbm: float | None = None
    temperature_c: float | None = None

    @classmethod
    def from_report(cls, report: Mapping[str, Any]) -> PanelStatus:
        """Read one status report, ignoring anything malformed.

        The report comes from the tablet over HTTP. It is validated here
        rather than trusted, so a panel running an older or a broken build
        cannot put a nonsense value into a Home Assistant sensor.
        """
        battery = report.get("battery")
        battery = battery if isinstance(battery, Mapping) else {}
        display = report.get("display")
        display = display if isinstance(display, Mapping) else {}

        percent = _percent(battery.get("percent"))
        if not _flag(battery.get("available")):
            percent = -1

        page = str(report.get("page") or "")
        uptime = report.get("uptime_seconds")
        if isinstance(uptime, bool) or not isinstance(uptime, (int, float)):
            uptime = None
        elif uptime < 0:
            uptime = None

        return cls(
            battery_percent=percent,
            battery_charging=percent >= 0 and _flag(battery.get("charging")),
            display_on=_flag(display.get("on")),
            display_known=_flag(display.get("available")),
            brightness=_percent(display.get("brightness")),
            app_version=str(report.get("version") or "")[:32],
            editor_url=_editor_url(report.get("editor_url")),
            contract_version=_contract_version(report.get("contract_version")),
            page=page if page in PAGES else "",
            uptime_seconds=None if uptime is None else float(uptime),
            wifi_dbm=_bounded(report.get("wifi_dbm"), WIFI_MIN_DBM,
                              WIFI_MAX_DBM),
            temperature_c=_bounded(report.get("temperature_c"),
                                   TEMPERATURE_MIN_C, TEMPERATURE_MAX_C),
        )


class PanelState:
    """Everything Home Assistant knows and asks about one panel.

    The entities, the config sensor, and the status endpoint all read and
    write through this object; none of them talks to another directly. It is
    deliberately free of Home Assistant types so that the rules above can be
    tested on their own.
    """

    def __init__(self, settings: PanelSettings | None = None) -> None:
        """Initialize with the settings stored on the config entry."""
        self.settings = settings or PanelSettings()
        self.commands = PanelCommands()
        self.status = PanelStatus()
        # Monotonic, for deciding whether the panel is still present.
        self.reported_at: float | None = None
        # Wall-clock seconds; the two timestamp sensors need a real date, not
        # a monotonic one.
        self.reported_wall_at: float | None = None
        self.started_at: float | None = None
        self._listeners: list[Callable[[], None]] = []
        self._config_listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to any change; returns the function that unsubscribes."""
        return _subscribe(self._listeners, listener)

    def add_config_listener(
        self,
        listener: Callable[[], None],
    ) -> Callable[[], None]:
        """Subscribe to the part of this state a panel actually reads.

        The config sensor uses this rather than `add_listener`. A report from
        the tablet, or the timer that decides whether the last one is still
        recent, changes nothing the panel needs to be told, and re-writing an
        identical payload every half minute would put a state change in the
        event bus for nothing.
        """
        return _subscribe(self._config_listeners, listener)

    def notify(self) -> None:
        """Tell every entity to re-read this state.

        Called on its own by the presence timer: nothing here changed, but
        whether the last report is still recent enough to believe did.
        """
        for listener in list(self._listeners):
            listener()

    def _notify_configuration(self) -> None:
        """Tell the entities and the panel that its configuration moved."""
        self.notify()
        for listener in list(self._config_listeners):
            listener()

    # ------------------------------------------------------------- settings

    def set_setting(self, key: str, value: Any) -> PanelSettings:
        """Change one setting and return the new set, for storing."""
        updated = self.settings.with_value(key, value)
        if updated != self.settings:
            self.settings = updated
            self._notify_configuration()
        return self.settings

    # ------------------------------------------------------------- commands

    def request_display(self, on: bool, *, at: int | None = None) -> None:
        """Ask the panel to turn its display on or off."""
        self.commands = replace(
            self.commands,
            display_state=DISPLAY_ON if on else DISPLAY_OFF,
            display_at=now_ms() if at is None else at,
        )
        # The switch reports what the panel last confirmed, so the optimistic
        # value is recorded here too; the next report overrules it.
        self.status = replace(self.status, display_on=on, display_known=True)
        self._notify_configuration()

    def request_brightness(self, percent: int, *, at: int | None = None) -> None:
        """Ask the panel to set its backlight brightness."""
        value = _clamp(percent, BRIGHTNESS_MIN, BRIGHTNESS_MAX, BRIGHTNESS_MAX)
        self.commands = replace(
            self.commands,
            brightness=value,
            brightness_at=now_ms() if at is None else at,
        )
        self.status = replace(self.status, brightness=value)
        self._notify_configuration()

    def request_restart(self, *, at: int | None = None) -> None:
        """Ask the panel to restart its application."""
        self.commands = replace(
            self.commands, restart_at=now_ms() if at is None else at
        )
        self._notify_configuration()

    def request_page(self, page: str, *, at: int | None = None) -> bool:
        """Ask the panel to show one of its pages.

        Returns whether the page is one a client knows. An unknown name is
        refused here rather than sent, because a client that does not
        recognise it would silently do nothing and the select entity would
        then show a page the tablet is not on.
        """
        if page not in PAGES:
            return False
        self.commands = replace(
            self.commands, page=page, page_at=now_ms() if at is None else at
        )
        self.status = replace(self.status, page=page)
        self._notify_configuration()
        return True

    # --------------------------------------------------------------- status

    def apply_report(
        self,
        report: Mapping[str, Any],
        *,
        now: float | None = None,
        wall: float | None = None,
    ) -> None:
        """Record what a panel just said about itself."""
        self.status = PanelStatus.from_report(report)
        self.reported_at = time.monotonic() if now is None else now
        self.reported_wall_at = time.time() if wall is None else wall
        self._record_started_at(
            self.status.uptime_seconds, self.reported_wall_at
        )
        self.notify()

    def is_online(self, *, now: float | None = None) -> bool:
        """Return whether a report arrived recently enough to be believed."""
        if self.reported_at is None:
            return False
        current = time.monotonic() if now is None else now
        return current - self.reported_at < REPORT_TIMEOUT_SECONDS

    def _record_started_at(self, uptime: float | None, wall: float) -> None:
        """Remember when the panel application started.

        The tablet reports how long it has been running, and the interesting
        fact is the moment it started: that stays still while the application
        does, and moving means it restarted. Every report would shift it by a
        second or two through rounding and network delay, so a small drift is
        treated as the same start.
        """
        if uptime is None:
            self.started_at = None
            return
        started_at = wall - uptime
        if (
            self.started_at is None
            or abs(started_at - self.started_at) > UPTIME_TOLERANCE_SECONDS
        ):
            self.started_at = started_at

    # -------------------------------------------------------------- payload

    def as_payload(self) -> dict[str, Any]:
        """Return the settings and commands block of the config sensor."""
        return {
            "settings": self.settings.as_payload(),
            "commands": self.commands.as_payload(),
        }
