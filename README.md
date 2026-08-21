# VahaC ESP32 Music Assistant Media Controller

An ESPHome touchscreen controller for Home Assistant and Music Assistant,
built for the ESP32-S3 480×480 ST7701S + GT911 board commonly sold as
`ESP32-S3-4848S040`.

The project packages the existing working controller as:

- a HACS-compatible Home Assistant custom integration;
- a reusable ESPHome package with all build assets in this repository;
- a migration path that removes Pyscript and two manual synchronization
  automations after verification.

The LVGL interface, display timings, touch pins, media controls, album art,
queue windowing, playlists, room controls, sleep timer, and consumed wake touch
are intentionally preserved.

## Current validation status

The custom integration transformation tests and static repository checks pass.
The packaged example also passes `esphome config` and a complete ESPHome
2026.8.0 compile. Physical target testing is still required before a release is
tagged. See [Hardware verification](#hardware-verification).

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
3. Install **VahaC Media Controller** and restart Home Assistant.
4. Open Settings → Devices & services → Add integration.
5. Select **VahaC Media Controller**.
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

The old queue automation no longer contains a player entity ID: the integration
listens to the Music Assistant player selected in Config Flow. The ESPHome
device still uses its `player_entity` substitution for native media state and
control actions. If the selected player is changed later in Options Flow,
update that substitution during the next ESPHome/OTA update as well.

### Synchronization behavior

- Playlists refresh during integration setup and every six hours.
- Queue data refreshes after a Music Assistant title change with a cancellable
  three-second debounce.
- Only 50 queue entries are requested, starting up to five entries before the
  current item.
- Rapid changes cancel obsolete delays and queue calls cannot overlap.
- `vahac_media_controller.refresh` refreshes queue and playlists on demand.
- `vahac_media_controller.play_queue_item` starts the selected queue item by
  its Music Assistant queue item ID without replacing the queue.

## Configure and flash ESPHome

### Local package

1. Copy `firmware/media-controller.example.yaml` to a local file such as
   `media-controller.local.yaml`.
2. Copy `firmware/secrets.example.yaml` to `firmware/secrets.yaml`.
3. Replace every placeholder in both local files.
4. Set `player_entity` to the Music Assistant player selected in Config Flow.
5. Set the queue/playlists/light/switch substitutions to the entity IDs created
   by the VahaC integration.
6. Validate and compile:

   ```text
   esphome config firmware/media-controller.local.yaml
   esphome compile firmware/media-controller.local.yaml
   ```

7. Flash by USB for the first installation, then use ESPHome OTA updates.

The 2,000+ line maintained UI stays in `firmware/media-controller.yaml`; the
user edits only the small local configuration.

### Git package

`firmware/media-controller.remote.example.yaml` demonstrates the current
ESPHome Git package syntax. Copy it into your ESPHome configuration directory,
set the substitutions, and keep all `!secret` values in that directory's
`secrets.yaml`.

Remote ESPHome packages cannot contain secret lookups. This is why Wi-Fi, API
encryption, OTA, the fallback AP password, and the Home Assistant token are in
the small user configuration rather than the maintained package.

## REST token limitation

Version 1 intentionally retains the existing Home Assistant REST transport for
queue, playlist, and album-art requests. The ESP32 sends a bearer token only to
the configured local `ha_url`.

Use a dedicated token, store it only in `secrets.yaml`, do not commit it, and
keep the ESPHome device and Home Assistant on a trusted local network. Removing
the token is a later security milestone that requires payload-size, ESP32
memory, reconnect, and album-art testing; it is not mixed into this migration.

## Migration from the legacy installation

Do not remove the working Pyscript setup first. Use this order:

1. Keep the legacy Pyscript files and automations enabled.
2. Install and configure the new integration.
3. Confirm its queue sensor contains a compact JSON `data` attribute with
   `titles`, `artists`, `queue_ids`, `current_index`, and `count`.
4. Confirm its playlists sensor contains `names`, `uris`, and `count`, with
   generated `(from library)` entries filtered out.
5. Point a test firmware configuration at the new entity IDs and compile it.
6. Disable—not delete—the two legacy synchronization automations and reload
   Pyscript or restart Home Assistant.
7. Verify startup/periodic playlists, delayed queue updates, queue item playback,
   playlist playback, and a Home Assistant restart.
8. Complete the physical checks below.

Only after every check passes is it safe to remove:

- Pyscript, if no other automation uses it;
- `sync_ma_queue.py`;
- `set_ma_playlists.py` (the legacy filename differs from the earlier handoff
  name `sync_ma_playlists.py`);
- the legacy queue automation;
- the legacy playlist automation;
- `input_select.music_playlist`, if nothing else uses it.

Exact pre-migration reference files remain under `legacy/` for rollback and
behavior comparison. The original `home-assistant/` directory is also retained
during the hardware-validation period.

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

The Phase 0 audit and implementation sequence are recorded in
`docs/IMPLEMENTATION_PLAN.md`.

## License

MIT — see `LICENSE`.
