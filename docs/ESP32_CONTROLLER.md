# ESP32-S3 controller

An ESPHome touchscreen controller for Home Assistant and Music Assistant, built
for the ESP32-S3 480x480 ST7701S + GT911 board commonly sold as
`ESP32-S3-4848S040`.

The firmware is packaged as a reusable ESPHome package: the device YAML you
paste into ESPHome Device Builder stays small, and `packages:` downloads
[firmware/media-controller.yaml](../firmware/media-controller.yaml) and the
image assets from this repository during validation and compilation.

> **There are two firmwares for this board.** This one is configured by
> flashing: you copy nine entity IDs and a long-lived token into the YAML, and
> changing which lamp a button drives means flashing again. The other,
> [ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md), is paired from Home
> Assistant with a six-digit code and needs no entity IDs and no token at all.
> They share every pixel of their interface — see the
> [comparison](ESP32_PAIRED_CONTROLLER.md#which-firmware-to-use) — and both work
> against one Home Assistant at the same time. Nothing here changed; a device
> already in the field needs no attention.

Since the two firmwares differ only in how they reach Home Assistant, everything
they draw lives in a third file,
[firmware/media-controller-ui.yaml](../firmware/media-controller-ui.yaml), which
both include. Its header lists the handful of script and entity names the two
halves agree on; a widget that needs to act on Home Assistant calls a `cmd_`
script rather than naming a transport itself.

It consumes the entities and services described in
[CONTRACT.md](CONTRACT.md), which the Home Assistant integration provides.
Install that first: see [INTEGRATION.md](INTEGRATION.md).

For the build story, photos, and setup walkthrough, see the write-up:
[Music Assistant ESP32 Media Controller](https://vahac.com/blogs/music-assistant-esp32-media-controller/?utm_source=github).

## Current validation status

The custom integration transformation tests and static repository checks pass.
The packaged firmware also passes `esphome config` and a complete ESPHome
2026.8.0 compile. The firmware was successfully verified on the physical
ESP32-S3 + ST7701S + GT911 target, including the Git package installation flow.
Use the [hardware checklist](#hardware-verification) when installing it on
another board revision.

**The interface was moved into a shared package after that hardware run, and the
firmware has not been re-flashed since.** The move is verified rather than
assumed: `esphome config` prints the fully merged and substituted configuration,
and its output before and after the split is identical line for line, only
reordered. The one deliberate behaviour change is that the widget actions now go
through `cmd_` scripts, and the two copies of the playlist parser became one, so
two log lines that used to differ now read the same. Re-flash a device once to
confirm, then treat step 1 of the
[paired firmware's checklist](ESP32_PAIRED_CONTROLLER.md#hardware-verification)
as done.

**One real bug turned up on the way.** `ui_load_room_config` addressed the room
buttons and their labels as `id(btn_light1)->obj`. ESPHome generates those
widgets as plain `lv_obj_t *`, which has no `obj` member and is an incomplete
type in that header, so the lambda could not compile against ESPHome 2026.8.0 —
the whole firmware failed to build, not merely the room page. The `->obj` form
is correct for a roller and is still used for `playlist_roller`, which ESPHome
generates as a wrapper; it was wrong for everything else. Fixed in the shared
package, so both firmwares get it. Whatever compile the status above refers to,
it was against an older ESPHome.

With that fix in place both firmwares build again on ESPHome 2026.8.0: this one
at 37.4% RAM and 21.9% flash, the paired one at 38.0% and 21.9%. The split cost
essentially nothing in either.

The `Minimal Ring` and `Cover Card` screen styles, the UI synchronisation
refactor behind them, and the swipe debounce are validated by `esphome config`
and a full compile. `Minimal Ring` has run on the physical device; `Cover Card`
has not. Album art rendering, the volume slider, the track time readout, and the
runtime cost of a third LVGL page still need hardware confirmation. See steps
11–16 of the [hardware checklist](#hardware-verification).

## Supported hardware

- ESP32-S3 (`esp32-s3-devkitc-1`)
- ESP-IDF framework
- 16 MB flash
- Octal PSRAM at 80 MHz
- ST7701S RGB display, 480×480
- GT911 capacitive touchscreen

The working ST7701S initialization, RGB/SPI/I²C pins, sync timings, 12 MHz
pixel clock, and PSRAM configuration are hardware-critical.

## Prerequisites

1. The Media Controller integration installed and configured
   ([INTEGRATION.md](INTEGRATION.md)).
2. ESPHome for validation, compilation, and flashing.
3. A dedicated Home Assistant long-lived access token for the v1 REST
   transport. See [REST token limitation](#rest-token-limitation).

## Configure and flash ESPHome

The ESPHome device YAML is intentionally small. Paste the complete block below
into the device configuration in ESPHome Device Builder. Do not copy the
2,000+ line `firmware/media-controller.yaml` file into Home Assistant: the
`packages:` section downloads that maintained file and all required image
assets from this repository during validation and compilation.

```yaml
substitutions:
  # Keep the existing ESPHome device name when updating an already adopted
  # device; changing it creates a different device identity in Home Assistant.
  device_name: media-controller
  friendly_name: Media Controller

  # Use the same Music Assistant player selected in the integration Config Flow.
  player_entity: media_player.your_music_assistant_player

  # Copy the actual entity IDs created by the Media Controller integration.
  queue_entity: sensor.your_controller_queue
  playlists_entity: sensor.your_controller_playlists

  # Room-control slots 1 to 4 of the controller entry. An installation created
  # before integration 0.8.2 keeps the older light.<controller>_light_1
  # spelling; a newer one uses _slot_1. Copy whichever Home Assistant shows.
  light1_entity: light.your_controller_slot_1
  light2_entity: light.your_controller_slot_2
  fan_entity: switch.your_controller_slot_3
  ac_entity: switch.your_controller_slot_4

  # Button labels and tile visibility are read from here at runtime.
  config_entity: sensor.your_controller_config

  ha_url: "http://homeassistant.local:8123"
  ha_token: !secret media_controller_ha_token

packages:
  media_controller:
    url: https://github.com/VahaC/ha-media-controller
    ref: main
    files:
      - firmware/media-controller.yaml
    refresh: 1d

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
  encryption:
    key: !secret media_controller_api_encryption_key

ota:
  - platform: esphome
    password: !secret media_controller_ota_password
```

Before installing:

1. Replace `device_name`, `player_entity`, and every queue, playlist, slot, and
   config entity placeholder with the actual values from Home Assistant.
2. Keep using the existing global ESPHome `secrets.yaml`; do not create a
   repository-specific secrets file.
3. Ensure the `!secret` names in the block match keys that already exist in
   that global file. Rename the references in the device YAML if your keys have
   different names.
4. In ESPHome Device Builder, select **Validate**, then **Install**. Use USB for
   the first flash and OTA for later updates.

For command-line validation and compilation:

```text
esphome config media-controller.yaml
esphome compile media-controller.yaml
```

Remote ESPHome packages cannot contain secret lookups. This is why Wi-Fi, API
encryption, OTA, and the Home Assistant token are in the small user
configuration rather than the maintained package.

## Room slots

The four buttons on the switches page are slots 1 to 4 of the controller
entry. Which entity a slot points at is changed in Home Assistant, in the
integration options; the device follows without a reflash, because it is bound
to the slot proxy rather than to the entity behind it.

Read from `config_entity` on every API connection:

- the label on each button;
- whether the button is shown at all — an empty slot has no tile.

Fixed at compile time, and therefore a reflash:

- the entity ID each button reads and writes, because `platform: homeassistant`
  and `homeassistant.service` resolve the substitution while compiling;
- the **domain** of each slot: buttons 1 and 2 call `light.*` and carry the
  long-press brightness action, buttons 3 and 4 call `switch.*`. The
  integration enforces the same split, so a slot cannot be given the wrong
  kind of entity in the first place;
- the number of buttons and their positions;
- the per-button icons, which are compile-time image assets.

A colour-temperature lamp in slot 1 is therefore switched and dimmed here, and
offers its full control set on a client that can draw it, such as the T560
panel. `config_entity` is optional: without it the buttons keep their
compile-time labels and all four stay visible, and the log carries one warning
per reconnect.

## Screen styles

The home screen ships in three layouts. The device exposes a **Screen Style**
select entity, so switching between them is a Home Assistant UI action or an
automation — no recompile and no reflash. The choice is stored on the device and
survives reboots.

| Option | Layout |
| --- | --- |
| `Classic` | Full-bleed album art, 240° progress arc, decoration card with title/artist/volume, transport row, shuffle/repeat, Queue and Playlists buttons. |
| `Minimal Ring` | Album art as a centred disc inside a 270° progress ring with a glowing position dot, a bare prev / play-pause / next row, small title and artist, corner volume buttons, and a `...` button that opens an overlay with shuffle, repeat, Queue and Playlists. |
| `Cover Card` | Rounded cover card with a drop shadow, large title and artist, elapsed and total time either side of a linear progress bar, a full transport row with shuffle and repeat inline, a volume slider flanked by step buttons, and Queue/Playlists in the top corners. Nothing hidden behind an overlay. |

`Cover Card` is the only layout that shows track times. Its volume row works two
ways: drag the slider for a large jump, or tap the speaker glyph on either side
to step the volume the same way the other layouts do. It shares its pre-sized
album art source with `Minimal Ring`, so adding it cost no extra image buffer and
no extra download.

Both layouts are live at all times: player state is written to every layout, so
switching is instant and the newly shown one is already up to date. Swiping left
or right from either one still opens Room Controls, and Room Controls returns to
whichever layout is currently selected.

### Appearance entities

These template entities are also stored on the device and applied at boot:

- `Progress Ring Color`, `Progress Ring Fill Color`, `Progress Ring Opacity`
- `Title Color`, `Artist Color`, `Volume Color`
- `Decoration Color`, `Decoration Opacity` (Classic only)
- `Buttons Color`, `Buttons Opacity`
- `Flat Controls Color` — transport glyphs on `Minimal Ring` and `Cover Card`.
  It is separate from `Buttons Color` because both layouts deliberately reserve
  the accent for the progress indicator and the play button, and render
  everything else in neutral grey. Set it to the same value as `Buttons Color`
  if you prefer them to match.
- `Album Art Opacity`
- `Screen Timeout`

Colours are plain six-digit hex without a leading `#`, for example `00cfff`.

### Adding another layout

Layouts are ordinary LVGL pages. To add one:

1. Add a page next to `page_player_cover` in `firmware/media-controller.yaml`.
2. Add its option to the `screen_style` select.
3. Add a branch to `show_home_page`, `show_home_page_move_left`, and
   `show_home_page_move_right`, and to the page check in `apply_screen_style`.
4. Extend the `ui_sync_*` and `apply_theme` scripts with the new widget IDs.
5. If it needs album art at a new size, add an `online_image` with the matching
   `resize:` and route it in `ui_load_album_art`.

Navigation never names a home page directly — it always goes through the
`show_home_page*` scripts — and no sensor writes to a widget directly, so those
steps are the whole integration surface.

### Album art sizing

Every layout decodes album art at the size it draws it:

| Source | Size | Used by |
| --- | --- | --- |
| `album_art` | 480×480 | `Classic`, full screen |
| `album_art_small` | 244×244 | `Minimal Ring` disc, `Cover Card` cover |

Only the source the active layout needs is downloaded. `resize:` preserves the
aspect ratio, so non-square art is letterboxed rather than stretched.

### Album art must never be scaled at draw time

This build sets `LV_COLOR_16_SWAP` and leaves `LV_DRAW_SW_SUPPORT_SWAPPED` off,
so LVGL's software renderer cannot transform a swapped RGB565 image. Asking it
to (via `lv_image_set_scale`, `zoom:`, or `scale:`) produces striped garbage
instead of the cover, and the per-frame cost of transforming a full-resolution
download is high enough to stall the main loop.

Give each layout an `online_image` whose `resize:` already matches the widget,
and share one source between layouts that need the same size. `resize:`
preserves aspect ratio, so non-square art is letterboxed rather than stretched.

## REST token limitation

This firmware uses the Home Assistant REST transport for queue, playlist, and
album-art requests, and the token for it is compiled in. The ESP32 sends that
bearer token only to the configured local `ha_url`.

Use a dedicated token, store it only in `secrets.yaml`, do not commit it, and
keep the ESPHome device and Home Assistant on a trusted local network.

The token is gone in
[the paired firmware](ESP32_PAIRED_CONTROLLER.md), which is handed a revocable
one by Home Assistant during pairing and stores it in flash rather than in a
build. That is the fix; this firmware keeps its compile-time token so that
devices already in the field are not disturbed.

## Hardware verification

On the physical ESP32-S3 + ST7701S + GT911 device, verify all of the following:

1. Cold boot initializes the 480×480 display without artifacts.
2. GT911 tap, hold, and swipe work while the screen is awake.
3. Let the idle/paused screen turn off. The first touch or gesture must only
   turn on the backlight. It must not click, toggle, long-press, swipe, navigate,
   play media, or select a queue item. LVGL must resume only after release.
4. Title, artist, progress, volume, previous, play/pause, next, shuffle, and
   repeat still work.
5. Album art loads initially and reloads after Home Assistant reconnects.
6. Playlists load, Unicode names render correctly, and the selected playlist
   starts through Music Assistant.
7. Queue remains bounded, highlights the correct current entry, safely handles
   an empty queue, and single/double selection behavior remains intact.
8. Queue item playback jumps within the existing queue.
9. Optional Light 1/Light 2/Fan/AC proxies reflect state and forward actions;
   unconfigured mappings affect only their own controls.
10. Long queues and repeated page navigation do not cause watchdog or memory
    resets; inspect the included heap/PSRAM diagnostics.
11. Note `Media Controller Heap Free` and `Media Controller Heap Min Free`.
    Each extra LVGL page costs roughly 10–15 KB of internal heap; album art
    buffers are shared between layouts of the same size and do not multiply.

    `Media Controller Loop Time` is the **longest single loop iteration** in the
    last update interval, not an average, so one expensive frame — a page load
    animation, an album art decode, a queue response — sets it. Occasional peaks
    of tens of milliseconds are normal and are not evidence of a stall.

    `Reset Reason` is carried over from the previous boot and stays there until
    the next one, so it can look alarming long after a one-off reset. Watch
    `Media Controller Uptime` instead: if it keeps climbing, the device is not
    rebooting whatever the reset reason says.
12. Switch `Screen Style` through all three options from Home Assistant. The
    layout must change immediately, already showing the current track, artist,
    progress, and album art, with no reboot.
13. On `Minimal Ring`: album art is clipped to a clean circle for both square
    and non-square source images, the position dot tracks the ring across a
    whole track, `...` opens and closes the overlay, and shuffle/repeat state in
    the overlay matches Music Assistant.
14. On `Cover Card`: the cover renders cleanly, elapsed and total time count
    correctly and read `--:--` for live streams, the volume slider follows Home
    Assistant but does not jump while being dragged, releasing it sets the volume
    once rather than on every step, and the speaker glyphs either side of it step
    the volume and move the knob to match.
15. A single swipe changes the page exactly once, in both directions and from
    every layout. Repeat with playback running.
16. Change `Screen Style` while the queue, playlists, or room controls page is
    open. The device must stay on that page and only apply the new layout when
    it next returns home.

## Development

When iterating on the firmware, point the device YAML at a working branch
instead of `main`. Note that `asset_base_url` defaults to the `main` branch, so
override it as well whenever the branch changes image assets:

```yaml
substitutions:
  asset_base_url: "https://raw.githubusercontent.com/VahaC/ha-media-controller/dev/firmware/assets"

packages:
  media_controller:
    url: https://github.com/VahaC/ha-media-controller
    ref: dev
    files:
      - firmware/media-controller.yaml
    refresh: 0s
```

For layout work, a commit per iteration is unnecessary. Include the maintained
file from a local checkout and keep the assets local too:

```yaml
substitutions:
  asset_base_url: assets

packages:
  media_controller: !include ../ha-media-controller/firmware/media-controller.yaml
```

Users should pin a release tag rather than a branch, so that work in progress on
`main` never reaches them mid-change.

