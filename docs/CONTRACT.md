# Client contract

Everything a client needs from Home Assistant is listed here. The
`media_controller` integration is the only producer; the ESP32-S3 firmware and
the T560 panel are consumers. Nothing else may be assumed.

Treat this file as the change-control surface: a change to anything below
affects released devices in the field. A change to code that is not described
here affects one component only.

Contract version: **4** (matches integration `0.9.x`).

Every version so far has been purely additive. Version 2 added the config
sensor and let proxy lights forward colour temperature. Version 3 added two
optional blocks to the config sensor — `settings` and `commands` — the entities
a panel device owns itself, and one endpoint a panel reports its own hardware
state to.

Version 4 adds a second ESP32 firmware that pairs like the tablet and reads
everything below at runtime. It changes no payload and no entity: what it
changes is who the sentences are about. Statements that named "the ESP32" as
the client that cannot cache, cannot be a panel, or reads its entity IDs from
substitutions now say "the classic ESP32 firmware", because the paired one does
all three the way the tablet does. A client may also apply only part of
`settings` and ignore the rest, which is new only as a written rule.

Nothing is removed and no entity any earlier client reads is renamed, so an
older client keeps working: it simply ignores what it does not understand.

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

A **panel** device carries these as well. The classic ESP32 controller has none
of them, because it is a controller rather than a panel; the paired ESP32
firmware and the tablet both have all of them, except where a client says
otherwise below:

| Entity | Platform | Purpose |
| --- | --- | --- |
| `sensor.<panel>_battery` | sensor | Reported charge, percent |
| `sensor.<panel>_uptime` | sensor | When the application last started |
| `sensor.<panel>_last_report` | sensor | When the tablet was last heard from |
| `sensor.<panel>_wifi_signal` | sensor | Reported signal strength, dBm |
| `sensor.<panel>_temperature` | sensor | Reported tablet temperature, °C |
| `binary_sensor.<panel>_charging` | binary_sensor | Reported charger state |
| `binary_sensor.<panel>_connected` | binary_sensor | Whether reports arrive |
| `select.<panel>_page` | select | The page the panel is showing |
| `switch.<panel>_screen` | switch | Backlight on or off |
| `number.<panel>_screen_brightness` | number | Backlight level, percent |
| `number.<panel>_poll_interval` | number | `poll_interval_ms`, in seconds |
| `number.<panel>_playlist_poll_interval` | number | `playlist_poll_interval_ms`, in seconds |
| `number.<panel>_screen_off` | number | `screen_off_seconds` |
| `button.<panel>_restart` | button | Restart the panel application |

The three interval numbers are shown in seconds and stored on the config entry
in the units the payload uses. `screen_off` accepts 0, meaning never.

`<client>` is the controller itself for the slots of an ESP32 running the
classic firmware, and the panel device for every other client — the tablet and
the paired ESP32 firmware alike.

**Two entity ID spellings are valid and both are permanent.** An installation
created before integration `0.8.2` keeps `light.<controller>_light_1`,
`light.<controller>_light_2`, `switch.<controller>_fan`, and
`switch.<controller>_ac` for slots 1 to 4, because the migration preserves the
registry rows so that flashed devices need no reflash. An installation created
after it uses `_slot_1` to `_slot_4`. No client may assume either spelling; the
classic ESP32 firmware reads them from substitutions and every other client —
the tablet and the paired ESP32 firmware — from the config sensor.

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
  "revision": 2098342174,
  "settings": {
    "poll_interval_ms": 1000,
    "playlist_poll_interval_ms": 60000,
    "screen_off_seconds": 30
  },
  "commands": {
    "display": {"state": "off", "at": 1756800000000},
    "brightness": {"value": 60, "at": 1756800000100},
    "restart": {"at": 1756800000200},
    "page": {"value": "room", "at": 1756800000300}
  }
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
  Home Assistant is unreachable at boot. The paired ESP32 firmware keeps the
  entity IDs it learned in flash for exactly this reason. A client that cannot
  store a cache — the classic ESP32 firmware — must keep working from its
  compile-time defaults instead, and must not treat a missing config sensor as
  fatal.
- `settings` and `commands` are **optional and only sent to panels**. Both are
  absent for the classic ESP32 controller, which applies nothing at runtime. A
  client that does not understand them ignores them, and a client that
  understands only some of them applies those and ignores the rest: the paired
  ESP32 firmware applies both poll intervals and every command, but not
  `screen_off_seconds`, which its own ESPHome device already owns.

### Panel settings

`settings` is a desired configuration, not an event: the newest payload simply
wins, and a client adopts it without acknowledging it. It is what used to be
edited in `config.ini` over SSH.

| Key | Unit | Range |
| --- | --- | --- |
| `poll_interval_ms` | milliseconds | 500 – 30000 |
| `playlist_poll_interval_ms` | milliseconds | 10000 – 3600000 |
| `screen_off_seconds` | seconds | 0, or 5 – 3600 |

Home Assistant clamps every value before it sends one; a client clamps again
rather than trusting the payload. `screen_off_seconds` is 0 for never.

`config.ini` on the tablet keeps the same keys, and they are a **fallback, not
an override**: they decide only until the panel has read a payload carrying
`settings`, and again if the cache is lost.

### Panel commands

`commands` carries moments rather than messages, because nothing can be pushed
to a client that serves nothing. Every entry has an `at` field: milliseconds
since the epoch, on the Home Assistant clock.

A client keeps the newest `at` it has acted on for each command and applies one
only when the payload's `at` is **greater**. That is what makes a poll a safe
transport: a command is applied exactly once however often it is read, a client
that was asleep still sees the last one, and a restart command does not run
again on every boot.

| Command | Fields | Meaning |
| --- | --- | --- |
| `display` | `state` (`on`/`off`), `at` | Turn the backlight on or off |
| `brightness` | `value` (1 – 100), `at` | Set the backlight level |
| `restart` | `at` | Restart the client application |
| `page` | `value`, `at` | Show one of the client's pages |

Rules:

- a command that has never been issued is **omitted**, not sent as a zero;
- an unknown command name must be ignored, not treated as an error;
- an entry without a usable `at` must be ignored: it cannot be ordered;
- **on the first payload after starting, a client adopts every `at` without
  acting on it.** A command issued while the client was down has already been
  overtaken by events, and a restart that has happened must not happen again on
  every boot;
- `state` is `on` or `off`. Any other value is ignored.
- `page` names a client page. **Which pages exist is the client's business**,
  so a client ignores a name it does not have rather than guessing at one.
  The pages of the T560 panel are `player`, `queue`, `playlists`, and `room`;
  Home Assistant offers exactly those and refuses any other before sending.

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

## Panel status endpoint

`POST /api/media_controller/panel_status`

Home Assistant cannot ask a tablet anything, so a panel pushes what only it
knows. It reports on a change and at least once a minute; the entities above go
unavailable when nothing has arrived for three minutes.

The request is authenticated with the panel's own access token — the one it was
handed during pairing. Home Assistant accepts it only when the caller is the
Home Assistant user created for **that** panel, so one panel cannot write
another's battery level.

```json
{
  "panel_id": "t560_1a2b3c4d",
  "version": "0.3.1",
  "page": "player",
  "uptime_seconds": 4210,
  "wifi_dbm": -53,
  "temperature_c": 31.5,
  "battery": {"available": true, "percent": 82, "charging": false},
  "display": {"available": true, "on": true, "brightness": 57}
}
```

- `available` is what makes a field believable. A tablet with no battery, or
  one whose display state is unknown, sends `false` and the matching entities
  stay unavailable rather than reporting zero.
- `percent` and `brightness` are 0 – 100; anything else is discarded. Use -1
  for a backlight that exists but cannot be written by this session.
- Booleans must be real JSON booleans; `1` is not `true`.
- `version` sets the software version on the panel's Home Assistant device.
- `page` is the page the client is showing, from the same closed list the
  `page` command takes. A name Home Assistant does not offer is dropped, so
  the select entity never holds an option it does not have.
- `uptime_seconds` is how long the **application** has been running, not the
  tablet. Home Assistant turns it into the moment it started, and republishes
  that only when it moves by more than 15 seconds — otherwise rounding alone
  would keep nudging it.
- `wifi_dbm` (-120 – 0) and `temperature_c` (-50 – 150) are optional. A panel
  omits either where the hardware has none, and the matching sensor stays
  unavailable. Neither is worth a report of its own: send them with whatever
  report is already going.

Answers: `200` with `{"status": "ok"}`; `400` for an unusable body; `403` when
the token belongs to another account; `404` when no loaded panel has that ID.

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
- `tests/test_pairing.py` — the rules that guard the provisioning endpoint;
- `tests/test_panel_state.py` — the settings, the command channel, and the
  validation of a status report;
- `clients/t560/tests/test_power_button.py` — the tablet side of the settings
  and of the display request.
