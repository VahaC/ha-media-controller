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

## Updating

- Update the Home Assistant integration through HACS.
- Revalidate and install firmware updates through ESPHome/OTA.
- Review release notes before adopting changes to hardware-critical sections.

## Development

Pure transformation tests use the standard library:

```text
python -m unittest discover -s tests -v
```

## License

MIT — see `LICENSE`.
