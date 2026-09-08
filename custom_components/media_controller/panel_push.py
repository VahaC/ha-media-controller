"""Sending a panel the two states it used to ask for.

A paired panel read the player and its own config sensor by polling, once a
second each, over a synchronous HTTP client. On the ESP32-S3 panel that is not
a background cost: its display is an RGB panel the processor refreshes itself
out of PSRAM, the refill interrupt sits on the core the main loop runs on, and
a request holds that core long enough for the refresh to miss. What a person
sees is the picture jumping, twice a second, for a player that is usually
paused and a configuration that usually has not changed. See
`components/media_controller_push/media_controller_push.h` for the mechanism in
full.

So the two payloads travel the other way here. Home Assistant watches the same
two states and posts them to the panel when they actually change; the polls
stay behind them, slowed to a heartbeat, as the thing that notices delivery has
stopped.

## What this module will and will not do

- it pushes **only** to a panel that has reported a `push_key`. That key is
  minted on the device and repeated in every status report, so a panel running
  an older build, or one that is no longer paired, reports none and is left
  polling exactly as it was. There is no version test here and there does not
  need to be: the key is the capability;
- it never retries. A push that does not arrive is a payload the panel's own
  fallback poll will ask for within the half minute, and a queue of retries
  aimed at a panel that is rebooting or off the network would arrive as a
  burst against the one thing this change exists to protect;
- it sends the shape the panel already knows -- `state` and `attributes`, as
  `/api/states/<entity>` returns them -- because the firmware hands a push to
  the same parser it hands a poll response to. One document, one reading of
  it, on both sides.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from urllib.parse import urlsplit

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.json import json_dumps

from .const import CONF_HOST, CONF_PANEL_PORT, DEFAULT_PANEL_PORT
from .panel_provision import async_config_entity_id
from .panel_state import PanelState

_LOGGER = logging.getLogger(__name__)

PLAYER_PATH = "/api/push/player"
CONFIG_PATH = "/api/push/config"
KEY_HEADER = "X-Panel-Push-Key"

# Short, because the panel answers before it parses: this waits for a socket
# and a 202, not for a screen to be redrawn. A panel that cannot answer in this
# long is one the fallback poll should be covering anyway.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=4)

# A player moves several attributes at once -- position, title, artwork -- and
# Home Assistant reports them as separate state changes when the source
# updates them separately. Coalescing them costs a fifth of a second of
# latency and saves the panel a second and a third parse of the same track.
DEBOUNCE_SECONDS = 0.2


class PanelPusher:
    """Watches two states and posts them to one panel."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        state: PanelState,
    ) -> None:
        """Prepare a pusher; nothing is watched until `async_start`."""
        self._hass = hass
        self._entry = entry
        self._state = state
        self._config_entity = ""
        self._player_entity = ""
        self._cancel_config: Callable[[], None] | None = None
        self._cancel_player: Callable[[], None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._pending: dict[str, asyncio.TimerHandle] = {}
        # Why the last delivery was not attempted, so that the reason is
        # logged when it changes and not once per state change. Every skip
        # below is a silent no-op otherwise, and a push that never happens
        # looks exactly like a push that happened and did nothing.
        self._last_skip = ""

    # ------------------------------------------------------------ lifecycle

    @callback
    def async_start(self) -> bool:
        """Begin watching, returning whether there was anything to watch.

        False means this panel's config sensor does not exist yet, which is
        the ordinary state of a panel being set up for the first time. The
        caller does not have to treat it as a failure: the panel polls, and
        the next reload finds the sensor.
        """
        self._config_entity = async_config_entity_id(self._hass, self._entry)
        if not self._config_entity:
            # Said out loud rather than returned quietly. A pusher that never
            # started logs none of the reasons below either, so silence in the
            # log would otherwise be indistinguishable from everything working
            # -- and it is the opposite.
            _LOGGER.warning(
                "No config sensor for panel %s yet, so nothing will be "
                "pushed to it and it will go on polling; this clears itself "
                "on the next reload once the sensor exists",
                self._entry.title,
            )
            return False

        self._cancel_config = async_track_state_change_event(
            self._hass, [self._config_entity], self._async_config_changed
        )
        # The player is named inside the config payload, so the first
        # subscription to it comes from reading what is already there rather
        # than from waiting for the payload to change.
        self._async_follow_player()
        return True

    @callback
    def async_stop(self) -> None:
        """Stop watching and drop anything still in flight."""
        if self._cancel_config is not None:
            self._cancel_config()
            self._cancel_config = None
        if self._cancel_player is not None:
            self._cancel_player()
            self._cancel_player = None
        for handle in self._pending.values():
            handle.cancel()
        self._pending.clear()
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    # ------------------------------------------------------------ listeners

    @callback
    def _async_config_changed(self, event: Event) -> None:
        """The panel's own configuration moved."""
        # The player entity is part of that payload, so a config change is
        # also where this device learns it is now watching a different player.
        self._async_follow_player()
        self._async_schedule(CONFIG_PATH, self._config_entity)

    @callback
    def _async_player_changed(self, event: Event) -> None:
        """The player the panel is drawing moved."""
        self._async_schedule(PLAYER_PATH, self._player_entity)

    @callback
    def _async_follow_player(self) -> None:
        """Subscribe to whichever player the config payload now names."""
        config = self._hass.states.get(self._config_entity)
        player = ""
        if config is not None:
            named = config.attributes.get("player")
            if isinstance(named, str):
                player = named
        if player == self._player_entity:
            return

        if self._cancel_player is not None:
            self._cancel_player()
            self._cancel_player = None
        self._player_entity = player
        if not player:
            return
        self._cancel_player = async_track_state_change_event(
            self._hass, [player], self._async_player_changed
        )

    # ------------------------------------------------------------- delivery

    @callback
    def _async_schedule(self, path: str, entity_id: str) -> None:
        """Send this payload after the debounce, replacing any waiting one."""
        if not entity_id:
            return
        waiting = self._pending.pop(path, None)
        if waiting is not None:
            waiting.cancel()

        @callback
        def _fire() -> None:
            self._pending.pop(path, None)
            self._async_send(path, entity_id)

        self._pending[path] = self._hass.loop.call_later(
            DEBOUNCE_SECONDS, _fire
        )

    @callback
    def _async_send(self, path: str, entity_id: str) -> None:
        """Start one delivery, if this panel is one that accepts them."""
        key = self._state.status.push_key
        if not key:
            # No key reported: an older build, or one that is not paired.
            # It polls, and that is a complete answer rather than a problem
            # -- but it is worth saying once, because it is also what a panel
            # that was meant to accept pushes looks like when it does not.
            self._async_skip(
                "no_key",
                "Panel %s reported no push key, so it is being left to poll",
                self._entry.title,
            )
            return
        origin = self._async_origin()
        if not origin:
            self._async_skip(
                "no_address",
                "No address for panel %s: the config entry carries no host "
                "and no editor URL has been reported, so nothing can be "
                "pushed to it",
                self._entry.title,
            )
            return
        current = self._hass.states.get(entity_id)
        if current is None:
            self._async_skip(
                "no_state", "No state to push for %s", entity_id
            )
            return

        if self._last_skip:
            _LOGGER.info(
                "Pushing to panel %s again", self._entry.title
            )
            self._last_skip = ""

        # Only the two fields the firmware reads. `State.as_dict()` would also
        # carry the context and both timestamps, which is a few hundred bytes
        # of nothing on a payload this device parses by hand.
        body = json_dumps(
            {"state": current.state, "attributes": dict(current.attributes)}
        )
        url = f"{origin}{path}"
        task = self._entry.async_create_background_task(
            self._hass,
            self._async_post(url, key, body),
            name=f"media_controller push {path}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @callback
    def _async_origin(self) -> str:
        """Return where this panel answers, or "" when that is not known.

        The config entry carries a host only for a panel Home Assistant found
        over zeroconf; a panel added any other way has an empty one, and
        pushing to it would be pushing at nothing. So the address the panel
        reports for its own editor is the fallback: it is the panel's own
        routable address, it is the one thing on the network that knows which
        interface that is, and it arrives in every status report.

        The port is taken with it. The editor and these routes are the same
        listener on the same device -- a panel opens exactly one port -- so an
        address that reaches one reaches the other.
        """
        host = str(self._entry.data.get(CONF_HOST) or "")
        if host:
            port = int(
                self._entry.data.get(CONF_PANEL_PORT) or DEFAULT_PANEL_PORT
            )
            if port > 0:
                return f"http://{host}:{port}"

        reported = self._state.status.editor_url
        if not reported:
            return ""
        parts = urlsplit(reported)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return ""
        return f"{parts.scheme}://{parts.netloc}"

    @callback
    def _async_skip(self, reason: str, message: str, *args: object) -> None:
        """Say why nothing was sent, once per reason rather than per change.

        At warning level deliberately. Every one of these means the panel is
        polling when this integration believed it would not have to, and a
        panel that polls is the problem this module exists to remove -- so it
        is not something to leave at debug for somebody to go looking for.
        """
        if self._last_skip == reason:
            return
        self._last_skip = reason
        _LOGGER.warning(message, *args)

    async def _async_post(self, url: str, key: str, body: str) -> None:
        """Deliver one payload, or let the panel's fallback poll cover it."""
        session = async_get_clientsession(self._hass)
        try:
            async with session.post(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    KEY_HEADER: key,
                },
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status == 403:
                    # The key moved: the panel was re-paired, or restored a
                    # different one. The next status report carries the new
                    # one and pushes resume by themselves, so this is logged
                    # and not acted on.
                    _LOGGER.debug("Panel at %s refused a push key", url)
                elif response.status >= 400:
                    _LOGGER.debug(
                        "Panel at %s answered %s to a push",
                        url,
                        response.status,
                    )
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug("No answer from the panel at %s", url)
        except asyncio.CancelledError:
            raise


@callback
def async_start_push(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: PanelState,
) -> Callable[[], None] | None:
    """Start pushing to one panel, returning what stops it again."""
    pusher = PanelPusher(hass, entry, state)
    if not pusher.async_start():
        return None
    _LOGGER.debug("Watching states to push to panel %s", entry.title)
    return pusher.async_stop
