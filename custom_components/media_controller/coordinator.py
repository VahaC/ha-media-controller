"""Queue and playlist synchronization coordinators."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import PLAYLIST_REFRESH_INTERVAL, QUEUE_REFRESH_DELAY
from .music_assistant import MusicAssistantAdapter, MusicAssistantUnavailable
from .transformations import PlaylistPayload, QueuePayload

_LOGGER = logging.getLogger(__name__)


class PlaylistCoordinator(DataUpdateCoordinator[PlaylistPayload]):
    """Refresh playlists on setup and every six hours."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        adapter: MusicAssistantAdapter,
    ) -> None:
        """Initialize the playlist coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} playlists",
            update_interval=PLAYLIST_REFRESH_INTERVAL,
            always_update=False,
        )
        self.adapter = adapter

    async def _async_update_data(self) -> PlaylistPayload:
        """Fetch and transform playlists."""
        try:
            return await self.adapter.async_get_playlists()
        except MusicAssistantUnavailable as err:
            raise UpdateFailed(str(err)) from err
        except (TimeoutError, ConnectionError) as err:
            raise UpdateFailed("Music Assistant playlist request failed") from err
        except Exception as err:
            _LOGGER.exception("Unexpected Music Assistant playlist refresh error")
            raise UpdateFailed("Unexpected playlist refresh error") from err


class QueueCoordinator(DataUpdateCoordinator[QueuePayload]):
    """Refresh a bounded queue after debounced player title changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        adapter: MusicAssistantAdapter,
    ) -> None:
        """Initialize the queue coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} queue",
            update_interval=None,
            always_update=False,
        )
        self.adapter = adapter
        self._generation = 0
        self._refresh_lock = asyncio.Lock()
        self._delayed_refresh_task: asyncio.Task[None] | None = None
        self._remove_player_listener: Callable[[], None] | None = None

    @callback
    def async_start(self) -> None:
        """Start listening for meaningful player state changes."""
        if self._remove_player_listener is not None:
            return
        self._remove_player_listener = async_track_state_change_event(
            self.hass,
            [self.adapter.player_entity_id],
            self._async_player_state_changed,
        )

    @callback
    def _async_player_state_changed(self, event: Event) -> None:
        """Debounce queue refreshes when the media title changes."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        old_title = old_state.attributes.get("media_title") if old_state else None
        new_title = new_state.attributes.get("media_title") if new_state else None
        if old_title == new_title:
            return
        self.async_schedule_delayed_refresh()

    @callback
    def async_schedule_delayed_refresh(self) -> None:
        """Cancel an obsolete delay and schedule the latest queue refresh."""
        self._generation += 1
        generation = self._generation
        if (
            self._delayed_refresh_task is not None
            and not self._delayed_refresh_task.done()
        ):
            self._delayed_refresh_task.cancel()
        self._delayed_refresh_task = self.hass.async_create_task(
            self._async_delayed_refresh(generation),
            f"{self.config_entry.title} delayed queue refresh",
        )

    async def _async_delayed_refresh(self, generation: int) -> None:
        """Wait for Music Assistant to advance, then refresh once."""
        try:
            await asyncio.sleep(QUEUE_REFRESH_DELAY)
            if generation == self._generation:
                # Do not let a later title change cancel an API request that has
                # already started; only obsolete waiting periods are cancelled.
                self._delayed_refresh_task = None
                await self.async_request_refresh()
        except asyncio.CancelledError:
            return

    async def _async_update_data(self) -> QueuePayload:
        """Fetch a bounded queue while preventing overlapping requests."""
        generation = self._generation
        async with self._refresh_lock:
            try:
                payload = await self.adapter.async_get_queue()
            except MusicAssistantUnavailable as err:
                raise UpdateFailed(str(err)) from err
            except (TimeoutError, ConnectionError) as err:
                raise UpdateFailed("Music Assistant queue request failed") from err
            except Exception as err:
                _LOGGER.exception("Unexpected Music Assistant queue refresh error")
                raise UpdateFailed("Unexpected queue refresh error") from err

        if generation != self._generation and self.data is not None:
            return self.data
        return payload

    async def async_shutdown(self) -> None:
        """Remove the listener and cancel the pending debounce timer."""
        if self._remove_player_listener is not None:
            self._remove_player_listener()
            self._remove_player_listener = None
        if (
            self._delayed_refresh_task is not None
            and not self._delayed_refresh_task.done()
        ):
            self._delayed_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._delayed_refresh_task
        self._delayed_refresh_task = None
        await super().async_shutdown()
