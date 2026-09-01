# Client contract

Everything a client needs from Home Assistant is listed here. The
`media_controller` integration is the only producer; the ESP32-S3 firmware and
the T560 panel are consumers. Nothing else may be assumed.

Treat this file as the change-control surface: a change to anything below
affects released devices in the field. A change to code that is not described
here affects one component only.

Contract version: **2** (matches integration `0.8.x`).

Version 2 is purely additive. It adds the config sensor and lets proxy lights
forward colour temperature; it removes nothing and renames no entity a version 1
client already reads, so a client written against version 1 keeps working.

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
| `sensor.<client>_config` | sensor | Room-control layout of one client |
| `light.<client>_slot_<n>` | light | Room light proxy in slot n |
| `switch.<client>_slot_<n>` | switch | Room switch proxy in slot n |

`<client>` is the controller itself for the ESP32 slots, and the panel device
for every other client.

**Two entity ID spellings are valid and both are permanent.** An installation
created before integration `0.8.2` keeps `light.<controller>_light_1`,
`light.<controller>_light_2`, `switch.<controller>_fan`, and
`switch.<controller>_ac` for slots 1 to 4, because the migration preserves the
registry rows so that flashed devices need no reflash. An installation created
after it uses `_slot_1` to `_slot_4`. No client may assume either spelling; the
ESP32 reads them from substitutions and every other client from the config
sensor.

The state of every sensor above is the constant string `ok`. All data is in
the attributes, because a Home Assistant state is limited to 255 characters.

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

### Config sensor attributes

```json
{
  "profile": "t560",
  "slot_count": 6,
  "player": "media_player.kitchen",
  "queue": "sensor.controller_queue",
  "playlists": "sensor.controller_playlists",
  "slots": [
    {
      "slot": 1,
      "entity": "light.controller_slot_1",
      "label": "DESK LAMP",
      "controls": ["toggle", "brightness", "color_temp"],
      "min_kelvin": 2000,
      "max_kelvin": 6535
    }
  ],
  "revision": 2098342174
}
```

Real attributes, not an encoded string. Rules a client must follow:

- `player`, `queue`, and `playlists` are the controller entities this client
  reads. They are here so that a client needs no entity ID of its own: a URL,
  a token, and its own identifier are enough to bootstrap. A payload in which
  any of them is empty is not yet usable and must be retried, not cached.
- `entity` is always the **proxy**, never the entity the user selected.
- Unconfigured slots are **omitted**. Render what arrives, in `slot` order, and
  handle an empty `slots` list.
- `controls` is a closed list: `toggle`, `brightness`, `color_temp`. An
  unknown value must be ignored, not treated as an error, so that a future
  control can be added without breaking released clients.
- `min_kelvin` and `max_kelvin` are present only when `controls` contains
  `color_temp`.
- `revision` is a checksum of the rest of the payload, not a counter. Equal
  values mean an unchanged configuration; any change produces a different
  value. A client uses it to skip a re-layout, never to order versions.
- A client must cache the last payload it read and start from that cache when
  Home Assistant is unreachable at boot. A client that cannot store a cache —
  the ESP32 — must keep working from its compile-time defaults instead, and
  must not treat a missing config sensor as fatal.

How much of the payload a client uses depends on what it can change at
runtime. The T560 panel builds its whole room page from it. The ESP32 takes
only the labels and the visibility of its four buttons: everything else about
those buttons, including the entity IDs and the service domains, is resolved
while compiling and cannot follow a configuration change.

### Proxy entities

A proxy mirrors the state of the entity selected for its slot and forwards
actions to it. A proxy whose source is missing is `unavailable`; the other
controller functions keep working. Clearing a slot removes its proxy.

A slot's domain is fixed when the slot is created, because the ESP32 resolves
both the entity ID and the service domain of its four buttons at compile time.

Proxy lights mirror the colour modes of their target: `onoff`, `brightness`, or
`color_temp` with the target's Kelvin bounds. They forward `brightness` and
`color_temp_kelvin` on turn-on. Colour, effects, and every other light feature
are **not** forwarded. A client must not address the target entity directly to
work around that; the slot mechanism is the only supported path.

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
- `tests/test_profiles.py` — which controls a client is told to draw;
- `tests/test_migration.py` — the version 1 slots keep their numbers;
- `clients/t560/tests/test_panel_config.c` — payload parsing on the client
  side, including an unknown control name;
- `tests/test_pairing.py` — the rules that guard the provisioning endpoint.
