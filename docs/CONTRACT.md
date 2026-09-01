# Client contract

Everything a client needs from Home Assistant is listed here. The
`media_controller` integration is the only producer; the ESP32-S3 firmware and
the T560 panel are consumers. Nothing else may be assumed.

Treat this file as the change-control surface: a change to anything below
affects released devices in the field. A change to code that is not described
here affects one component only.

Contract version: **1** (matches integration `0.7.x`).

## Producer

`custom_components/media_controller` creates one device per configured Music
Assistant player. Entity IDs come from the Home Assistant entity registry, so
they are per-installation and must be configurable in every client. Never
hardcode them.

## Entities

| Entity | Platform | Purpose |
| --- | --- | --- |
| `sensor.<controller>_queue` | sensor | Bounded queue window |
| `sensor.<controller>_playlists` | sensor | Library playlists |
| `light.<controller>_light_1` | light | Room light proxy 1 |
| `light.<controller>_light_2` | light | Room light proxy 2 |
| `switch.<controller>_fan` | switch | Room switch proxy, fan |
| `switch.<controller>_ac` | switch | Room switch proxy, AC |

The state of both sensors is the constant string `ok`. All data is in the
attributes, because a Home Assistant state is limited to 255 characters.

### Queue sensor attributes

```json
{
  "data": "{\"titles\":[…],\"artists\":[…],\"queue_ids\":[…],\"current_index\":0,\"count\":50}",
  "count": 50
}
```

`data` is a **JSON string**, not an object. It is serialized compactly with
`ensure_ascii=False`, so it is UTF-8 and Unicode track names survive.

Inside `data`:

- `titles`, `artists`, `queue_ids` — parallel arrays, always the same length;
- `current_index` — index **within this window**, not the global queue index;
- `count` — length of the parallel arrays.

The window is `DEFAULT_QUEUE_WINDOW_SIZE` (50) entries starting up to
`DEFAULT_QUEUE_WINDOW_BEFORE` (5) entries before the current item. A client must
never assume the window starts at the beginning of the queue, and must handle
`count == 0`.

### Playlists sensor attributes

```json
{
  "names": ["…"],
  "uris": ["…"],
  "count": 12
}
```

Here the arrays are **real attributes**, not an encoded string. This asymmetry
with the queue sensor is deliberate history, not an accident: keep both shapes
until the contract version is raised. `names` and `uris` are parallel. Entries
whose name contains `(from library)` are filtered out by the integration. The
list is capped at `DEFAULT_PLAYLIST_LIMIT` (500), fetched in pages of 100.

### Proxy entities

A proxy mirrors the state of the entity selected in Options Flow and forwards
actions to it. A proxy with no configured source, or whose source is missing, is
`unavailable`; the other controller functions keep working.

Proxy lights currently declare `ColorMode.BRIGHTNESS` only. They mirror
`brightness` and forward `brightness` on turn-on. **They do not forward color
temperature.** A client that offers a colour-temperature control must point at
the real light entity for that tile, which is what
`clients/t560/config/config.ini.example` does for `desk_lamp` and
`desk_led_strip`. Raising this is a contract change; see
[ROADMAP.md](ROADMAP.md).

## Services

`media_controller.refresh`

| Field | Required | Meaning |
| --- | --- | --- |
| `entry_id` | no | One controller entry; omit for all loaded entries |

`media_controller.play_queue_item`

| Field | Required | Meaning |
| --- | --- | --- |
| `entity_id` | yes | The Music Assistant `media_player` |
| `queue_item_id` | yes | A value from `queue_ids` in the queue payload |

Playback of a queue entry must go through this service. Calling
`media_player.play_media` with a queue item replaces the queue and is a bug.

Playlist playback goes through `music_assistant.play_media` with a `uri` from
the playlists payload.

## Refresh timing

- Playlists refresh at setup and every six hours.
- The queue refreshes after a Music Assistant title change, behind a cancellable
  three-second debounce.
- Overlapping queue calls are prevented; obsolete delays are cancelled.
- Clients poll Home Assistant for entity state. They must request single
  entities (`/api/states/<entity_id>`), never the full `/api/states` list.

## Direct Music Assistant state

Media metadata, position, duration, volume, shuffle, and repeat are read from
the Music Assistant `media_player` entity directly, not from this integration.
Transport actions are ordinary `media_player.*` service calls. The integration
exists only for what Music Assistant does not expose in a form a small client
can consume.

## Changing the contract

1. Update this file first.
2. Bump `version` in `custom_components/media_controller/manifest.json`.
3. Update every consumer in the same pull request: `firmware/`, `clients/`.
4. If a released client cannot read the new shape, raise the contract version
   above and keep the old shape until every client is updated.

Tests that protect the contract:

- `tests/test_transformations.py` — payload construction;
- `clients/t560/tests/test_json_helpers.c` — payload parsing on the client side.
