# Room slots

Specification for moving room-control configuration out of client files and
into Home Assistant. It implements [ROADMAP.md](ROADMAP.md) item 1 and replaces
the four fixed room slots of integration `0.7.x`.

Status: **implemented** in integration `0.8.2` and firmware `0.8.0`. A panel
announces itself, is added from the discovery card, and is handed its own
access token, so nothing about it is configured on the tablet. What is left
out of scope here is moving the tablet-local settings — `[panel]` and
`[camera]` — into Home Assistant; see
[Still on the tablet](#still-on-the-tablet). Contract version: **2**.

## Goal

Adding a client device asks which device it is, states how many room controls
that device can drive, and shows one form with exactly that many slots. The
user puts any entity into any slot. Each client then draws the controls that
the entity in the slot actually supports — a dimmable lamp gets a brightness
control, a plug gets a toggle — without editing a file on the device.

## Decisions

These are settled. They are recorded here because several of them constrain
everything below.

| # | Decision | Consequence |
| --- | --- | --- |
| 1 | Both clients address **proxy entities**, never the target directly | Slot domain (`light` / `switch`) is fixed when the slot is created |
| 2 | Client profiles are a **static registry** in the integration | A new client type is a code change, not a UI action |
| 3 | ESP32 has no entry of its own | Its four slots stay on the controller config entry, where they already are |
| 4 | The form shows **exactly N slots**; empty slot = tile hidden | No "add another" loop |
| 5 | Every slot has a **label field**; empty falls back to `friendly_name` | |
| 6 | First iteration supports **`light` and `switch` only** | No RGB, no `fan` domain, no `climate`, no `cover` |
| 7 | The integration **normalizes capabilities** | Clients render from a plain list and never parse `supported_color_modes` |
| 8 | Legacy **entity IDs** are preserved | Flashed ESP32 devices keep working without a reflash |

### Why proxies and not direct entities

ESPHome binds entity IDs at compile time, in both directions:

```yaml
binary_sensor:
  - platform: homeassistant
    entity_id: ${light1_entity}          # state in
```

```yaml
- homeassistant.service:
    service: light.toggle                # domain baked into the button
    data: {entity_id: ${light1_entity}}  # target out
```

A proxy with a stable entity ID is the only way an ESP32 in the field can
follow a slot change made in the Home Assistant UI. The cost is decision 1: a
slot cannot change domain. Replacing a lamp with a plug means deleting the slot
and creating a new one, and reflashing the ESP32 if the slot is one of its four.

## Client profiles

A profile is not a bare maximum. The classic ESP32 firmware constrains each slot
individually, because its four LVGL buttons have different compile-time actions:
buttons 1–2 carry `on_long_press_repeat` with `light.turn_on` /
`brightness_pct`, buttons 3–4 only `switch.toggle`.

That is exactly what the paired firmware removes. There the button calls
`cmd_slot_toggle(slot)` and the script reads the domain off the entity it was
given at runtime, so every slot accepts either domain — which is why the two
firmwares need two profiles rather than one widened one. Widening `ESP32_S3`
would offer a switch in slot 1 to devices already in the field, whose button 1
can only call `light.toggle`.

```python
@dataclass(frozen=True, slots=True)
class SlotSpec:
    index: int
    domains: tuple[str, ...]        # what the entity selector offers
    controls: tuple[str, ...]       # what this client can draw at all


@dataclass(frozen=True, slots=True)
class ClientProfile:
    slug: str
    name: str                       # shown in the device-type step
    slots: tuple[SlotSpec, ...]


ESP32_S3 = ClientProfile(
    slug="esp32_s3",
    name="ESP32-S3 controller",
    slots=(
        SlotSpec(1, ("light",),  ("toggle", "brightness")),
        SlotSpec(2, ("light",),  ("toggle", "brightness")),
        SlotSpec(3, ("switch",), ("toggle",)),
        SlotSpec(4, ("switch",), ("toggle",)),
    ),
)

T560 = ClientProfile(
    slug="t560",
    name="T560 panel",
    slots=tuple(
        SlotSpec(n, ("light", "switch"), ("toggle", "brightness", "color_temp"))
        for n in range(1, 7)
    ),
)

# The same board on the paired firmware. Four buttons still, but the entity
# behind each arrives at runtime, so no slot is tied to a domain. No colour
# temperature: there is no control on the screen to set one with.
ESP32_S3_PANEL = ClientProfile(
    slug="esp32_s3_panel",
    name="ESP32-S3 panel",
    slots=tuple(
        SlotSpec(n, ("light", "switch"), ("toggle", "brightness"))
        for n in range(1, 5)
    ),
)
```

The controls a client actually draws for a slot are
`target_capabilities & spec.controls`. A colour-temperature lamp in ESP32 slot 1
is toggled and dimmed there, and gets its full control set on the T560.

`CONTROLLER_PROFILE` is `ESP32_S3` and always has been; `PANEL_PROFILES` is
`(T560, ESP32_S3_PANEL)`. A slug appearing in one does not appear in the other,
which is what keeps `panel_profile("esp32_s3")` from ever resolving: the classic
firmware is not a panel and cannot be added as one.

New profiles live in `custom_components/media_controller/profiles.py`.

## Where slots live

| Client | Slot storage | Reason |
| --- | --- | --- |
| ESP32-S3, classic firmware | The controller config entry (`data` / `options`) | Its four proxies already exist there and it is compile-time bound to them |
| T560, paired ESP32-S3, and later panels | One config entry per device | A panel announces itself over mDNS, and a discovery flow creates an entry — `async_step_zeroconf` exists on `ConfigFlow` and has no subentry equivalent |

The two ESP32 rows are the same hardware in different places, and that is
deliberate: a device that is reflashed from the classic firmware to the paired
one is paired as a new panel and picks its rooms again. Its old controller-level
slots stay where they are until they are removed, so nothing breaks in the
meantime and a reflash back is possible.

A panel entry stores which controller it reads. It never reaches into that
controller's runtime: the three entity IDs it needs are shared through one
`ControllerEntities` object per controller, seeded from the entity registry so
that a panel can load before, or without, its controller.

The controller-level slots are the ESP32's slots for historical reasons, and
the documentation should say so plainly rather than pretending it is a general
concept. The flows say so too: they are behind a named step in the source's
options and are not asked for when a source is created.

In the user interface a controller entry is a **media player source**, and its
device is registered as a service so that Home Assistant lists it apart from
the panels. The code keeps the older name throughout — entry data, the shared
runtime records, and a panel's stored `controller_entry_id` — because renaming
those would be a migration that changes nothing anyone can see.

## Flows

### Source config flow — the player, and only the player

Step `controller` asks one question:

```
Music Assistant player   [entity selector, domain=media_player, integration=music_assistant]
```

The `esp32_s3` slots are not here. They are read by one client — an ESP32 on
the classic firmware — and asking eight more fields of everybody who adds a
source made a source look like a device with buttons on it, which is exactly
the confusion the entry kinds are meant to avoid. A source is created with an
empty slot list, and the slots are filled in from its options.

Step `user` is a menu only when there is something to choose between. With no
source configured, a panel cannot be attached to anything, so the menu is
skipped and `controller` is shown directly.

### Source options flow

A menu, because the two halves have different audiences:

```
Music Assistant player                        → step `player`
Room controls (classic-firmware ESP32 only)   → step `esp32_slots`
```

`esp32_slots` is the four-slot form above. Options are stored whole, so each
step writes both halves — the one it asked about and the one it left alone —
and an empty player is omitted rather than written, so editing slots can never
unbind a source from its player.

The second item is shown to everybody, including the majority who will never
need it, and that is deliberate. It cannot be hidden until a slot exists,
because the classic firmware is flashed with the entity IDs of the proxies
that form creates — there is always zero of them when somebody needs it for
the first time. Nor is it worth hiding behind Advanced Mode: flashing the
classic firmware is a documented path, not an expert one. So the label names
its audience instead.

### Panel discovery flow

The manifest declares `"zeroconf": ["_media-controller._tcp.local."]`. A panel
publishes that service with `panel_id`, `profile`, and `name` TXT records. On
the tablet `t560-announce-panel` does it with `avahi-publish-service`, so no
code in the panel process is involved; on a paired ESP32 it is an `mdns:`
service in the firmware, with the MAC address as `panel_id`.

This is why the service type is not T560-specific and never was: a second kind
of panel needed a new `profile` record and nothing else.

1. **`zeroconf`** — the unique ID is `panel_<panel_id>`, so a panel that is
   already configured only has its address updated.
2. **`pair`** — the code the tablet is showing, followed by `pair_wait`, a
   progress step that ends when the panel answers with the same code. This is
   first on purpose: it is the only part of the setup that depends on a device
   that may not be listening, and everything after it is pure form-filling.
3. **`controller_link`** — which source the panel plays from. The description
   names the device, its profile, and its slot count. With no source
   configured this becomes `new_controller`, which asks for a Music Assistant
   player and builds one, so that pairing the first panel is still one
   sitting.
4. **`slots`** — `len(profile.slots)` pairs of entity selector and label, each
   selector restricted to `spec.domains`. Submitting it creates the entry,
   which is what releases the token.

`Add device` offers the same thing manually, for a panel that cannot announce
itself, with the panel ID typed in. Editing a panel later reruns the source
choice and the slot form through its options flow; the device type is not
offered again, because it decides how many proxies exist.

## Capability normalization

Resolved by the integration when a slot is saved, and again when the target
becomes available after being missing. The result is stored alongside the slot,
so a slot renders correctly even while its target is unavailable.

| Target | `controls` | Extra fields |
| --- | --- | --- |
| `switch.*` | `["toggle"]` | — |
| `light.*`, `supported_color_modes == {onoff}` or unknown | `["toggle"]` | — |
| `light.*` with any other colour mode | `["toggle", "brightness"]` | — |
| `light.*` whose modes include `color_temp` | `["toggle", "brightness", "color_temp"]` | `min_kelvin`, `max_kelvin` from `min_color_temp_kelvin` / `max_color_temp_kelvin` |

Every mode except `onoff` and `unknown` implies brightness in Home Assistant,
so brightness is derived from the set difference, not from an allow-list.

Some Home Assistant light groups expose their effective `brightness` or
`color_temp_kelvin` state attributes without a complete
`supported_color_modes` value. The integration uses those attributes as a
fallback when the slot is configured or the integration is reloaded. It does
not refresh the config sensor on every light state change, so the independent
toggle control is not coupled to capability discovery.

## Entities

### Slot proxies

One proxy per configured slot, in the domain fixed at creation.

| | Value |
| --- | --- |
| Platform | `light` or `switch` |
| `unique_id` | `f"{owner_id}_slot_{n}"`, where `owner_id` is the entry ID — the controller's for ESP32 slots, the panel's for panel slots |
| `translation_key` | `slot_1` … `slot_6` |
| Display name | `Slot N` |

The display name is deliberately not the user's label. Entity IDs are generated
from the name at first registration and must stay stable for the ESP32, so the
label lives only in the config payload, which is what the clients render. Users
may rename proxies freely in the UI; nothing reads that name.

`ControllerLight` stops declaring a fixed `ColorMode.BRIGHTNESS`. It builds
`supported_color_modes` from the stored capability snapshot, mirrors
`color_temp_kelvin` and the Kelvin bounds, and forwards `ATTR_COLOR_TEMP_KELVIN`
on turn-on. This is the contract change that removes the current workaround
where `desk_lamp` and `desk_led_strip` bypass the proxy and address the real
light. Capabilities change only when the slot is saved, so the entry reloads
rather than mutating a live entity's colour modes.

### Config sensor

One per client: `sensor.<controller>_config` for the ESP32 slots, and
`sensor.<panel>_config` for each panel. State is the constant `ok`;
everything is in attributes, like the existing queue and playlist sensors.

```json
{
  "profile": "t560",
  "slot_count": 6,
  "slots": [
    {
      "slot": 1,
      "entity": "light.controller_slot_1",
      "label": "DESK LAMP",
      "controls": ["toggle", "brightness", "color_temp"],
      "min_kelvin": 2000,
      "max_kelvin": 6535
    },
    {
      "slot": 2,
      "entity": "switch.controller_slot_2",
      "label": "FAN",
      "controls": ["toggle"]
    }
  ],
  "revision": 7,
  "settings": {
    "poll_interval_ms": 1000,
    "playlist_poll_interval_ms": 60000,
    "screen_off_seconds": 30
  },
  "commands": {
    "display": {"state": "off", "at": 1756800000000},
    "restart": {"at": 1756800000200},
    "page": {"value": "room", "at": 1756800000300}
  }
}
```

- Empty slots are **omitted**, not sent as nulls. A client renders what it
  receives, in `slot` order.
- `revision` is a checksum of the **layout** — everything above it — and not
  a counter: it changes whenever the layout changes and is stable across
  restarts without extra stored state. A client that sees an unchanged
  revision skips re-layout. `settings` and `commands` are deliberately outside
  it, because they are applied without rebuilding anything.
- `settings` and `commands` appear only on `panel` config sensors. The ESP32
  applies nothing at runtime, so it is sent neither. The camera block stays on
  the tablet: it is read by a daemon that never talks to Home Assistant. See
  [CONTRACT.md](CONTRACT.md) for both blocks and for the endpoint a panel
  reports its battery and display state to.

Real attributes, not an encoded JSON string. The queue sensor's string form is
kept for the queue only; see [CONTRACT.md](CONTRACT.md).

### Recorder

Add `custom_components/media_controller/recorder.py` with
`async_exclude_attributes` covering the config sensor payload, and the existing
`queue` and `playlists` attributes while we are there. They currently write a
large JSON blob to the database on every queue change.

## Panel identity

A panel is identified by a **per-device ID**, not by its hostname. Two tablets
flashed from the same image share a hostname, and would then claim the same
Home Assistant device and overwrite each other's configuration.

The ID is `t560_<first 8 hex of sha256(hardware address)>`, written once to
`~/.config/t560-music-panel/panel-id`. An underscore, not a dash: the ID ends
up inside an entity ID.

| Event | Identity | What the user does |
| --- | --- | --- |
| Application update or reinstall | unchanged — the file is in the preserved config directory | nothing |
| Tablet wiped | unchanged — derived from the same hardware address again | approve one re-pairing |
| A second tablet | different — a different hardware address | add it as its own device |

`t560-announce-panel` publishes that same file's value and never derives one
of its own, so the announcement and the application can never disagree.

The panel does not guess its config sensor either. Home Assistant derives that
entity ID from the device name, so two panels named alike get `_config` and
`_config_2`; the entity ID is therefore handed to the panel during pairing and
cached. Guessing it was the second way two tablets could have read each
other's layout.

## Pairing

A panel has no keyboard, so its token cannot be typed on it, and Home
Assistant cannot push anything to a tablet that serves nothing. The panel asks
instead.

1. A panel with no token shows a six-digit code, generated once and cached so
   that a watchdog restart does not change the number being read out.
2. It polls `POST /api/media_controller/provision` every three seconds with
   its panel ID and that code.
3. Home Assistant answers only for an **approved** pairing. Approval happens
   in the flow that adds the panel — as its **first** step, before the
   controller and the slots — or, for a panel that already exists, through the
   standard reauthentication prompt, which the endpoint raises the first time
   an unapproved panel asks.
4. The first poll carrying the right code **confirms** the pairing. That is
   what the setup form waits for: it asks nothing else until the right device
   has answered, so nobody maps six room controls for a tablet that turns out
   to be off. Five wrong codes cancel the approval and the form says so.
5. A confirmed pairing does not yet hand anything over. The token is minted
   when the form is finished, and travels on the first poll after the panel's
   config entry and its config sensor exist. Until then the answer is
   `202 pairing_pending` and the panel keeps asking; each correct poll extends
   the window, so a slow setup cannot expire underneath it.
6. On success the panel receives the token and its config sensor's entity ID,
   stores the token with mode `0600`, and restarts into normal operation.

Holding the token back until the entry exists is also what makes the config
sensor's entity ID always correct: it is read from the entity registry at the
moment it is handed over, never guessed. And the token is not merely withheld
until then, it is not minted until then: a setup closed halfway through leaves
an approval that expires and nothing else.

The token belongs to a dedicated non-administrator user, `Media Controller
<name>`, so it can be revoked on its own. Re-pairing mints a new token and
revokes the old one, but only after the new one exists, so a failure cannot
leave a panel with neither. Removing the panel revokes the token and deletes
the user once it owns nothing else.

### Why an unauthenticated endpoint is acceptable

It has to be: a panel asking for its first token has no credentials to
present. What guards it, in `pairing.py` and covered by `tests/test_pairing.py`:

- it answers only while an approval is open for **that** panel ID;
- only for a code shown on the device's own screen;
- for at most five minutes after the last correct poll;
- exactly once — a replay gets nothing;
- and five wrong codes cancel the approval.

An approval is per panel ID, so one tablet's approval can never hand a token
to another.

### What this does not protect against

A device on the same network that can both see the panel's screen and reach
Home Assistant could claim the token while that window is open. That is the
same trust boundary as reading the code aloud in the room, and it is the
reason the window is short and single-use rather than open.

## Client changes

### T560

- `app_config.h` — `PANEL_ROOM_COUNT` became `PANEL_ROOM_MAX`, a bound rather
  than a count. A `PanelLayout` holds the three controller entities and up to
  six `PanelRoom` records carrying entity, label, controls, and Kelvin bounds.
- `app_config.c` — `config.ini` keeps `url`, `panel_id`, and the tablet-local
  settings. The `[entities]`, `[labels]`, and `[room_features]` sections are
  gone.
- `panel_config.c` — parses `sensor.<panel_id>_config` and caches the accepted
  payload in `~/.cache/t560-music-panel/layout.json`. Only a payload the panel
  accepted is cached, so an unusable one never becomes the layout of the next
  boot.
- `application.c` — the config sensor is polled first in every cycle, at the
  playlist interval; nothing else is requested until the layout arrives. A
  changed `revision` quits the process, exactly as a `config.ini` change
  already did, and the watchdog restarts it against the fresh cache within
  about two seconds.
- `panel_ui.c` — the tile grid is built from `layout.room_count` instead of six
  static widgets. A tile offers the ADJUST sheet only when its slot reports
  `brightness` or `color_temp`, and the sheet shows only those controls. The
  icon follows the slot number, so a tile keeps its icon when the entity behind
  it changes; the kicker text follows the proxy domain.

Start-up has two paths. With a cached layout the window is built immediately,
which is also what makes the panel usable while Home Assistant is down. Without
one — a tablet that has never reached Home Assistant — a placeholder is shown
until the first successful read.

### Still on the tablet

`[panel]` and `[camera]` stay in `config.ini`. `t560-power-button.py` and
`t560-motion-detector.py` read them directly, and giving each daemon its own
Home Assistant client and token would be worse than leaving three timing
values local. Moving them means adding per-panel settings entities to the
integration and having the panel materialize a derived ini for the daemons to
read on `SIGHUP`; the panel would stay the only HTTP client on the tablet.
That work is not done.

### ESP32

Done: the four button labels and the visibility of each button are read from
`config_entity` on every API connection, with the `http_request` pattern the
firmware already used for playlists. The four `text:` labels gained an `id:`,
a `slot_label_parser` global walks the `slots` array by brace depth — the
firmware has no JSON library — and `ui_load_room_config` applies the result
behind the existing `ui_ready` guard. An empty slot hides its button; a missing
config sensor leaves the compile-time labels in place.

What cannot change without a reflash, and must be documented as a limit rather
than promised away:

- the entity ID each button reads and writes, because `platform: homeassistant`
  and `homeassistant.service` resolve `${light1_entity}` at compile time;
- the service domain per button (`light.toggle` vs `switch.toggle`);
- the number of buttons and their absolute LVGL geometry;
- per-button icons, which are compile-time image assets.

**The substitution names `light1_entity`, `light2_entity`, `fan_entity`, and
`ac_entity` must not be renamed.** The package is pulled by `ref` with
`refresh: 1h`, so renaming a substitution breaks the next compile of every user
who copied `media-controller.example.yaml`. Their meaning changes — they now
point at slot proxies — but their spelling does not.

## Migration

Config entry `VERSION` 1 → 2. `async_migrate_entry` rewrites `data` and
`options` into the slot list, and renumbers the four proxies in the entity
registry:

| Old key | New slot | `unique_id` before | `unique_id` after | Entity ID |
| --- | --- | --- | --- | --- |
| `light_1_entity` | 1 | `{entry_id}_light_1_entity` | `{entry_id}_slot_1` | unchanged |
| `light_2_entity` | 2 | `{entry_id}_light_2_entity` | `{entry_id}_slot_2` | unchanged |
| `fan_entity` | 3 | `{entry_id}_fan_entity` | `{entry_id}_slot_3` | unchanged |
| `ac_entity` | 4 | `{entry_id}_ac_entity` | `{entry_id}_slot_4` | unchanged |

The `unique_id` is rewritten rather than kept, so that one scheme covers every
slot and no entity code carries a legacy branch. What the ESP32 actually reads
is the **entity ID**, and changing a `unique_id` does not change it: the
registry keeps the same row, so `light.<controller>_light_1` and the rest
survive and no device needs a reflash. Only the display names become `Slot N`.

New installations get `light.<controller>_slot_1`. The two spellings coexist
permanently and no code may assume either.

A slot number never shifts. A version 1 entry that configured only `ac_entity`
migrates to slot 4, not slot 1, because the ESP32 button that read that proxy
must keep reading it.

Labels are empty after migration, so tiles fall back to `friendly_name` until
the user sets them.

A panel created while panels were still config subentries has to be removed
and added again: an entry and a subentry are different records. Its entities
are cleaned up on the first load, and nothing else in Home Assistant is
affected.

## Contract version 2

Changes to record in [CONTRACT.md](CONTRACT.md) before any code lands:

1. Proxy lights forward colour temperature and mirror the target's colour
   modes. The note telling clients to bypass the proxy for colour temperature
   is removed.
2. New `sensor.<client>_config` entity and its payload shape.
3. Slot proxies replace the four named proxies; both entity ID spellings are
   valid.
4. Clients must cache the last known configuration and start from the cache.
5. Clients still request single entities. `/api/states` in full stays
   forbidden.

## Tests

- `tests/test_transformations.py` — config payload construction, empty slots
  omitted, the revision changing with the configuration.
- `tests/test_profiles.py` — the capability normalization table above,
  including `onoff`-only lights and missing targets.
- `tests/test_migration.py` — v1 → v2 keeps every slot number and drops the
  legacy keys.
- `tests/test_pairing.py` — what guards the unauthenticated endpoint: single
  use, expiry, attempt limit, and that one panel's approval never serves
  another.
- `clients/t560/tests/test_panel_config.c` — parsing the config payload,
  including an unknown control name, which must be ignored rather than fatal.

None of these need a Home Assistant runtime: every rule they cover lives in a
module with no Home Assistant imports, which is why `transformations.py`,
`profiles.py`, and `pairing.py` are separate from the entities and the view
that use them.

## Order of work

1. **Integration.** Done in `0.8.2`: profiles, migration, slot proxies with
   capability forwarding, config sensor, recorder exclusion, `strings.json`.
   The ESP32 keeps working unchanged, because its entity IDs are preserved.
2. **T560.** Done: config sensor, dynamic tiles, offline cache, mDNS
   announcement, per-device identity, and pairing. `config.ini` became
   optional; only the token file remains, and the panel writes that itself.
3. **ESP32 firmware.** Done: labels and tile visibility from the config
   sensor, and the `config_entity` substitution that names it. Contract
   version 2 is now recorded, with every consumer updated.

The ESP32 is not part of the pairing work: ESPHome holds its own token in
`secrets.yaml`, which is edited where the device YAML is edited, not on the
device.
