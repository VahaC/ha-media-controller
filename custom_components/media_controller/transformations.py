"""Pure payload and stored-record structures.

This module deliberately has no Home Assistant imports, so the payloads a
client reads, the stored shape of a registry element, and the entry
migrations can all be tested without a Home Assistant runtime.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import math
from typing import Any
import zlib


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
        """Return the firmware queue JSON object."""
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
        """Return the Home Assistant playlist attributes."""
        return {
            "names": list(self.names),
            "uris": list(self.uris),
            "count": self.count,
        }


def migrate_v2_title(title: str, legacy_prefix: str) -> str:
    """Drop the version 2 title prefix, and only when it is still intact.

    A title is the one piece of an entry a person is invited to rewrite, so
    anything that is no longer exactly what this integration wrote is left
    alone. Stripping the prefix off an empty remainder would leave an entry
    with no name at all, so that is left alone too.
    """
    if not title.startswith(legacy_prefix):
        return title
    return title[len(legacy_prefix):].strip() or title


def room_state_number(value: Any) -> float | int | None:
    """Return a JSON-native number for a room-state reading, or None.

    Home Assistant renders `/api/template` for administrators only, and a
    panel token belongs to a dedicated non-administrator user by design, so
    the integration renders here what the ESP32 panel can no longer ask for
    itself: one small array per registry element, keyed by rid. A number the
    entity does not report travels as JSON null, which the firmware reads as
    "no reading" rather than as zero.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def room_state_position(value: Any) -> int | None:
    """Return a cover's position as a whole percentage, or None.

    Unlike every other room-state reading this one is bounded by its own
    definition: 0 is shut and 100 is fully open, in every house and every
    unit system. It is rounded to a whole percent and clamped to that range
    rather than passed through, because a client draws it on a control whose
    travel is the range itself — a blind reporting 120 would otherwise be
    drawn off the end of its own slider.

    A cover that reports no position at all — every blind that only opens
    and closes — returns None, which travels as JSON null. That is the whole
    of what "missing" may become: inventing a percentage for a cover that
    reports none would put a number under a finger that moves nothing.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return max(0, min(100, int(round(value))))


def room_state_percentage(value: Any) -> int | None:
    """Return a fan's speed as a whole percentage, or None.

    Like a cover's position and unlike every other room-state reading, this
    one is bounded by its own definition: 0 is stopped and 100 is full speed,
    in every house. It is rounded to a whole percent and clamped to that
    range rather than passed through, because a client draws it on a control
    whose travel is the range itself.

    A fan that reports no speed — one running at a single speed, or one that
    is simply off and says nothing — returns None, which travels as JSON
    null. Inventing a number for it would put a value under a finger that,
    on a single-speed fan, moves nothing.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return max(0, min(100, int(round(value))))


def room_state_unit(value: Any) -> str | None:
    """Return a sensor unit for a room-state reading, or None.

    Home Assistant renders a missing attribute as the string "None", which
    is no unit rather than a unit called None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in ("", "none", "unknown", "unavailable"):
            return None
        return value
    return str(value)


def room_state_values(
    domain: str,
    state: str | None,
    attributes: Mapping[str, Any] | None,
) -> list[Any]:
    """Render one registry element's current room state.

    `domain` is the Home Assistant domain of the element (`light`, `switch`,
    `climate`, `cover`, `weather`, `sensor`); anything else travels as a bare
    state, which is all a client that cannot draw the domain needs to ignore
    the element. `state` is the entity state itself, or None when the entity
    is gone, which reads as unknown rather than keeping a stale value: an
    element that is unavailable must not read as off, because off is a fact
    and this is the absence of one. The state string is UTF-8 and survives
    intact; sensor values are states too, never numbers, because a sensor may
    report "on" rather than a reading.
    """
    safe_attributes = attributes or {}
    if state is None:
        return ["unknown"]
    if domain == "cover":
        # The state says `open` or `closed` and cannot say how far. A client
        # that draws a position control has to be told the number it moves,
        # and the one client that reads this block is the one that cannot ask
        # for the attribute itself. A cover that reports none sends null.
        return [state, room_state_position(safe_attributes.get("current_position"))]
    if domain == "fan":
        # The state says `on` or `off` and cannot say how fast. The speed
        # rides beside it for the same reason a cover's position does: the
        # panel that reads this block cannot ask Home Assistant for the
        # `percentage` attribute itself. A fan running at a single speed, or
        # one that is off, reports no percentage and sends null.
        return [state, room_state_percentage(safe_attributes.get("percentage"))]
    if domain == "climate":
        return [
            state,
            room_state_number(safe_attributes.get("current_temperature")),
            room_state_number(safe_attributes.get("temperature")),
        ]
    if domain == "weather":
        return [
            state,
            room_state_number(safe_attributes.get("temperature")),
            room_state_number(safe_attributes.get("humidity")),
        ]
    if domain == "sensor":
        return [state, room_state_unit(safe_attributes.get("unit_of_measurement"))]
    return [state]


def render_room_states(hass: Any, entries: Iterable[Any]) -> dict[str, list[Any]]:
    """Render the current state of every registry element, keyed by rid.

    `hass` is only read through `hass.states.get`, and an entry only through
    its `rid`, `domain` and `target_entity_id`, so tests serve a stub. An
    element whose entity is gone reads as unknown rather than keeping a stale
    value. Callers pass already-resolved entries: capabilities are read from
    the live target at serve time, because stored controls go stale — a form
    stores none at all, and a target missing at setup keeps none until
    something re-resolves it, which for a switch without capability
    attributes is never.
    """
    states: dict[str, list[Any]] = {}
    for entry in entries:
        target = hass.states.get(entry.target_entity_id)
        if target is None:
            states[entry.rid] = ["unknown"]
        else:
            states[entry.rid] = room_state_values(
                entry.domain, target.state, target.attributes
            )
    return states


def migrate_v3_section(
    section: Mapping[str, Any] | None,
    dead_keys: Iterable[str],
) -> dict[str, Any]:
    """Return one stored data or options mapping with the slots removed.

    Contract version 9 has no room-control slots, so the stored block and the
    four version 1 keys that preceded it are dropped rather than carried
    forward for the life of the entry. Everything else is copied through
    untouched: this runs on a source entry, and the player it is bound to is
    in the same mapping.
    """
    dead = set(dead_keys)
    return {
        key: value
        for key, value in (section or {}).items()
        if key not in dead
    }


@dataclass(frozen=True, slots=True)
class EntityPayload:
    """One registry element as a panel reads it.

    It names the real entity: a panel learns entity IDs at
    runtime and needs no proxy, and an unbounded registry behind proxies would
    create an unbounded number of extra entities in Home Assistant.
    """

    rid: str
    entity: str
    name: str
    domain: str
    controls: tuple[str, ...] = ()
    min_kelvin: int | None = None
    max_kelvin: int | None = None
    # The setpoint bounds of a thermostat. They travel only beside a
    # `target_temperature` control, the way the two Kelvin bounds travel only
    # beside `color_temp`. No unit travels with them: they are whatever the
    # entity itself reports, and a card draws a bare degree sign.
    min_temp: float | None = None
    max_temp: float | None = None
    target_temp_step: float | None = None
    # A fan's speed step as a whole percent, travelling only beside a
    # `percentage` control the way the setpoint bounds travel only beside
    # `target_temperature`. Absent when the fan reports no useful step, and a
    # client then sweeps a percent at a time.
    percentage_step: float | None = None
    # The catalog identifier of the picture this tile draws, or "" when the
    # user chose none and the client draws whatever its domain suggests. It
    # is a name and never a position, so the catalog may be reordered without
    # moving anybody's icon, and a client that does not know it ignores it
    # exactly as it ignores a control it cannot draw.
    icon: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return the client-facing registry object."""
        payload: dict[str, Any] = {
            "rid": self.rid,
            "entity": self.entity,
            "name": self.name,
            "domain": self.domain,
            "controls": list(self.controls),
        }
        # Sent only when one was chosen. An absent key and an empty one mean
        # the same thing to a client, and leaving it out keeps the payload of
        # an installation that has chosen no icons exactly the size it was.
        if self.icon:
            payload["icon"] = self.icon
        if self.min_kelvin is not None:
            payload["min_kelvin"] = self.min_kelvin
        if self.max_kelvin is not None:
            payload["max_kelvin"] = self.max_kelvin
        if self.min_temp is not None:
            payload["min_temp"] = self.min_temp
        if self.max_temp is not None:
            payload["max_temp"] = self.max_temp
        if self.target_temp_step is not None:
            payload["target_temp_step"] = self.target_temp_step
        if self.percentage_step is not None:
            payload["percentage_step"] = self.percentage_step
        return payload


@dataclass(frozen=True, slots=True)
class ClientConfigPayload:
    """Everything one client device needs to draw its room controls.

    `entities` is a panel's registry, and `None` means "this entry has no
    such block": the key is left out of the payload entirely, which is how a
    client tells a panel's config sensor from a source's.
    """

    profile: str = ""
    entity_limit: int | None = None
    entities: tuple[EntityPayload, ...] | None = None
    # Panels only, and only those that draw more than one skin. It is the one
    # entity in the payload a client *writes* rather than reads: a panel that
    # lets a person pick a skin on the device itself calls
    # `select.select_option` on it. Deriving it from the config sensor's own
    # entity ID would break the first time somebody renamed either of them,
    # which is exactly what `rid` exists to avoid elsewhere.
    skin_select_entity: str = ""
    player_entity: str = ""
    queue_entity: str = ""
    playlists_entity: str = ""
    # Which version of the client contract the integration publishing this
    # payload implements, so that a client can tell whether the two of them
    # still speak the same protocol. The number is owned by `contract.py` and
    # passed in, because this module imports nothing: 0 means the caller did
    # not name one, which is what a client reads as "older than mine".
    contract_version: int = 0
    # Panels only. A source owns no runtime settings and gets neither key.
    settings: Mapping[str, Any] | None = None
    commands: Mapping[str, Any] | None = None
    # Panels only, and only those whose profile says they draw with it. The
    # tablet has none: its two skins carry their own palettes, so it would
    # have nothing to apply a progress-ring colour to.
    theme: Mapping[str, Any] | None = None
    # Panels only. The current state of every registry element, keyed by rid,
    # rendered by the integration because a panel cannot render it itself:
    # POST /api/template answers administrators only, and a panel token
    # belongs to a dedicated non-administrator user. The ESP32 panel reads
    # this block out of the same poll that carries the registry; any other
    # client ignores it, the way it ignores settings and commands it has no
    # use for. Omitted for a source, which draws nothing.
    room_states: Mapping[str, Any] | None = None

    def as_attributes(self) -> dict[str, Any]:
        """Return the Home Assistant attributes of a config sensor.

        The three controller entities are included so that a client needs no
        entity ID of its own: a URL, a token, and its panel ID are enough to
        bootstrap.

        A block this entry has no use for is left out altogether, so a source
        never carries `entities`, `settings`, `commands` or `room_states`.
        """
        payload: dict[str, Any] = {
            "profile": self.profile,
            "player": self.player_entity,
            "queue": self.queue_entity,
            "playlists": self.playlists_entity,
        }
        if self.entities is not None:
            payload["entity_limit"] = self.entity_limit or 0
            payload["entities"] = [
                entity.as_dict() for entity in self.entities
            ]
        # The revision covers the layout and nothing else — the registry
        # included, because the registry is layout. A client rebuilds its
        # interface when it changes, and settings and commands must never
        # cause that: they are applied while the panel keeps running.
        payload["revision"] = self.revision(payload)
        # Deliberately after the revision, and so not part of it. The contract
        # version is not layout: it changes only when the integration itself is
        # upgraded, and folding it into the checksum would restart every panel
        # in the house to redraw a room page that did not move.
        payload["contract_version"] = self.contract_version
        # Also after the revision, and for the same reason: which entity holds
        # the skin is not layout. It is assigned once, when the select is
        # added, and folding it in would spend a re-layout on a fact that
        # changes nothing on screen. Panels only, decided the same way every
        # other panel-only key here is: an entry with no registry is not one.
        if self.entities is not None and self.skin_select_entity:
            payload["skin_select"] = self.skin_select_entity
        if self.settings is not None:
            payload["settings"] = dict(self.settings)
        # Outside the revision, like settings: a colour is restyled onto
        # widgets that already exist, and folding it into the checksum would
        # rebuild a panel's room page to change the colour of a progress ring.
        if self.theme is not None:
            payload["theme"] = dict(self.theme)
        if self.commands is not None:
            payload["commands"] = dict(self.commands)
        # Also after the revision, for the same reason as settings and
        # commands and more so: states move constantly while the house is
        # simply being used, and a re-layout on every toggle would rebuild
        # the room page out from under the finger that caused it. Panels
        # only, decided the same way every other panel-only key here is.
        if self.entities is not None and self.room_states:
            payload["room_states"] = dict(self.room_states)
        return payload

    @staticmethod
    def revision(payload: Mapping[str, Any]) -> int:
        """Return a stable fingerprint of one configuration.

        A client compares it with the previous value to decide whether a
        re-layout is needed. It is a checksum rather than a counter so that it
        survives restarts without extra stored state, and so that reverting a
        change restores the previous value.
        """
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return zlib.crc32(canonical.encode("utf-8"))


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
