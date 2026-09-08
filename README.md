# Home Assistant Media Controller

A Home Assistant custom integration and two touch panels for Music Assistant.

The integration turns Music Assistant queue and playlist data into a form small
devices can consume, and publishes the room entities each panel may control.
The panels render it. Both speak exactly the same
[entity and service contract](docs/CONTRACT.md), so a room control changed in
Home Assistant changes on every screen without reflashing or redeploying
anything.

**Neither panel needs the ESPHome integration.** An ESP32 panel is installed
from a browser, paired with a six-digit code, and never appears in ESPHome at
all; everything you see in Home Assistant comes from this integration. ESPHome
builds the firmware, the way a compiler builds a program.

For the build story, photos, and setup walkthrough, see the write-up:
[Music Assistant ESP32 Media Controller](https://vahac.com/blogs/music-assistant-esp32-media-controller/?utm_source=github).

## Components

| Component | Path | What it is |
| --- | --- | --- |
| Media Controller integration | [custom_components/media_controller/](custom_components/media_controller) | HACS custom integration. Queue and playlist sensors, the room registry, and every entity a panel owns. Required by every client. |
| ESP32-S3 panel | [firmware/media-controller-paired.yaml](firmware/media-controller-paired.yaml) | ESPHome package for the 480x480 ST7701S + GT911 board sold as `ESP32-S3-4848S040`. Three LVGL screen styles, paired from Home Assistant with a six-digit code. No entity IDs and no token in the build; room controls, the home layout and the colours are chosen in the Home Assistant UI and changed without reflashing. |
| ESP32-S3 web installer | [https://vahac.github.io/ha-media-controller/](https://vahac.github.io/ha-media-controller/) | The paired firmware as one finished image for every board, installed from a browser over USB. No ESPHome, no YAML, no `secrets.yaml`. Wi-Fi is typed into the same page and never leaves the machine. |
| T560 panel | [clients/t560/](clients/t560) | Native GTK3 application for a Samsung Galaxy Tab E SM-T560 (ARMv7) running postmarketOS and Openbox. No browser, no WebKit. Two interface skins, chosen from Home Assistant. |

Choose either panel, or run both against one Home Assistant.

The web installer is not a second firmware. It publishes the ESP32 firmware as
a finished image with nothing personal compiled into it, so that installing a
panel needs a browser and a cable rather than a toolchain. ESPHome still builds
that image — in this repository's continuous integration, not on your machine.

A third component used to be here: `firmware/media-controller.yaml`, the
classic ESP32 firmware, configured by flashing nine entity IDs and a long-lived
token into a YAML file. It reached Home Assistant over the ESPHome native API,
which is the dependency contract version 9 removed, so it went with it. The
board is the same one: install the factory image over USB and it becomes a
paired panel. See
[Moving a classic device forward](docs/ESP32_PAIRED_CONTROLLER.md#moving-a-classic-device-forward).

## Documentation

| Document | Read it when |
| --- | --- |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Installing or configuring the Home Assistant side. Start here — both clients depend on it. |
| [docs/ESP32_PAIRED_CONTROLLER.md](docs/ESP32_PAIRED_CONTROLLER.md) | Installing, configuring, or modifying the ESP32-S3 panel. Start here for a new build. |
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
   - ESP32-S3, from the browser — open <https://vahac.github.io/ha-media-controller/> in desktop Chrome or
     Edge, plug the board into that computer with a USB cable, press Install,
     and give it your Wi-Fi on the same page. Type the six digits it then shows
     into Home Assistant. This is the shortest path and needs no ESPHome:
     [docs/ESP32_PAIRED_CONTROLLER.md](docs/ESP32_PAIRED_CONTROLLER.md).
     That is the only time the cable is needed: a paired panel is updated from
     **Settings → Updates** afterwards, authenticated by the token it was
     given when it paired.
   - ESP32-S3, from an ESPHome package — the same firmware, for an
     installation that already runs ESPHome:
     [docs/ESP32_PAIRED_CONTROLLER.md](docs/ESP32_PAIRED_CONTROLLER.md).
   - T560 tablet — [clients/t560/docs/BUILD_AND_INSTALL.md](clients/t560/docs/BUILD_AND_INSTALL.md).

## Repository layout

```text
custom_components/media_controller/   Home Assistant integration (HACS)
firmware/media-controller-ui.yaml     ESPHome interface: display, LVGL, theme
firmware/media-controller-paired.yaml Transport: REST, config from Home Assistant
firmware/media-controller-factory.yaml The same firmware as one shipped image, with nothing personal in it
firmware/assets/                      Image assets, fetched at compile time
firmware/requirements.txt             The pinned ESPHome that builds the published image
custom_components/media_controller/icons/  Card artwork the integration serves to panels
components/media_controller_grid/     ESPHome external component: the paired room grid and its editor
components/media_controller_provision/ ESPHome external component: the endpoint Home Assistant hands a panel its bootstrap over
installer/                            The web installer page, published to GitHub Pages
tools/make-web-installer.py           Publishes both images and the release index the update entity reads
clients/t560/                         GTK3 tablet panel (C, Python helpers)
docs/                                 Cross-component documentation
tests/                                Integration transformation tests
```

`custom_components/media_controller/`, every path under `firmware/`, and
`components/` are frozen. Device configurations in the
field name a firmware file and `firmware/assets/` by raw URL, HACS downloads
the integration from its path, and a paired device pulls the external component
from `components/` as an ESPHome Git source. `media-controller-ui.yaml` is
frozen for a subtler reason: devices reach it through a relative `!include`
from a file they do name, so renaming it breaks devices that never mention it.
Moving any of them breaks installations that already exist. See
[docs/MERGE.md](docs/MERGE.md).

## Versioning

Each component is released on its own tag, because their audiences and update
mechanisms are different:

```text
integration-vX.Y.Z    custom_components/**
firmware-vX.Y.Z       firmware/** and components/**
panel-vX.Y.Z          clients/t560/**
```

One `firmware-` tag covers the ESP32 firmware, the interface package it
includes and the external components it loads, because they ship together and
the components are pinned to `main`. Each entrypoint also carries its own
`project.version`: `media_controller.esp32s3_paired` for the package build and
`media_controller.esp32s3_factory` for the same firmware as a shipped image.

Pushing a `vX.Y.Z` tag is also what publishes the web installer: it compiles
the factory image, checks it carries no credentials, and deploys the page with
that version's binary under a path naming it. It creates no release — releases
here are written by hand. See
[.github/workflows/installer.yml](.github/workflows/installer.yml).

`version` in `custom_components/media_controller/manifest.json` is bumped only
when the integration itself changes; it drives the HACS update prompt and must
not move for a client-only change.

A change to [docs/CONTRACT.md](docs/CONTRACT.md) requires a coordinated release
of the integration and every affected client.

## Tests

```text
python -m unittest discover -s tests -v                 # integration transformations
python tools/make-icon-assets.py --check                # card artwork is in step with the catalog
cd clients/t560 && make test                            # panel JSON parsing + helpers
esphome config <your device YAML>                       # the package build
esphome config firmware/media-controller-factory.yaml   # the shipped image
```

`firmware/media-controller-paired.yaml` is a package rather than a complete
device configuration — it deliberately takes Wi-Fi from whatever imports it —
so it is validated through a device wrapper. `.github/workflows/firmware.yml`
builds one; `firmware/paired-check.local.yaml` is the same thing locally, and
neither carries `api:`, because a shipped panel has none.

## License

MIT — see [LICENSE](LICENSE). It covers the integration, the firmware package,
and the clients.
