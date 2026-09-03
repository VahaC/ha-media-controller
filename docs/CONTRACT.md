# Client contract

Everything a client needs from Home Assistant is listed here. The
`media_controller` integration is the only producer; the ESP32-S3 firmware and
the T560 panel are consumers. Nothing else may be assumed.

Treat this file as the change-control surface: a change to anything below
affects released devices in the field. A change to code that is not described
here affects one component only.

Contract version: **6** (matches integration `1.2.x`).

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

Version 5 makes the number at the top of this file something code compares
rather than prose nobody reads. Both halves now carry it: the integration
publishes `contract_version` in the config sensor, and a panel reports its own
in its status report. A panel and an integration that no longer speak the same
protocol therefore say so — Home Assistant raises a repair issue naming a
panel that is behind, and a panel that finds Home Assistant behind reports it
where its own user looks — instead of silently dropping half of what the other
sends. See **Version compatibility** below. The classic ESP32 firmware neither
sends nor reads the field and is untouched by it.

Up to and including version 5 nothing was removed and no entity any earlier
client read was renamed, so an older client kept working: it simply ignored
what it did not understand. The two fields version 5 added are optional in
exactly that sense — every build from before it omits them, and an absent
value means "older" rather than an error.

Version 6 is the first version that **takes something away**, and only from
panels. A panel's four-to-six fixed room slots are replaced by an unbounded
registry of entities, carried in a new optional `entities` block. With the
slots go the proxy entities a panel owned — `light.<panel>_slot_<n>` and
`switch.<panel>_slot_<n>` are deleted from Home Assistant, because a registry
with no upper bound would otherwise create an unbounded number of them and
neither panel needs one: both learn entity IDs at runtime. A panel is
therefore no longer sent `slots` at all, and its room controls have to be
chosen again. See **Registry entries** and **What version 6 breaks** below.

The classic ESP32 controller is untouched by all of it. It still receives
`slots`, still addresses proxies, and still behaves exactly as it did under
version 5: it resolves both entity IDs and service domains while compiling, so
proxies are the only way it can follow a change made in the Home Assistant UI,
and a registry it cannot read would be of no use to it. It is sent no
`entities` block, exactly as it is sent no `settings` and no `commands`.

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
| `light.<controller>_slot_<n>` | light | Room light proxy in slot n |
| `switch.<controller>_slot_<n>` | switch | Room switch proxy in slot n |

The two proxy rows exist **only for a controller entry**, which is to say only
for an ESP32 running the classic firmware. As of version 6 a panel has no
slots and no proxies; it is handed the real entity IDs in the `entities` block
and addresses them directly.

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
| `select.<panel>_player_skin` | select | `player_skin`; options are the client's own |
| `switch.<panel>_screen` | switch | Backlight on or off |
| `number.<panel>_screen_brightness` | number | Backlight level, percent |
| `number.<panel>_poll_interval` | number | `poll_interval_ms`, in seconds |
| `number.<panel>_playlist_poll_interval` | number | `playlist_poll_interval_ms`, in seconds |
| `number.<panel>_screen_off` | number | `screen_off_seconds` |
| `button.<panel>_restart` | button | Restart the panel application |

The three interval numbers are shown in seconds and stored on the config entry
in the units the payload uses. `screen_off` accepts 0, meaning never.

`player_skin` exists for every client that draws more than one layout, and its
options are that client's own names — see **Panel settings** below. A client
that draws one interface gets no such entity.

`<client>` is the controller itself for the slots of an ESP32 running the
classic firmware, and the panel device for the config sensor of every other
client — the tablet and the paired ESP32 firmware alike.

**Two entity ID spellings are valid and both are permanent.** An installation
created before integration `0.8.2` keeps `light.<controller>_light_1`,
`light.<controller>_light_2`, `switch.<controller>_fan`, and
`switch.<controller>_ac` for slots 1 to 4, because the migration preserves the
registry rows so that flashed devices need no reflash. An installation created
after it uses `_slot_1` to `_slot_4`. The classic ESP32 firmware reads them
from substitutions and must assume neither spelling.

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

One client kind reads `slots` and the other reads `entities`, and neither
receives the block it does not read. The panel payload is:

```json
{
  "profile": "t560",
  "entity_limit": 100,
  "player": "media_player.kitchen",
  "queue": "sensor.controller_queue",
  "playlists": "sensor.controller_playlists",
  "entities": [
    {
      "rid": "a3f1c92d",
      "entity": "light.desk_lamp",
      "name": "Desk lamp",
      "domain": "light",
      "controls": ["toggle", "brightness", "color_temp"],
      "min_kelvin": 2200,
      "max_kelvin": 6500
    }
  ],
  "revision": 2098342174,
  "contract_version": 6,
  "settings": {
    "poll_interval_ms": 1000,
    "playlist_poll_interval_ms": 60000,
    "screen_off_seconds": 30,
    "player_skin": "cassette"
  },
  "commands": {
    "display": {"state": "off", "at": 1756800000000},
    "brightness": {"value": 60, "at": 1756800000100},
    "restart": {"at": 1756800000200},
    "page": {"value": "room", "at": 1756800000300}
  }
}
```

The classic ESP32 controller reads the same payload with `slots` and
`slot_count` where a panel has `entities` and `entity_limit`, and with neither
`settings` nor `commands`:

```json
{
  "profile": "esp32_s3",
  "slot_count": 4,
  "player": "media_player.kitchen",
  "queue": "sensor.controller_queue",
  "playlists": "sensor.controller_playlists",
  "slots": [
    {
      "slot": 1,
      "entity": "light.controller_slot_1",
      "label": "DESK LAMP",
      "controls": ["toggle", "brightness"],
      "min_kelvin": 2000,
      "max_kelvin": 6535
    }
  ],
  "revision": 2098342174,
  "contract_version": 6
}
```

Real attributes, not an encoded string. Rules a client must follow:

- `player`, `queue`, and `playlists` are the controller entities this client
  reads. They are here so that a client needs no entity ID of its own: a URL,
  a token, and its own identifier are enough to bootstrap. A payload in which
  any of them is empty is not yet usable and must be retried, not cached.
- `slots` and `slot_count` are sent **only to the classic ESP32 controller**,
  and `entities` and `entity_limit` **only to panels**. A client reads the
  block it knows and ignores the other, exactly as it ignores `settings` and
  `commands` it has no use for. Neither block is ever sent to both.
- In `slots`, `entity` is always the **proxy**, never the entity the user
  selected. In `entities` it is always the **real entity**, because panels
  have no proxies; see **Registry entries** below.
- Unconfigured slots are **omitted**. Render what arrives, in `slot` order, and
  handle an empty `slots` list.
- `controls` is a closed list in both blocks: `toggle`, `brightness`,
  `color_temp`. An unknown value must be ignored, not treated as an error, so
  that a future control can be added without breaking released clients.
- `min_kelvin` and `max_kelvin` are present only when `controls` contains
  `color_temp`.
- `revision` is a checksum of the rest of the payload, not a counter. Equal
  values mean an unchanged configuration; any change produces a different
  value. A client uses it to skip a re-layout, never to order versions.
  `entities` is inside it, because the registry is layout. `contract_version`
  is deliberately outside it: the protocol number is not layout, and folding
  it in would restart every panel in a house to redraw a room page that did
  not move.
- `contract_version` is the version of this document the integration
  implements. It is sent to every client, panel or not, so that a client can
  see whether the other half of the contract is behind it. An absent value
  means an integration older than the version that introduced the field —
  see **Version compatibility** below.
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
  `screen_off_seconds`, which its own ESPHome device already owns as a *Screen
  Timeout* number. It does apply `player_skin`: the *Screen Style* select on
  its ESPHome device stays the value's owner and its local fallback, the way
  `config.ini` is the tablet's, and a named skin writes to it.

### Registry entries

`entities` is a panel's room controls. It replaces `slots` for panels and is
sent to nothing else. Where a slot list was a fixed number of numbered
positions, this is an ordinary list: a user adds as many entities as the
client profile allows, in any of the groups below, and removes them again.

```json
{
  "rid": "a3f1c92d",
  "entity": "light.desk_lamp",
  "name": "Настільна лампа",
  "domain": "light",
  "controls": ["toggle", "brightness", "color_temp"],
  "min_kelvin": 2200,
  "max_kelvin": 6500
}
```

- `rid` is **eight lowercase hex characters** and is the identity of the
  registry element, not of the entity behind it. It is minted when the element
  is created, never changes for as long as the element exists, and is never
  reused after one is deleted. A device that lets a user arrange its own grid
  stores `rid`, never `entity`: a Home Assistant entity ID is renamed by the
  user at will, and a layout keyed on one would scatter the next time somebody
  tidied their entity IDs. Two elements in one payload never share a `rid`.
- `entity` is the **real entity**, addressed directly with the ordinary Home
  Assistant service calls for its domain. There is no proxy. Both panels learn
  entity IDs at runtime and never needed one, and a registry with no upper
  bound would otherwise create an unbounded number of extra entities in Home
  Assistant. Entity IDs still come from the registry and are still
  per-installation: never hardcode one.
- `name` is what the tile says. It is the label the user typed, or the
  entity's `friendly_name` when they typed none, and it is UTF-8: Cyrillic and
  every other script survive intact.
- `domain` is the Home Assistant domain of `entity`, repeated here so that a
  client can pick a card without parsing the entity ID. It is one of the group
  domains below. **A client that cannot draw a domain ignores that element**,
  exactly as it ignores a control it does not know, so a group added later
  cannot break a client already in the field.
- `controls` is the same closed list as in `slots` — `toggle`, `brightness`,
  `color_temp` — and is resolved by the integration from the target's
  capabilities. A client renders from it and never parses
  `supported_color_modes` itself. As of this version only `light` and `switch`
  produce controls; every other group is carried with an empty list, because
  the cards that would draw them are not written yet.
- `min_kelvin` and `max_kelvin` appear only when `controls` contains
  `color_temp`, as in `slots`.
- The order of the list is the order to render in. It is the group order in
  the table below, and within a group the order the user added them.

`entity_limit` is how many elements the profile allows in total, across every
group. It is per client, because the limits answer different questions: the
tablet's registry never travels into a firmware image, and the ESP32's does.

| Client | `entity_limit` |
| --- | --- |
| T560 panel | 100 |
| ESP32-S3 panel | 64 |
| ESP32-S3 controller | — (no registry; it reads `slots`) |

The groups, in payload order:

| Group | `domain` | Cards in this version |
| --- | --- | --- |
| Lights | `light` | yes |
| Switches | `switch` | yes |
| Media players | `media_player` | no |
| Climate | `climate` | no |
| Covers | `cover` | no |
| Weather | `weather` | no |

### What version 6 breaks

Only panels, and only their room controls.

- **A panel's slots are gone and are not migrated.** The room controls of a
  T560 or a paired ESP32 have to be chosen again, in the panel's options. The
  entry keeps its identity, its token, its pairing and every other entity it
  owns; nothing has to be re-paired and nothing has to be reflashed to be
  configured again.
- **A panel's proxy entities are deleted.** `light.<panel>_slot_<n>` and
  `switch.<panel>_slot_<n>` are removed from the entity registry the first
  time the panel entry loads on this version. Anything that referenced one —
  an automation, a script, a dashboard card — must be pointed at the real
  entity instead, which is what the panel now addresses too.
- **A panel is no longer sent `slots`.** A panel build older than version 6
  reads a payload with no `slots` key and shows no room controls at all. Home
  Assistant raises the repair issue described under **Version compatibility**,
  and the remedy is the ordinary one for that panel: rebuild and deploy the
  tablet application, or install the ESP32 again from ESPHome Device Builder.

Nothing about the classic ESP32 controller changes. Its four slots, its four
proxies and its payload are exactly what they were.

### Panel settings

`settings` is a desired configuration, not an event: the newest payload simply
wins, and a client adopts it without acknowledging it. It is what used to be
edited in `config.ini` over SSH.

| Key | Unit | Range |
| --- | --- | --- |
| `poll_interval_ms` | milliseconds | 500 – 30000 |
| `playlist_poll_interval_ms` | milliseconds | 10000 – 3600000 |
| `screen_off_seconds` | seconds | 0, or 5 – 3600 |
| `player_skin` | name | the client's own, or absent |

Home Assistant clamps every value before it sends one; a client clamps again
rather than trusting the payload. `screen_off_seconds` is 0 for never.

`player_skin` names which of its layouts a client draws. The vocabulary is
**the client's own**, because the layouts are: the tablet has two and the
ESP32 three, and neither would know what to do with the other's names. Home
Assistant keeps the list on the client profile and offers only the names the
client it is talking to actually draws.

| Client | Names | What a name selects |
| --- | --- | --- |
| T560 panel | `modern`, `cassette` | The whole interface — player page, navigation bar and room controls alike |
| ESP32-S3 panel | `classic`, `minimal_ring`, `cover_card` | Which of the three home layouts the firmware shows |
| ESP32-S3 controller | — | Not a panel; it is sent no `settings` block at all |

Three rules make that workable across versions:

- **Absent is not a default.** A payload that does not carry `player_skin`
  means nobody has chosen, and the client keeps whatever it falls back to on
  its own — `config.ini` on the tablet, a restoring select in flash on the
  ESP32. A client must not read an absent key as a request for its first
  layout, or an unconfigured Home Assistant would silently overrule the
  device's own file.
- **An unknown name is a choice that cannot be honoured.** A client draws its
  own default rather than nothing, so a layout added to the integration
  reaches a device already in the field as a name it has never heard of and
  changes nothing there.
- **The list is open.** Adding a layout to a client means adding its name to
  that client's profile and teaching that client to draw it. No other client
  is affected, and neither is this table's shape.

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
runtime. The T560 panel builds its whole room page from `entities`. The
classic ESP32 takes only the labels and the visibility of its four buttons
from `slots`: everything else about those buttons, including the entity IDs
and the service domains, is resolved while compiling and cannot follow a
configuration change.

### Proxy entities

Proxies belong to the classic ESP32 controller and to nothing else. They exist
because that firmware resolves both the entity ID and the service domain of
its four buttons while compiling, so a stable entity ID it can be flashed
against is the only way it can follow a slot change made in the Home Assistant
UI. Every other client learns entity IDs at runtime and addresses the real
entity; as of version 6 that is what panels do, through `entities`.

A proxy mirrors the state of the entity selected for its slot and forwards
actions to it. A proxy whose source is missing is `unavailable`; the other
controller functions keep working. Clearing a slot removes its proxy.

A slot's domain is fixed when the slot is created, because the ESP32 resolves
both the entity ID and the service domain of its four buttons at compile time.

Proxy lights mirror the colour modes of their target: `onoff`, `brightness`, or
`color_temp` with the target's Kelvin bounds. They forward `brightness` and
`color_temp_kelvin` on turn-on. Colour, effects, and every other light feature
are **not** forwarded. The classic ESP32 firmware must not address the target
entity directly to work around that; the slot mechanism is the only supported
path for it. A panel addresses real entities by design and is not covered by
this rule at all.

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
  "contract_version": 6,
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
  It is a release number and answers a different question from
  `contract_version`: it says when the build shipped, not what it
  understands.
- `contract_version` is the version of this document the panel implements.
  It is optional in the sense that an older panel does not send one, and an
  absent value is read as "older than the integration" rather than as an
  error — see **Version compatibility** below.
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

## Version compatibility

The number above is not decoration: both halves of the contract carry it in
code and compare it, because a panel and the integration are released
separately and either can be the older one.

- the integration publishes its own as `contract_version` in the config
  sensor, to every client;
- a panel reports its own as `contract_version` in its status report.

The number to compare is this document's version, never a release number.
`integration-v1.2.0` and `panel-v0.5.0` say when a build shipped, not what it
understands: two builds a month apart may implement the same protocol, and two
builds an hour apart may not.

**An absent value means older.** Every build on either side from before this
rule existed sends nothing, so a missing `contract_version` is read as 0 and
compared like any smaller number. It is never an error, and neither side may
refuse a payload or a report over it.

### The integration's side

Home Assistant raises a repair issue naming the panel when that panel's
contract version is lower than its own, and clears it once the panel reports
the current one.

**Every panel is checked the same way**, because every panel behaves the same
way: the tablet and the paired ESP32 firmware both pair, both poll the config
sensor and both report. Only the remedy differs, so the client profile picks
the wording of the issue and nothing else — a tablet is rebuilt and copied to
the device, an ESP32 is installed again from ESPHome Device Builder.

A panel that has **never reported at all** is the case that matters in
practice, because it is otherwise invisible: its battery, screen, page and
settings entities simply sit unavailable forever with nothing to explain them.
Silence alone cannot prove a stale build — a device is also silent when it is
switched off — so what is asked is whether the panel has *ever* reported in
the life of the installation, which the integration already records outside
its own memory as the device's software version. A device that is merely off
carries one; a device that cannot report never has. A grace period after the
entry loads covers a panel that was paired moments ago or is still booting,
and the issue clears itself the moment the panel reports.

### A client's side

A client that finds the integration older than itself reports it where its own
user looks, and treats it as a configuration warning rather than a lost
connection: Home Assistant answered, it simply speaks an older protocol. The
T560 panel puts it on its status line; the paired ESP32 firmware writes it to
its ESPHome log, once per version seen, because it has no line to spare on
screen and a warning every poll cycle would bury everything else.

### Clients that do not participate

Reporting a contract version is optional in both directions, and the classic
ESP32 firmware does neither. It is a controller rather than a panel: it never
reports, so the integration has no version of its own to compare and raises
nothing about it, and it ignores `contract_version` in the config sensor
exactly as it ignores `settings` and `commands`. Nothing about that firmware
changes, and no change to it is required.

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

1. Update this file first, including the contract version at the top of it.
2. Raise the same number in the two places that hold it in code:
   `CONTRACT_VERSION` in `custom_components/media_controller/contract.py` and
   `T560_PANEL_CONTRACT_VERSION` in `clients/t560/src/app_config.h`. A
   constant that has drifted from this document is worse than no constant,
   because both sides compare against it.
3. Bump `version` in `custom_components/media_controller/manifest.json`.
4. Update every consumer in the same pull request: `firmware/`, `clients/`.
5. If a released client cannot read the new shape, raise the contract version
   above and keep the old shape until every client is updated.

Tests that protect the contract:

- `tests/test_transformations.py` — payload construction, including which of
  `slots` and `entities` each client kind is sent;
- `tests/test_registry.py` — `rid` generation and stability, the per-profile
  limits, an empty registry and one at its limit;
- `tests/test_profiles.py` — which controls a client is told to draw;
- `tests/test_migration.py` — the version 1 slots keep their numbers;
- `clients/t560/tests/test_panel_config.c` — payload parsing on the client
  side, including an unknown control name;
- `tests/test_pairing.py` — the rules that guard the provisioning endpoint;
- `tests/test_panel_state.py` — the settings, the command channel, and the
  validation of a status report;
- `tests/test_contract.py` — the rule that decides a panel is running a build
  older than the contract, including the never-reported case;
- `clients/t560/tests/test_power_button.py` — the tablet side of the settings
  and of the display request.
