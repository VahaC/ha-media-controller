# Home Assistant Media Controller

A Home Assistant custom integration and two touch controllers for Music
Assistant.

The integration turns Music Assistant queue and playlist data into a form small
devices can consume, and provides remappable room proxy entities. The clients
render it. Both clients speak exactly the same
[entity and service contract](docs/CONTRACT.md), so a room control remapped in
Home Assistant changes on every screen without reflashing or redeploying
anything.

For the build story, photos, and setup walkthrough, see the write-up:
[Music Assistant ESP32 Media Controller](https://vahac.com/blogs/music-assistant-esp32-media-controller/?utm_source=github).

## Components

| Component | Path | What it is |
| --- | --- | --- |
| Media Controller integration | [custom_components/media_controller/](custom_components/media_controller) | HACS custom integration. Queue and playlist sensors, room proxy entities, two services. Required by every client. |
| ESP32-S3 controller | [firmware/media-controller.yaml](firmware/media-controller.yaml) | ESPHome package for the 480x480 ST7701S + GT911 board sold as `ESP32-S3-4848S040`. Three LVGL screen styles. Configured by flashing: entity IDs and a token live in the YAML. |
| ESP32-S3 controller, paired | [firmware/media-controller-paired.yaml](firmware/media-controller-paired.yaml) | The same board and the same screens, paired from Home Assistant with a six-digit code. No entity IDs and no token in the build; room controls are chosen in the Home Assistant UI and changed without reflashing. |
| T560 panel | [clients/t560/](clients/t560) | Native GTK3 application for a Samsung Galaxy Tab E SM-T560 (ARMv7) running postmarketOS and Openbox. No browser, no WebKit. |

Choose any one client, or run all of them against one Home Assistant.

The two ESP32 firmwares are the same device configured two ways, and they share
every pixel of their interface through
[firmware/media-controller-ui.yaml](firmware/media-controller-ui.yaml). Nothing
about the classic one changed when the paired one arrived, so a device already
in the field needs no attention; the
[comparison table](docs/ESP32_PAIRED_CONTROLLER.md#which-firmware-to-use) is
there when you want to move.

## Documentation

| Document | Read it when |
| --- | --- |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Installing or configuring the Home Assistant side. Start here — both clients depend on it. |
| [docs/ESP32_CONTROLLER.md](docs/ESP32_CONTROLLER.md) | Flashing, configuring, or modifying the ESP32-S3 controller. |
| [docs/ESP32_PAIRED_CONTROLLER.md](docs/ESP32_PAIRED_CONTROLLER.md) | The same board, paired from Home Assistant instead of configured by flashing. Start here for a new build. |
| [clients/t560/README.md](clients/t560/README.md) | Building, deploying, or modifying the tablet panel. |
| [docs/CONTRACT.md](docs/CONTRACT.md) | Changing anything a client reads. This is the change-control surface. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned work: Home Assistant-owned panel layout, colour-temperature proxies, portability. |
| [docs/MERGE.md](docs/MERGE.md) | Understanding why the repository is laid out this way, and which paths must never move. |

## Quick start

1. Install the **Media Controller** integration through HACS by adding
   `https://github.com/VahaC/ha-media-controller` as a custom **Integration**
   repository, then point it at a Music Assistant player. That creates a
   **media player source** — the thing every client plays from, and the reason
   this step comes first. Home Assistant lists it under *Services*, because it
   is a binding rather than hardware.
   Full steps: [docs/INTEGRATION.md](docs/INTEGRATION.md).
2. Set up a client. Each one becomes a **panel** device of its own, attached to
   the source from step 1:
   - ESP32-S3, paired — [docs/ESP32_PAIRED_CONTROLLER.md](docs/ESP32_PAIRED_CONTROLLER.md).
     Flash, type the six digits it shows, choose the rooms in Home Assistant.
   - ESP32-S3, classic — [docs/ESP32_CONTROLLER.md](docs/ESP32_CONTROLLER.md).
     Copy the entity IDs Home Assistant assigned to the new source into the
     YAML first.
   - T560 tablet — [clients/t560/docs/BUILD_AND_INSTALL.md](clients/t560/docs/BUILD_AND_INSTALL.md).

## Repository layout

```text
custom_components/media_controller/   Home Assistant integration (HACS)
firmware/media-controller-ui.yaml     Shared ESPHome interface: display, LVGL, theme
firmware/media-controller.yaml        Classic transport: native API, flashed config
firmware/media-controller-paired.yaml Paired transport: REST, config from Home Assistant
firmware/assets/                      Image assets, fetched at compile time
clients/t560/                         GTK3 tablet panel (C, Python helpers)
docs/                                 Cross-component documentation
tests/                                Integration transformation tests
```

`custom_components/media_controller/` and every path under `firmware/` are
frozen. Device configurations in the field name a firmware file and
`firmware/assets/` by raw URL, and HACS downloads the integration from its path.
`media-controller-ui.yaml` is frozen for a subtler reason: devices reach it
through a relative `!include` from a file they do name, so renaming it breaks
devices that never mention it. Moving any of them breaks installations that
already exist. See [docs/MERGE.md](docs/MERGE.md).

## Versioning

Each component is released on its own tag, because their audiences and update
mechanisms are different:

```text
integration-vX.Y.Z    custom_components/**
firmware-vX.Y.Z       firmware/**
panel-vX.Y.Z          clients/t560/**
```

One `firmware-` tag covers both ESP32 firmwares and the interface package they
share, because a change to that package ships to both at once. Each firmware
also carries its own `project.version`, which is what ESPHome shows on the
device: `media_controller.esp32s3` for the classic one and
`media_controller.esp32s3_paired` for the paired one.

`version` in `custom_components/media_controller/manifest.json` is bumped only
when the integration itself changes; it drives the HACS update prompt and must
not move for a client-only change.

A change to [docs/CONTRACT.md](docs/CONTRACT.md) requires a coordinated release
of the integration and every affected client.

## Tests

```text
python -m unittest discover -s tests -v                 # integration transformations
cd clients/t560 && make test                            # panel JSON parsing + helpers
esphome config firmware/media-controller.yaml           # classic firmware
esphome config firmware/media-controller-paired.yaml    # paired firmware
```

Both firmware files must validate: they share an interface package, so a change
to it is a change to both.

## License

MIT — see [LICENSE](LICENSE). It covers the integration, the firmware package,
and the clients.
