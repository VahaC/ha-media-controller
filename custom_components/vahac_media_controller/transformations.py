"""Pure queue and playlist transformations.

This module deliberately has no Home Assistant imports so its compatibility
logic can be tested without a Home Assistant runtime.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from typing import Any


def _value(item: object, key: str, default: Any = None) -> Any:
    """Read a field from either a mapping or a Music Assistant model."""
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _text(value: Any) -> str:
    """Convert optional metadata to a safe string."""
    if value is None:
        return ""
    return str(value)


def coerce_index(value: Any) -> int:
    """Convert a queue index to an integer, using -1 for invalid values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def calculate_queue_offset(
    current_index: Any,
    window_before: int,
) -> int:
    """Calculate the first global queue index to request."""
    index = coerce_index(current_index)
    return max(index - max(int(window_before), 0), 0) if index >= 0 else 0


@dataclass(frozen=True, slots=True)
class QueuePayload:
    """Bounded queue data consumed by the ESP32."""

    titles: tuple[str, ...] = ()
    artists: tuple[str, ...] = ()
    queue_ids: tuple[str, ...] = ()
    current_index: int = 0

    @property
    def count(self) -> int:
        """Return the number of safe parallel queue entries."""
        return len(self.titles)

    def as_dict(self) -> dict[str, Any]:
        """Return the legacy-compatible JSON object."""
        return {
            "titles": list(self.titles),
            "artists": list(self.artists),
            "queue_ids": list(self.queue_ids),
            "current_index": self.current_index,
            "count": self.count,
        }

    def as_json(self) -> str:
        """Serialize compact UTF-8-safe JSON for the ESP32 REST client."""
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class PlaylistPayload:
    """Playlist data consumed by the ESP32."""

    names: tuple[str, ...] = ()
    uris: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        """Return the number of safe parallel playlist entries."""
        return len(self.names)

    def as_attributes(self) -> dict[str, Any]:
        """Return legacy-compatible Home Assistant attributes."""
        return {
            "names": list(self.names),
            "uris": list(self.uris),
            "count": self.count,
        }


def _queue_title(item: object) -> str:
    title = _value(item, "media_title") or _value(item, "name")
    if not title and (media_item := _value(item, "media_item")):
        title = _value(media_item, "name")
    return _text(title)


def _queue_artist(item: object) -> str:
    artist = _value(item, "media_artist") or _value(item, "artist")
    if artist:
        return _text(artist)

    media_item = _value(item, "media_item")
    if not media_item:
        return ""

    artist = _value(media_item, "artist_str") or _value(media_item, "artist")
    if artist:
        return _text(artist)

    artists = _value(media_item, "artists")
    if isinstance(artists, Iterable) and not isinstance(artists, (str, bytes)):
        return ", ".join(
            name
            for entry in artists
            if (name := _text(_value(entry, "name") or entry))
        )
    return ""


def _queue_id(item: object) -> str:
    return _text(
        _value(item, "queue_item_id")
        or _value(item, "item_id")
        or _value(item, "id")
    )


def transform_queue_items(
    items: Iterable[object] | None,
    *,
    global_current_index: Any,
    offset: int,
) -> QueuePayload:
    """Convert a bounded Music Assistant result to the ESP32 payload."""
    safe_items = list(items or ())
    if not safe_items:
        return QueuePayload()

    titles = tuple(_queue_title(item) for item in safe_items)
    artists = tuple(_queue_artist(item) for item in safe_items)
    queue_ids = tuple(_queue_id(item) for item in safe_items)

    current_index = coerce_index(global_current_index)
    local_index = current_index - max(offset, 0) if current_index >= 0 else 0
    local_index = max(0, min(local_index, len(safe_items) - 1))

    return QueuePayload(titles, artists, queue_ids, local_index)


def transform_playlists(
    items: Iterable[object] | None,
    *,
    limit: int,
) -> PlaylistPayload:
    """Filter and convert Music Assistant playlists."""
    safe_limit = max(int(limit), 0)
    if safe_limit == 0:
        return PlaylistPayload()
    names: list[str] = []
    uris: list[str] = []

    for item in items or ():
        name = _text(_value(item, "name"))
        if "(from library)" in name:
            continue
        names.append(name)
        uris.append(_text(_value(item, "uri")))
        if len(names) >= safe_limit:
            break

    return PlaylistPayload(tuple(names), tuple(uris))
