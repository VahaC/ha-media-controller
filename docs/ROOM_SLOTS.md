# Room slots

Specification for moving room-control configuration out of client files and
into Home Assistant. It implements [ROADMAP.md](ROADMAP.md) item 1 and replaces
the four fixed room slots of integration `0.7.x`.

Status: **implemented** in integration `0.8.1` and firmware `0.8.0`. What is left
out of scope here is moving the tablet-local settings — `[panel]` and
`[camera]` — into Home Assistant; see [Still on the tablet](#still-on-the-tablet).
Contract version: **2**.

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
| 3 | ESP32 gets **no subentry** | Its four slots stay on the controller config entry, where they already are |
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

A profile is not a bare maximum. The ESP32 constrains each slot individually,
because its four LVGL buttons have different compile-time actions: buttons 1–2
carry `on_long_press_repeat` with `light.turn_on` / `brightness_pct`, buttons
3–4 only `switch.toggle`.

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
```

The controls a client actually draws for a slot are
`target_capabilities & spec.controls`. A colour-temperature lamp in ESP32 slot 1
is toggled and dimmed there, and gets its full control set on the T560.

New profiles live in `custom_components/media_controller/profiles.py`.

## Where slots live

| Client | Slot storage | Reason |
| --- | --- | --- |
| ESP32-S3 | The controller config entry (`data` / `options`) | Its four proxies already exist there and it is compile-time bound to them |
| T560 and later panels | One config subentry of type `panel` per device | Home Assistant renders subentries as an add/edit/delete list, which is the repeatable item the Options Flow cannot express |

The controller-level slots are the ESP32's slots for historical reasons, and
the documentation should say so plainly rather than pretending it is a general
concept.

## Flows

### Controller config flow — unchanged shape, new content

Step `user` keeps the Music Assistant player selector and replaces the four
named fields with the `esp32_s3` profile slots:

```
Music Assistant player   [entity selector, domain=media_player, integration=music_assistant]

Slot 1                   [entity selector, domain=light]
Slot 1 label             [text, optional]
Slot 2                   [entity selector, domain=light]
Slot 2 label             [text, optional]
Slot 3                   [entity selector, domain=switch]
Slot 3 label             [text, optional]
Slot 4                   [entity selector, domain=switch]
Slot 4 label             [text, optional]
```

The description line states the limit: *"The ESP32-S3 controller drives up to
4 room controls."*

### Panel subentry flow — two steps

`async_get_supported_subentry_types` returns `{"panel": PanelSubentryFlow}`.

1. **`user`** — device type from the profile registry, plus a name. The
   description of the chosen type carries the limit, so the user reads
   *"The T560 panel drives up to 6 room controls"* before the slot form.
2. **`slots`** — `len(profile.slots)` pairs of entity selector and label,
   each selector restricted to `spec.domains`.

Editing a panel reruns step `slots` with current values.

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

## Entities

### Slot proxies

One proxy per configured slot, in the domain fixed at creation.

| | Value |
| --- | --- |
| Platform | `light` or `switch` |
| `unique_id` | `f"{owner_id}_slot_{n}"` where `owner_id` is the entry ID for ESP32 slots and the subentry ID for panel slots |
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
`sensor.<panel>_config` for each panel subentry. State is the constant `ok`;
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
  "poll_interval_ms": 1000,
  "playlist_poll_interval_ms": 60000,
  "screen_off_seconds": 30,
  "revision": 7
}
```

- Empty slots are **omitted**, not sent as nulls. A client renders what it
  receives, in `slot` order.
- `revision` is a checksum of the rest of the payload, not a counter: it
  changes whenever the configuration changes and is stable across restarts
  without extra stored state. A client that sees an unchanged revision skips
  re-layout.
- The panel-local settings (`poll_interval_ms`, `screen_off_seconds`, the
  camera block) appear only on `panel` config sensors, and only once the
  corresponding settings entities exist — see
  [ROADMAP.md](ROADMAP.md) item 1, phase 2.

Real attributes, not an encoded JSON string. The queue sensor's string form is
kept for the queue only; see [CONTRACT.md](CONTRACT.md).

### Recorder

Add `custom_components/media_controller/recorder.py` with
`async_exclude_attributes` covering the config sensor payload, and the existing
`queue` and `playlists` attributes while we are there. They currently write a
large JSON blob to the database on every queue change.

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

The T560 keeps working on its `config.ini` until its subentry is created. The
first release must not delete the local sections; a later release removes them
once the panel has been observed reading the config sensor.

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
  omitted, revision increments.
- New `tests/test_profiles.py` — capability normalization table above, including
  `onoff`-only lights and missing targets.
- New `tests/test_migration.py` — v1 → v2 keeps every slot number and drops
  the legacy keys.
- `clients/t560/tests/test_json_helpers.c` — parsing the config payload,
  including an unknown control name, which must be ignored rather than fatal.

## Order of work

1. **Integration.** Done in `0.8.1`: profiles, migration, slot proxies with
   capability forwarding, config sensor, recorder exclusion, `strings.json`.
   The ESP32 keeps working unchanged, because its entity IDs are preserved.
2. **T560.** Done: panel subentry, config sensor, dynamic tiles, offline
   cache. `config.ini` shrank to `url`, `panel_id`, and the tablet-local
   `[panel]` and `[camera]` sections, beside the token file.
3. **ESP32 firmware.** Done: labels and tile visibility from the config
   sensor, and the `config_entity` substitution that names it. Contract
   version 2 is now recorded, with every consumer updated.
