# Home Assistant integration

`custom_components/media_controller` is the server side of this project. Both
clients — the [ESP32-S3 controller](ESP32_CONTROLLER.md) and the
[T560 panel](../clients/t560/README.md) — read the entities it publishes and
call the services it registers. Nothing else in this repository works without
it.

The exact entity and service surface is specified in [CONTRACT.md](CONTRACT.md).

## Prerequisites

1. A current Home Assistant installation.
2. The official Music Assistant integration with at least one exposed
   `media_player` entity.
3. HACS for custom-integration installation.

## Install

Until this repository is included in the default HACS catalog:

1. Open HACS → Integrations → Custom repositories.
2. Add
   `https://github.com/VahaC/ha-media-controller`
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


The T560 panel reads the same queue and playlists sensors and the same proxy
entities over the Home Assistant REST API. It needs no firmware substitutions:
its entity IDs live in `config.ini` on the tablet.

## Services

`media_controller.refresh` refreshes queue and playlists immediately. The
optional `entry_id` field limits it to one controller entry; omit it to refresh
every loaded controller.

`media_controller.play_queue_item` starts a Music Assistant queue item without
replacing the queue. It requires the Music Assistant `entity_id` and the
`queue_item_id` taken from the queue sensor payload.

Both are declared in
[services.yaml](../custom_components/media_controller/services.yaml).

## Brand images

The integration ships its own icon and logo in
`custom_components/media_controller/brand/`:

| File | Size |
| --- | --- |
| `icon.png` | 256x256 |
| `icon@2x.png` | 512x512 |
| `logo.png` | 256x256 |
| `logo@2x.png` | 512x512 |

They are the T560 panel application icon, so the integration in Home Assistant,
the tablet launcher, and the tablet task bar all show the same mark. The source
of truth is `clients/t560/data/icons/hicolor/<size>/apps/t560-music-panel.png`,
generated from geometry by `clients/t560/tools/make-app-icon.py`. After
regenerating it, copy both sizes across:

```bash
cp clients/t560/data/icons/hicolor/256x256/apps/t560-music-panel.png custom_components/media_controller/brand/icon.png
cp clients/t560/data/icons/hicolor/512x512/apps/t560-music-panel.png custom_components/media_controller/brand/icon@2x.png
cp clients/t560/data/icons/hicolor/256x256/apps/t560-music-panel.png custom_components/media_controller/brand/logo.png
cp clients/t560/data/icons/hicolor/512x512/apps/t560-music-panel.png custom_components/media_controller/brand/logo@2x.png
```

Optional `dark_icon.png`, `dark_logo.png`, and their `@2x` variants are also
supported. This icon reads on both themes, so they are not shipped.

### Where each image is used

- **Home Assistant 2026.3 and newer** serves the local files through
  `/api/brands/integration/media_controller/icon.png`. Local brand images take
  priority over the brands CDN, so the mark appears on the Integrations page,
  in the config flow dialog, and on the device page with no further setup.
- **Older Home Assistant versions** ignore the folder and fall back to the CDN.
- **The HACS store listing** still reads the CDN
  (`https://brands.home-assistant.io/_/media_controller/icon.png`) and does not
  yet fall back to the local proxy; `hacs/integration#5171` and
  `hacs/integration#5223` are open. To get the icon in the HACS panel as well,
  submit the same four files to the legacy `custom_integrations/media_controller/`
  folder of <https://github.com/home-assistant/brands>. That folder is marked
  legacy but is still accepted, and the file names and pixel sizes are identical,
  so `custom_components/media_controller/brand/` can be copied into it unchanged.

### Reaching an already-installed instance

1. Release the integration. HACS offers an update only when `version` in
   `manifest.json` changes; `0.7.2` carries this icon.
2. The user updates through HACS and restarts Home Assistant.
3. Brand images are cached on disk and served stale-while-revalidate, so a
   browser hard refresh (Ctrl+Shift+R) may be needed before the new mark
   appears.

A manual installation replaces `custom_components/media_controller/` and
restarts Home Assistant; the same cache note applies.

### Deliberately not set

`hacs.json` does not declare a minimum Home Assistant version. The integration
itself works below 2026.3 â only the local brand images do not. Declaring
`"homeassistant": "2026.3.0"` would block installation for those users over an
icon.

## Updating

Update the integration through HACS. When the `version` field in
[manifest.json](../custom_components/media_controller/manifest.json) changes,
HACS offers the update; the clients are unaffected until their own release is
adopted.

Read [CONTRACT.md](CONTRACT.md) before changing the payload shape of the queue
or playlists sensors, the proxy entity behavior, or a service signature. Those
changes reach both clients.

## Development

Pure transformation tests use the standard library:

```text
python -m unittest discover -s tests -v
```

`tests/` at the repository root belongs to the integration. The T560 panel has
its own tests under `clients/t560/tests/`.
