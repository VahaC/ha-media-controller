# Client contract

Everything a client needs from Home Assistant is listed here. The
`media_controller` integration is the only producer; the ESP32-S3 firmware and
the T560 panel are consumers. Nothing else may be assumed.

Treat this file as the change-control surface: a change to anything below
affects released devices in the field. A change to code that is not described
here affects one component only.

Contract version: **7** (matches integration `1.4.x`).

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

Version 6 also gives a panel two things the registry needs to be usable on the
device: `skin_select`, the entity a panel writes when a person picks a skin on
the tablet rather than in Home Assistant, and an endpoint where a panel keeps
a durable copy of the grid it arranges its registry into. Both are additive
and optional, and the classic ESP32 controller is sent neither. See **Panel
layout endpoint** below.

The classic ESP32 controller is untouched by all of it. It still receives
`slots`, still addresses proxies, and still behaves exactly as it did under
version 5: it resolves both entity IDs and service domains while compiling, so
proxies are the only way it can follow a change made in the Home Assistant UI,
and a registry it cannot read would be of no use to it. It is sent no
`entities` block, exactly as it is sent no `settings` and no `commands`.

Version 7 is additive again. It defines the current registry card vocabulary:
`climate` and `cover` controls, and read-only `weather` and `sensor` blocks,
alongside the existing `light` and `switch` cards. A client may implement only
the domains and controls its hardware and interface can draw; it ignores the
rest without rejecting the payload.

The sixth group, `media_player`, is no longer offered: a panel already plays
from a media player of its own, chosen on the same page and drawn by the
player card, so a second one in the registry only took up a place. The payload
is unchanged by that — an element of any domain still travels, and a client
still ignores one it cannot draw — so nothing about this version moves. A
`media_player` element stored by an older build is retired the next time its
panel is saved.

The **cover card** is part of version 7. A `cover` element resolves to as many
as three controls — `toggle`, `position` and `stop` — and a blind, a shutter
or an awning becomes something a client can act on rather than a tile that
answers nothing. How far open a cover is adds no field to the payload: it
arrives as an ordinary attribute of the entity a client already polls. The
T560 panel draws the full cover card; the paired ESP32 draws the toggle half
of it — OPEN/CLOSED with a tap — because its panel profile strips `position`
and `stop` before they reach the device, and it has no slider gesture left
to spend on them.

The **weather block** is also part of version 7. A `weather` element
still carries an empty `controls` list, because there is nothing to act on:
no new control name is introduced and no field is added to the payload,
because the condition is the entity state itself and the temperature and
humidity arrive as ordinary attributes of the entity a client already polls.
What changes is only what a client draws: a block with the forecast — the
condition and the temperature, with the humidity where it is reported —
instead of a button that answers nothing. A tap on it acts on nothing, it
never shows a pressed state, and it never opens the adjustment sheet.

Both panels draw the block: the T560 panel and the paired ESP32 firmware
alike. A client that cannot draw a domain still ignores that element, as the
rule below allows — it is just that no maintained client is such a client
for weather any more.

That is deliberate, and the rule that makes it possible is already written
below: **a client that does not know a value in `controls` ignores it, and a
client that cannot draw a domain ignores that element.** A panel running
version 6 that is handed a version 7 payload ignores the names and domains it
does not know and otherwise keeps working. Clients that both report contract
version 7 may still draw different subsets of the registry.

What version 7 adds, precisely:

- one value in `controls`: `target_temperature`, a single setpoint a card can
  move;
- three keys beside it — `min_temp`, `max_temp` and `target_temp_step` —
  present only when `controls` contains `target_temperature`, exactly as
  `min_kelvin` and `max_kelvin` are present only with `color_temp`;
- two cover controls, `position` and `stop`; the current position remains an
  ordinary state attribute rather than part of the config payload;
- `climate` and `cover` gain actionable card definitions, while `weather` and
  `sensor` are defined as read-only blocks.

`toggle` is **not** new and means on a thermostat what it has always meant:
the element can be turned off and on again. See **Climate cards** below.

**Card appearance** was added after version 7 and moves no version number,
for the same reason **Room states** below does not: nothing already in the
payload changes shape, and a client that knows none of it behaves exactly as
it did before any of it existed. It is three things:

- one optional key on a registry element, `icon`, naming a picture from a
  catalog the integration publishes. An older client ignores it and draws
  whatever it drew before;
- two read-only endpoints, **Card artwork** below, that publish the catalog
  and serve one picture at a time. A client that does not ask never learns
  they exist;
- one write endpoint, **Card appearance endpoint** below, through which a
  panel that hosts its own layout editor asks Home Assistant to store the
  display name and the icon of an element it already draws.

`name` is not new either, and neither is where it comes from. What is new is
that something can now set it: the field has been in the registry since
version 6 and no flow wrote it, so every tile has been named after its Home
Assistant entity. See **Display names** below.

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
  "contract_version": 7,
  "skin_select": "select.kitchen_tablet_player_skin",
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
  "contract_version": 7
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
- `controls` uses the closed vocabulary `toggle`, `brightness`, `color_temp`,
  `target_temperature`, `position`, `stop`. An unknown value must be ignored,
  not treated as an error, so that a future control can be added without
  breaking released clients. `target_temperature`, `position` and `stop`
  appear only in `entities`; the classic ESP32 firmware's fixed `slots` are
  lights and switches.
- `min_kelvin` and `max_kelvin` are present only when `controls` contains
  `color_temp`.
- `min_temp`, `max_temp` and `target_temp_step` are present only when
  `controls` contains `target_temperature`, and only in `entities`.
- `revision` is a checksum of the rest of the payload, not a counter. Equal
  values mean an unchanged configuration; any change produces a different
  value. A client uses it to skip a re-layout, never to order versions.
  `entities` is inside it, because the registry is layout. `contract_version`
  is deliberately outside it: the protocol number is not layout, and folding
  it in would restart every panel in a house to redraw a room page that did
  not move.
- `skin_select` is the entity ID of this panel's *Player skin* select, and is
  sent **only to panels**, and only to one whose profile draws more than one
  skin. It is the single entity in the payload a client **writes** rather than
  reads: a panel that offers a skin picker on the device calls
  `select.select_option` on it and changes nothing locally, so Home Assistant
  stays the owner of the value and the new skin arrives back the ordinary way,
  in `settings.player_skin`. It is outside `revision` for the same reason
  `contract_version` is: which entity holds the skin is not layout. A client
  that finds it absent simply has no local skin picker to offer.
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
  "icon": "desk-lamp",
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
  every other script survive intact. Only the name in force travels: a client
  is not told which of the two it is looking at, because sixty-four elements
  times two names is a payload the paired ESP32 reads out of a fixed buffer
  for a distinction nothing draws. See **Display names** below.
- `icon` is the catalog identifier of the picture the tile draws, and it is
  **absent when the user chose none**, which is every element until somebody
  chooses one. A client that does not know the key ignores it and draws what
  it drew before; a client that does draws the picture and falls back to its
  own artwork when it cannot. It is a name and never a position: the catalog
  may be reordered, added to or shortened without moving anybody's icon. See
  **Card artwork** below.
- `domain` is the Home Assistant domain of `entity`, repeated here so that a
  client can pick a card without parsing the entity ID. It is one of the group
  domains below. **A client that cannot draw a domain ignores that element**,
  exactly as it ignores a control it does not know, so a group added later
  cannot break a client already in the field.
- `controls` is the closed list `slots` uses, plus the three values only a
  registry element can carry: `toggle`, `brightness`, `color_temp`,
  `target_temperature`, `position`, `stop`. It is resolved by the integration
  from the target's capabilities. A client renders from it and never parses
  `supported_color_modes` or `supported_features` itself. As of this version
  `light`, `switch`, `climate` and `cover` produce controls; `weather` and
  `sensor` are carried with an empty list and drawn as a reading rather than
  a control — see **Weather blocks** and **Sensor blocks** below — as is any
  domain that is no longer a group.
- `min_kelvin` and `max_kelvin` appear only when `controls` contains
  `color_temp`, as in `slots`.
- `min_temp`, `max_temp` and `target_temp_step` appear only when `controls`
  contains `target_temperature`. See **Climate cards** below.
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
| Climate | `climate` | yes, since version 7 |
| Covers | `cover` | yes, in version 7 |
| Weather | `weather` | yes, as a reading |
| Sensors | `sensor` | yes, as a reading |

The table describes the contract vocabulary, not a requirement that every
client draw every domain. A client ignores a domain it cannot draw, so the
T560 and paired ESP32 may implement different subsets while both speak
contract version 7.

### Display names

A registry element carries the name its tile shows. Until now nothing wrote
it: the field existed, the payload carried it, and every flow left it empty,
so a tile was named after its Home Assistant entity and there was no other
possibility. A panel that hosts its own layout editor can now set it through
the **Card appearance endpoint** below.

The rules, and they are the integration's rather than any client's, because
the integration is what stores the value:

- it is **UTF-8 and every script is accepted**. Cyrillic, Greek, CJK and emoji
  are ordinary names, and one survives a save, a restart and a restore
  unchanged;
- leading and trailing whitespace is **trimmed**, so a field cleared by typing
  a space is a field that was cleared;
- **an empty name means "use the Home Assistant entity's own name"**. That is
  the one value with a meaning of its own, and it is what makes the field
  clearable without a second control. An element whose name is empty follows
  its entity through a rename, exactly as it did before names could be set;
- **control characters are refused**, not stripped. A newline in a tile label
  is somebody pasting the wrong thing;
- the length is bounded at **64 characters** — characters, not bytes, so a
  Cyrillic name may be exactly as long as a Latin one. The bound exists
  because the paired ESP32 holds the whole registry in RAM and reads it out of
  a fixed response buffer.

Setting a display name **never renames the Home Assistant entity**. The
entity keeps its own name, its own entity ID and its own registry row, and a
person who wants those changed changes them where Home Assistant keeps them.

### Climate cards

New in version 7, and the whole of what that version adds. A `climate`
element is resolved the way a `light` is: the integration reads the
thermostat's capabilities and sends the controls a card may draw, and a
client never inspects `supported_features` itself.

```json
{
  "rid": "7c41b8e0",
  "entity": "climate.hall",
  "name": "Hall",
  "domain": "climate",
  "controls": ["toggle", "target_temperature"],
  "min_temp": 7,
  "max_temp": 35,
  "target_temp_step": 0.5
}
```

Each control is claimed only on evidence, and either may be absent:

- **`toggle`** means the thermostat can be turned off and on again. It is
  claimed when the entity lists `off` among its `hvac_modes`, which is what
  Home Assistant's own `climate.turn_off` acts on, or when it sets both the
  `TURN_ON` and `TURN_OFF` feature bits itself. `toggle` is the same value,
  with the same meaning, that a light or a switch carries; it is not new and a
  client already honours it.
- **`target_temperature`** means the entity has a **single** setpoint. An
  entity that offers only a high and a low — `TARGET_TEMPERATURE_RANGE` and
  not `TARGET_TEMPERATURE` — gets no setpoint control at all, because there is
  no one number a card could move and writing the wrong field would be worse
  than drawing nothing.

The three bounds:

- they are **unitless numbers**, in whatever unit the entity itself reports.
  Home Assistant converts nothing here and the payload names no unit, because
  a unit is not a capability: a client draws a bare degree sign and the number
  it was given. A client must not assume Celsius;
- `target_temp_step` is what one press or one notch moves the setpoint by. It
  is never zero;
- `max_temp` is always greater than `min_temp`. Where the entity reports a
  range that is not, the integration substitutes Home Assistant's own
  defaults rather than sending an inverted one.

What a client draws is its own business, and the two panels differ:

| Client | Tap | Beyond a tap |
| --- | --- | --- |
| T560 panel | `toggle` | The setpoint on the same sheet the brightness of a light uses |
| ESP32-S3 panel | `toggle` | A long press sweeps the setpoint, as it sweeps brightness for a light |
| ESP32-S3 controller | — | Not a panel; it reads `slots` and is sent no `entities` |

Both panels also **show** the room temperature the thermostat reports, which
needs nothing from this document: it is an ordinary attribute of the entity a
client already polls.

A card an element gives no `target_temperature` still draws and still
toggles. A card whose element gives neither control is drawn as a reading
rather than a control, which is the honest thing to show for a thermostat
this integration can offer no action on.

### Cover cards

Part of version 7. A `cover` element is resolved the way a `climate` one is:
the integration reads the cover's feature bits and sends the controls a card
may draw, and a client never inspects `supported_features` itself.

```json
{
  "rid": "3f9a01cd",
  "entity": "cover.living_blind",
  "name": "Blind",
  "domain": "cover",
  "controls": ["toggle", "position", "stop"]
}
```

A cover carries **no bounds**. Unlike a setpoint, a position is a percentage
by definition: 0 is shut and 100 is fully open, in every house and every unit
system, so there is nothing to send alongside the control.

Each control is claimed only on evidence, and any of them may be absent:

- **`toggle`** means the cover can be both opened and closed. It is claimed
  only when the entity sets **both** the `OPEN` and `CLOSE` feature bits,
  because `cover.toggle` decides between the two from the current state: a
  cover that can only be opened would be given a control that works once and
  is then refused. `toggle` is the same value with the same meaning that a
  light, a switch or a thermostat carries; it is not new.
- **`position`** means the entity sets `SET_POSITION` and a card may ask for
  any percentage. A cover without it still opens and closes; it simply has no
  half way.
- **`stop`** means the entity sets `STOP`. It is the one control this card
  type needed that no other has: a blind travels for seconds and is stopped
  part way on purpose, which no percentage can express on a cover that reports
  no position at all.

How far open the thing currently is, `current_position`, is **state and not a
capability**: it is an ordinary attribute of the entity a client already
polls, it changes while the cover is simply being used, and it is therefore
not in the payload. A client reads it the way it already reads a lamp's
brightness or a room's temperature.

What a client draws is its own business, and the two panels differ:

| Client | Tap | Beyond a tap |
| --- | --- | --- |
| T560 panel | `toggle` | The percentage on the sheet a light's brightness uses, and a STOP button beside it |
| ESP32-S3 panel | `toggle` | Nothing; `position` and `stop` are stripped by its panel profile, so the card reads OPEN/CLOSED and a tap toggles |
| ESP32-S3 controller | — | Not a panel; it reads `slots` and is sent no `entities` |

A card whose element gives no `position` still draws and still toggles, and a
card that gives none of the three is drawn as a reading rather than a
control — the honest thing to show for a cover this integration can offer no
action on.

### Weather blocks

A `weather` element carries an empty `controls` list, because there is
nothing to act on: no new control name is introduced and no field is added
to the payload.

```json
{
  "rid": "9d2e7a41",
  "entity": "weather.home",
  "name": "Home",
  "domain": "weather",
  "controls": []
}
```

The condition is the entity state itself (`sunny`, `partlycloudy`, ...),
and the temperature and humidity are ordinary attributes of the entity a
client already polls. A client reads them the way it already reads a lamp's
brightness or a room's temperature, and draws the temperature with a bare
degree sign: the payload names no unit, because a unit is not a capability.

Where the card is large enough, the block lists the coming days beneath the
current reading — weekday columns with the high and the low, high/low
curves and precipitation bars where they fit, plain rows where only they
do, as many as fit. The days come from the `weather.get_forecasts`
service, which each client asks itself no oftener than every half hour:
slow-moving data needs no faster poll, and the payload carries none of it,
so this adds no field and no version.

What a client draws is its own business, and the two panels differ:

| Client | Tap | Beyond a tap |
| --- | --- | --- |
| T560 panel | Nothing; the block is a reading, not a button | Nothing; it never opens the adjustment sheet |
| ESP32-S3 panel | Nothing; the block is a reading, not a button | Nothing; a long press moves no value |
| ESP32-S3 controller | — | Not a panel; it reads `slots` and is sent no `entities` |

A block whose entity reports no temperature still draws and still reads:
it says the condition alone, or the humidity alone, rather than nothing.

### Sensor blocks

A `sensor` element carries an empty `controls` list, because there is
nothing to act on: no new control name is introduced and no field is added
to the payload.

```json
{
  "rid": "b71f0c2e",
  "entity": "sensor.kitchen_temperature",
  "name": "Kitchen",
  "domain": "sensor",
  "controls": []
}
```

The value is the entity state itself (`21.5`, `on`, ...), and the unit is the
ordinary `unit_of_measurement` attribute of the entity a client already
polls. A client reads them the way it already reads a lamp's brightness or
a room's temperature, and draws the value followed by the unit where one is
reported — `21.5 °C` — and the bare value where none is.

What a client draws is its own business, and the two panels agree:

| Client | Tap | Beyond a tap |
| --- | --- | --- |
| T560 panel | Nothing; the block is a reading, not a button | Nothing; it never opens the adjustment sheet |
| ESP32-S3 panel | Nothing; the block is a reading, not a button | Nothing; a long press moves no value |
| ESP32-S3 controller | — | Not a panel; it reads `slots` and is sent no `entities` |

A block whose entity reports `unavailable` or `unknown` still draws: it says
the name alone, rather than nothing. A tap on it acts on nothing, it never
shows a pressed state, and it never opens the adjustment sheet.

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

Both panels also show a **picture of each layout** in the editor they serve,
because a name says nothing about one. Those pictures are the client's own
business and appear nowhere in this document: they never cross the boundary
this file describes. Each is a static asset the client carries, one per name
in the table above, and a name with no picture is still offered. See
`clients/t560/README.md` and `docs/ESP32_PAIRED_CONTROLLER.md`.

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
  "contract_version": 7,
  "page": "player",
  "uptime_seconds": 4210,
  "wifi_dbm": -53,
  "temperature_c": 31.5,
  "editor_url": "http://192.168.1.105:8730/",
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
- `editor_url` is where the layout editor this panel serves on its own
  hardware answers, and it becomes the link on the panel's Home Assistant
  device page. It is reported rather than worked out by Home Assistant,
  because only the client knows the port it bound and which of its own
  interfaces is routable. It is optional in both directions: a panel that
  serves no editor — a tablet with `web_port=0`, a client that has none —
  omits it, and the link is then taken off the device rather than left
  pointing at a port nothing answers on. Home Assistant accepts an ordinary
  `http` or `https` address of a host, at most 255 characters and with no
  credentials in it, and silently ignores anything else: the value becomes a
  link offered on the strength of one HTTP request.

Answers: `200` with `{"status": "ok"}`; `400` for an unusable body; `403` when
the token belongs to another account; `404` when no loaded panel has that ID.

## Card artwork

```text
GET  /api/media_controller/icons
GET  /api/media_controller/icon/<icon_id>/<variant>
```

The pictures a room card can draw. They used to be compiled into each client —
six in the ESP32 firmware, eight in the tablet — and a card stored a **1-based
index into that array**, so the set could grow only by reflashing every device
in the house, and reordering it would have silently moved everybody's icons.
The catalog is the integration's now, a card stores a stable identifier, and a
client downloads the picture it needs.

- an **icon identifier** is lowercase letters, digits and hyphens, at most 32
  characters, and it does not begin with a hyphen. It is stable for the life
  of the catalog and it is what a registry element stores. The first eight are
  `light-1`, `light-2`, `desk-lamp`, `desk-led-strip`, `fan`, `ac`, `blind`
  and `weather` — the names the two clients already carried compiled in, so
  every icon anybody has already chosen maps to itself and nothing migrates;
- the **catalog** is a document and carries no image data at all. That is what
  makes it safe to fetch on a schedule: it changes when the integration is
  upgraded and never otherwise, and a `revision` says when it did, so a client
  that has read it once need never read it again;
- it is deliberately **not a block on the config sensor**, for exactly the
  reason the layout backup is not one: that sensor is polled every
  `poll_interval_ms` — once a second by default — and a catalog on it would
  travel to every panel in the house every second for a list that changes when
  somebody updates HACS;
- a **variant** is a supported pixel size or the literal `png`. Anything else
  is a 404. An open size parameter would be an invitation to ask for 4096 and
  find out what the device does with it;
- both routes are **authenticated the ordinary way**, with the token the panel
  was handed when it paired. The token never reaches a browser: the editor
  pages use the separate public PNG preview route described below.

Both the T560 and paired ESP32 editors load PNG previews directly from
`GET /api/media_controller/icon-preview/<icon_id>` on its configured Home
Assistant origin. This additional route requires no authentication and serves
only catalog-listed PNG files shipped with the integration; it exposes no
installation data. The catalog and existing variant routes remain authenticated.
The browser must be able to reach that origin (including HTTPS compatibility).
Each device downloads artwork only for cards in its layout, never for editor
previews. Editor state includes `icon_preview_base`, the public URL prefix.

The catalog:

```json
{
  "revision": 2098342174,
  "sizes": [40],
  "esp32_bytes": 6408,
  "icons": [
    {"id": "desk-lamp", "label": "Desk lamp"},
    {"id": "blind", "label": "Blind"}
  ]
}
```

`label` is what an editor calls the icon. Nothing stores it and nothing
compares it, so it may be changed freely; `id` may not.

The two variants:

- **`png`** is the source artwork, for a client that can decode one. The T560
  panel fetches these for its layout cards;
- **a pixel size** is the picture pre-rendered to exactly that size, in
  exactly the bytes LVGL blits: an eight-byte header — the ASCII `MCI1` and
  the size twice, as two little-endian 16-bit values — followed by ARGB8888
  in the little-endian B, G, R, A order LVGL reads. The only published size is
  **40**, which is what a card on the paired ESP32 draws, and `esp32_bytes`
  says what one weighs so a client can size its buffer and refuse a truncated
  download without parsing anything.

  It is pre-rendered rather than served as a PNG because of a hardware fact,
  not a preference: the ESP32 firmware sets `LV_COLOR_16_SWAP` and leaves
  `LV_DRAW_SW_SUPPORT_SWAPPED` off, so LVGL's software renderer cannot
  transform a source at all — see AGENTS.md — and that device has no PNG
  decoder to spare either.

What a client must do with all of it:

- **share one decoded picture between every card that names it.** The cache is
  keyed on the identifier, so a page of sixty-four cards naming three pictures
  holds three of them and not sixty-four;
- **keep the cache bounded**, and prefer external RAM where there is any;
- **never persist the catalog.** It is small, it is cheap to fetch, and a copy
  in flash is a copy that goes stale;
- **fall back rather than fail.** An identifier the catalog does not publish,
  a download that does not arrive, a Home Assistant that cannot be reached and
  a picture of the wrong shape all mean the same thing to a card: draw the
  artwork the client carries itself. A missing icon never stops a card, a room
  page, or navigation.

Answers: `200` with the document or the bytes; `404` for an identifier the
catalog does not publish, a variant this build does not serve, and a file the
installation does not carry. A request whose identifier is not of the shape
above is a `404` before anything is opened: the identifier is resolved to a
catalog row and the filename is built from the row, so a path cannot be
expressed in one however it is spelled or escaped.

## Card appearance endpoint

```text
POST /api/media_controller/panel_card/<panel_id>
```

```json
{"rid": "a3f1c92d", "name": "Настільна лампа", "icon": "desk-lamp"}
```

A panel that hosts its own layout editor uses this to store the two things a
person can say about how a card is drawn. It is the narrowest endpoint here
and it is written that way on purpose: the editor a panel serves has no
authentication of its own — see `docs/ESP32_PAIRED_CONTROLLER.md` — and the
whole of that decision rests on there being nothing worth reaching through it.

- it changes **one element of one panel's registry, and nothing else**. The
  `rid` must already be in *that* panel's registry. There is no path here that
  creates an element, deletes one, points one at a different entity, names an
  entity at all, calls a service, or touches any other config entry;
- **a key that is absent means "leave this alone"** and a key that is present
  means "set it to this, including to nothing". The difference matters: a card
  whose name field simply shows the Home Assistant entity's own name must not
  have that name stored as a custom one because somebody changed its icon, or
  it would stop following the entity through a rename;
- `name` follows the rules in **Display names** above;
- `icon` is an identifier the catalog publishes, or `""` for automatic. There
  is no third option: no URL, no path and no upload;
- authentication and isolation are the status endpoint's, unchanged. The
  request carries the panel's own access token and Home Assistant accepts it
  only from the Home Assistant user created for **that** panel. One panel
  cannot rename another's cards;
- nothing is stored on the device. Home Assistant owns the registry, and the
  new name and icon arrive back the ordinary way, in the next config poll —
  which is also what makes a house with two panels agree about what a lamp is
  called without either of them telling the other.

Answers: `200` with `{"status": "ok", "rid": ..., "name": ..., "icon": ...}`,
echoing what was actually stored, so that a caller can see an empty name come
back as the entity's own; `400` for a body that is not usable, a name that is
too long or carries control characters, and an icon the catalog does not
publish; `403` when the token belongs to another account; `404` when no loaded
panel has that ID, and when that panel's registry has no such `rid`.

## Panel layout endpoint

```text
GET  /api/media_controller/panel_layout/<panel_id>
PUT  /api/media_controller/panel_layout/<panel_id>
```

A panel that lets a person arrange its registry into a grid keeps that
arrangement on the device, where it is edited. This endpoint is the durable
copy of it, and the only thing here that Home Assistant could not lose without
losing something a client cannot rebuild: wiping the tablet, reinstalling the
application, or replacing the hardware loses the file, and a panel derives the
same `panel_id` from the same machine, so it finds its layout again.

- the body is an **opaque blob**. Home Assistant stores the bytes it is handed
  and returns them unchanged; it never parses them, and no key inside them
  means anything to it. The grid format belongs to the client that draws it,
  which may change it without a change to this document;
- it is **its own endpoint and not a block on the config sensor**, deliberately.
  The config sensor is polled every `poll_interval_ms` — once a second by
  default — and a hundred-card grid is several kilobytes: it would travel to
  the device every second for data read twice in the life of a panel. Keeping
  it out also keeps it out of `revision`, so saving a layout cannot make the
  panel rebuild the page it has just saved;
- authentication and isolation are the status endpoint's, unchanged. The
  request carries the panel's own access token, and Home Assistant accepts it
  only from the Home Assistant user created for **that** panel. One panel can
  neither read nor overwrite another's layout;
- a body larger than **16 KiB** is refused. Home Assistant stores whatever it
  is given, so the ceiling is what stops a client growing its storage without
  limit;
- the layout **outlives the config entry**. Removing a panel from Home
  Assistant does not delete it, because surviving a reinstall is the entire
  purpose.

`PUT` answers `200` with `{"status": "ok"}`; `403` when the token belongs to
another account; `404` when no loaded panel has that ID; `413` when the body
is over the ceiling.

`GET` answers `200` with the stored bytes as `text/plain`; `404` with
`{"status": "no_layout"}` when that panel has never saved one, and the same
`403` and `404` as above.

A client uses it twice: once after every local save, so the copy is current,
and once when a person asks for the layout to be restored. Nothing polls it.

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
- Room states ride the config sensor poll, which panels read about once a
  second; see **Room states** below.
- Clients poll Home Assistant for entity state. They must request single
  entities (`/api/states/<entity_id>`), never the full `/api/states` list.

### Room states

The current state of every registry element, rendered by the integration
into the config sensor beside the registry:

```json
{
  "room_states": {
    "a3f1c92d": ["on"],
    "7c41b8e0": ["heat", 21.5, 22.0],
    "9d2e7a41": ["sunny", 15.5, 62],
    "b71f0c2e": ["21.5", "°C"]
  }
}
```

One small array per element, keyed by `rid`:

- a light, a switch and a cover travel as the bare state — `on`, `open`,
  `unavailable` — because for them the state is the whole of the content;
- a thermostat travels as the mode, the room temperature and the setpoint;
- a weather block as the condition, the temperature and the humidity;
- a sensor block as the value and the unit;
- a reading the entity does not report travels as JSON null, which a client
  reads as "no reading" rather than as zero;
- an element whose entity is gone reads as `unknown` rather than keeping a
  stale value.

The block exists because a panel cannot render these itself. Its first shape
was a template the device POSTed to `/api/template`, one request for every
card on the page — but that endpoint answers administrators only, and a
panel's token belongs to a dedicated non-administrator user, so Home
Assistant refused it with 401 and every card stayed blank. The tablet never
noticed: it asks for one entity at a time through `/api/states/<entity_id>`,
which any caller with read access may use. The integration renders here what
the ESP32 panel can no longer ask for, and the ESP32 panel reads it out of
the same poll that carries the registry, at no extra request of its own.

Rules a client must follow:

- `room_states` is outside `revision`, exactly like `settings` and
  `commands`: states move constantly while the house is simply being used,
  and a re-layout on every toggle would rebuild the room page out from
  under the finger that caused it;
- it is sent **only to panels**, and only beside an `entities` block. The
  classic ESP32 controller is sent neither: it learns its four states over
  the ESPHome native API;
- a client that has no use for the block ignores it. The T560 panel reads
  per-entity state and ignores the whole of it; an older ESP32 panel reads
  nothing and behaves exactly as it did before the block existed, which is
  why this addition moves no version number.

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
- `tests/test_profiles.py` — which controls a client is told to draw,
  including the climate rules and the card domains;
- `tests/test_migration.py` — the version 1 slots keep their numbers;
- `clients/t560/tests/test_panel_config.c` — payload parsing on the client
  side, including an unknown control name, a climate element and its bounds,
  the registry limit, and the skin select;
- `clients/t560/tests/test_panel_grid.c` — the client-side layout the backup
  endpoint carries: what is a usable grid and what is dropped;
- `tests/test_layout_backup.py` — the layout a panel stores here: that it is
  opaque, private to one panel, and bounded;
- `tests/test_icon_catalog.py` — the icon identifiers and the variants: that
  an identifier is a key and never a path, that a reordered catalog moves
  nothing, and that the pre-rendered variant is exactly the shape it claims;
- `tests/test_card_appearance.py` — display names: trimming, the bound,
  Unicode, clearing, refusal of control characters, and setting the name and
  the icon of one element by `rid` without touching another;
- `tests/test_pairing.py` — the rules that guard the provisioning endpoint;
- `tests/test_panel_state.py` — the settings, the command channel, and the
  validation of a status report;
- `tests/test_contract.py` — the rule that decides a panel is running a build
  older than the contract, including the never-reported case;
- `clients/t560/tests/test_power_button.py` — the tablet side of the settings
  and of the display request.
