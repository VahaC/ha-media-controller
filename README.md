# VahaC ESP32 Music Assistant Media Controller

An ESPHome touchscreen controller for Home Assistant and Music Assistant,
built for the ESP32-S3 480×480 ST7701S + GT911 board commonly sold as
`ESP32-S3-4848S040`.

The project packages the existing working controller as:

- a HACS-compatible Home Assistant custom integration;
- a reusable ESPHome package with all build assets in this repository.

The LVGL interface, display timings, touch pins, media controls, album art,
queue windowing, playlists, room controls, sleep timer, and consumed wake touch
are intentionally preserved.

## Current validation status

The custom integration transformation tests and static repository checks pass.
The packaged firmware also passes `esphome config` and a complete ESPHome
2026.8.0 compile. The firmware was successfully verified on the physical
ESP32-S3 + ST7701S + GT911 target, including the Git package installation flow.
Use the [hardware checklist](#hardware-verification) when installing it on
another board revision.

The `Minimal Ring` screen style and the UI synchronisation refactor behind it
are validated by `esphome config` and a full compile only. They have not yet run
on the physical device: the circular album-art clipping, the runtime image
scaling, the ring position dot, and the runtime memory cost of a second LVGL
page all need hardware confirmation. See steps 11–14 of the
[hardware checklist](#hardware-verification).

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

1. A current Home Assistant installation.
2. The official Music Assistant integration with at least one exposed
   `media_player` entity.
3. HACS for custom-integration installation.
4. ESPHome for validation, compilation, and flashing.
5. A dedicated Home Assistant long-lived access token for the v1 REST
   transport. See [REST token limitation](#rest-token-limitation).

## Install the Home Assistant integration

Until this repository is included in the default HACS catalog:

1. Open HACS → Integrations → Custom repositories.
2. Add
   `https://github.com/VahaC/music-assistant-esp32s34848s040-controller`
   as an **Integration** repository.
3. Install **Media Controller** and restart Home Assistant.
4. Open Settings → Devices & services → Add integration.
5. Select **Media Controller**.
6. Select the required Music Assistant player.
7. Optionally map Light 1, Light 2, Fan, and AC.

The integration creates:

- a bounded queue sensor;
- a playlists sensor;
- Light 1 and Light 2 proxy light entities;
- Fan and AC proxy switch entities.

The proxy entities make room mappings changeable through Options Flow without
reflashing the ESP32. A proxy whose source is not configured or unavailable is
itself unavailable; the other controller functions continue working.

Entity IDs are assigned by Home Assistant's entity registry. Open the new
controller device and copy its actual entity IDs for the firmware substitutions.
Do not assume the example IDs are the IDs Home Assistant chose.

The integration listens to the Music Assistant player selected in Config Flow.
The ESPHome device also uses its `player_entity` substitution for native media
state and control actions. If the selected player is changed later in Options
Flow, update that substitution during the next ESPHome/OTA update as well.

### Synchronization behavior

- Playlists refresh during integration setup and every six hours.
- Queue data refreshes after a Music Assistant title change with a cancellable
  three-second debounce.
- Only 50 queue entries are requested, starting up to five entries before the
  current item.
- Rapid changes cancel obsolete delays and queue calls cannot overlap.
- `media_controller.refresh` refreshes queue and playlists on demand.
- `media_controller.play_queue_item` starts the selected queue item by
  its Music Assistant queue item ID without replacing the queue.

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
  light1_entity: light.your_controller_light_1
  light2_entity: light.your_controller_light_2
  fan_entity: switch.your_controller_fan
  ac_entity: switch.your_controller_ac

  ha_url: "http://homeassistant.local:8123"
  ha_token: !secret media_controller_ha_token

packages:
  media_controller:
    url: https://github.com/VahaC/music-assistant-esp32s34848s040-controller
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

1. Replace `device_name`, `player_entity`, and every queue/playlist/room entity
   placeholder with the actual values from Home Assistant.
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

## Screen styles

The home screen ships in two layouts. The device exposes a **Screen Style**
select entity, so switching between them is a Home Assistant UI action or an
automation — no recompile and no reflash. The choice is stored on the device and
survives reboots.

| Option | Layout |
| --- | --- |
| `Classic` | Full-bleed album art, 240° progress arc, decoration card with title/artist/volume, transport row, shuffle/repeat, Queue and Playlists buttons. |
| `Minimal Ring` | Album art as a centred disc inside a 270° progress ring with a glowing position dot, a bare prev / play-pause / next row, small title and artist, corner volume buttons, and a `...` button that opens an overlay with shuffle, repeat, Queue and Playlists. |

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
- `Minimal Controls Color` — Minimal Ring transport glyphs only. It is separate
  from `Buttons Color` because that layout deliberately keeps the accent colour
  on the progress ring and renders the controls in neutral grey. Set it to the
  same value as `Buttons Color` if you prefer them to match.
- `Album Art Opacity`
- `Screen Timeout`

Colours are plain six-digit hex without a leading `#`, for example `00cfff`.

### Adding another layout

Layouts are ordinary LVGL pages. To add a third one:

1. Add a page next to `page_player_minimal` in `firmware/media-controller.yaml`.
2. Add its option to the `screen_style` select.
3. Add a branch to `show_home_page`, `show_home_page_move_left`, and
   `show_home_page_move_right`, and to the page check in `apply_screen_style`.
4. Extend the `ui_sync_*` and `apply_theme` scripts with the new widget IDs.

Navigation never names a home page directly — it always goes through the
`show_home_page*` scripts — and no sensor writes to a widget directly, so those
four steps are the whole integration surface.

## REST token limitation

The firmware currently uses the Home Assistant REST transport for queue,
playlist, and album-art requests. The ESP32 sends a bearer token only to the
configured local `ha_url`.

Use a dedicated token, store it only in `secrets.yaml`, do not commit it, and
keep the ESPHome device and Home Assistant on a trusted local network. Removing
the token is a later security milestone that requires payload-size, ESP32
memory, reconnect, and album-art testing, so it remains a separate follow-up.

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
11. Note `Media Controller Heap Free` and `Media Controller Heap Min Free`
    before and after this firmware version. A second LVGL page costs roughly
    10–15 KB of internal heap; the album-art buffer is shared and does not
    double. Investigate anything larger than that.
12. Switch `Screen Style` between `Classic` and `Minimal Ring` from Home
    Assistant. The layout must change immediately, already showing the current
    track, artist, progress, and album art, with no reboot.
13. On `Minimal Ring`: album art is clipped to a clean circle for both square
    and non-square source images, the position dot tracks the ring across a
    whole track, `...` opens and closes the overlay, and shuffle/repeat state in
    the overlay matches Music Assistant.
14. Change `Screen Style` while the queue, playlists, or room controls page is
    open. The device must stay on that page and only apply the new layout when
    it next returns home.

## Updating

- Update the Home Assistant integration through HACS.
- Revalidate and install firmware updates through ESPHome/OTA.
- Review release notes before adopting changes to hardware-critical sections.

## Development

Pure transformation tests use the standard library:

```text
python -m unittest discover -s tests -v
```

When iterating on the firmware, point the device YAML at a working branch
instead of `main`. Note that `asset_base_url` defaults to the `main` branch, so
override it as well whenever the branch changes image assets:

```yaml
substitutions:
  asset_base_url: "https://raw.githubusercontent.com/VahaC/music-assistant-esp32s34848s040-controller/dev/firmware/assets"

packages:
  media_controller:
    url: https://github.com/VahaC/music-assistant-esp32s34848s040-controller
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
  media_controller: !include ../music-assistant-esp32s34848s040-controller/firmware/media-controller.yaml
```

Users should pin a release tag rather than a branch, so that work in progress on
`main` never reaches them mid-change.

## License

MIT — see `LICENSE`.
