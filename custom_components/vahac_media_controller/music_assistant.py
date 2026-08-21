"""Bounded access to the public Music Assistant client controllers."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    DEFAULT_PLAYLIST_LIMIT,
    DEFAULT_QUEUE_WINDOW_BEFORE,
    DEFAULT_QUEUE_WINDOW_SIZE,
)
from .transformations import (
    PlaylistPayload,
    QueuePayload,
    calculate_queue_offset,
    transform_playlists,
    transform_queue_items,
)

MUSIC_ASSISTANT_DOMAIN = "music_assistant"


class MusicAssistantUnavailable(RuntimeError):
    """Raised when the selected Music Assistant entry is not ready."""


def resolve_music_assistant_entry(
    hass: HomeAssistant,
    player_entity_id: str,
) -> tuple[ConfigEntry, str]:
    """Resolve the MA config entry and player ID from the entity registry."""
    registry_entry = er.async_get(hass).async_get(player_entity_id)
    if registry_entry is None:
        raise MusicAssistantUnavailable(
            f"Entity {player_entity_id} is not in the entity registry"
        )
    if registry_entry.platform != MUSIC_ASSISTANT_DOMAIN:
        raise MusicAssistantUnavailable(
            f"Entity {player_entity_id} is not provided by Music Assistant"
        )
    if not registry_entry.config_entry_id:
        raise MusicAssistantUnavailable(
            f"Entity {player_entity_id} has no Music Assistant config entry"
        )

    config_entry = hass.config_entries.async_get_entry(
        registry_entry.config_entry_id
    )
    if config_entry is None:
        raise MusicAssistantUnavailable(
            f"Music Assistant entry for {player_entity_id} was not found"
        )
    return config_entry, registry_entry.unique_id


class MusicAssistantAdapter:
    """Use the client already owned by the official HA integration.

    The Music Assistant integration does not expose bounded queue retrieval or
    queue-item playback as Home Assistant actions. Its public
    music-assistant-client dependency does expose both. Reusing the already
    connected client avoids a second connection and a second credential while
    keeping all queue payloads bounded.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        player_entity_id: str,
        music_assistant_entry_id: str,
        player_id: str,
    ) -> None:
        """Initialize the adapter."""
        self.hass = hass
        self.player_entity_id = player_entity_id
        self.music_assistant_entry_id = music_assistant_entry_id
        self.player_id = player_id

    @classmethod
    def from_player(
        cls,
        hass: HomeAssistant,
        player_entity_id: str,
    ) -> MusicAssistantAdapter:
        """Create an adapter from a configured MA media player entity."""
        entry, player_id = resolve_music_assistant_entry(hass, player_entity_id)
        return cls(hass, player_entity_id, entry.entry_id, player_id)

    def _client(self) -> Any:
        """Return the loaded public MusicAssistantClient instance."""
        entry = self.hass.config_entries.async_get_entry(
            self.music_assistant_entry_id
        )
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise MusicAssistantUnavailable("Music Assistant is not loaded")

        runtime_data = entry.runtime_data
        client = getattr(runtime_data, "mass", runtime_data)
        if (
            client is None
            or not hasattr(client, "music")
            or not hasattr(client, "player_queues")
        ):
            raise MusicAssistantUnavailable(
                "The loaded Music Assistant entry has no ready client"
            )
        return client

    async def async_get_playlists(
        self,
        limit: int = DEFAULT_PLAYLIST_LIMIT,
    ) -> PlaylistPayload:
        """Fetch a bounded playlist library."""
        if limit <= 0:
            return PlaylistPayload()
        client = self._client()
        items = await client.music.get_library_playlists(
            limit=limit,
            offset=0,
        )
        return transform_playlists(items, limit=limit)

    async def async_get_queue(
        self,
        *,
        window_before: int = DEFAULT_QUEUE_WINDOW_BEFORE,
        window_size: int = DEFAULT_QUEUE_WINDOW_SIZE,
    ) -> QueuePayload:
        """Fetch only the configured queue window around the current item."""
        if window_size <= 0:
            return QueuePayload()
        client = self._client()
        active_queue = await client.player_queues.get_active_queue(self.player_id)
        if active_queue is None:
            return QueuePayload()

        current_index = getattr(active_queue, "current_index", -1)
        offset = calculate_queue_offset(current_index, window_before)
        queue_id = getattr(active_queue, "queue_id", None)
        if not queue_id:
            return QueuePayload()

        items = await client.player_queues.get_queue_items(
            queue_id,
            limit=max(int(window_size), 0),
            offset=offset,
        )
        return transform_queue_items(
            items,
            global_current_index=current_index,
            offset=offset,
        )

    async def async_play_queue_item(self, queue_item_id: str) -> None:
        """Play a Music Assistant queue item by its stable queue item ID."""
        client = self._client()
        active_queue = await client.player_queues.get_active_queue(self.player_id)
        if active_queue is None or not getattr(active_queue, "queue_id", None):
            raise MusicAssistantUnavailable("No active Music Assistant queue")
        await client.player_queues.play_index(
            active_queue.queue_id,
            queue_item_id,
        )
