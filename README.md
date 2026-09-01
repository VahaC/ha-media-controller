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
| Media Controller integration | [custom_components/media_controller/](custom_components/media_controller) | HACS custom integration. Queue and playlist sensors, room proxy entities, two services. Required by both clients. |
| ESP32-S3 controller | [firmware/](firmware) | ESPHome package for the 480x480 ST7701S + GT911 board sold as `ESP32-S3-4848S040`. Three LVGL screen styles. |
| T560 panel | [clients/t560/](clients/t560) | Native GTK3 application for a Samsung Galaxy Tab E SM-T560 (ARMv7) running postmarketOS and Openbox. No browser, no WebKit. |

Choose either client, or run both against one Home Assistant.

## Documentation

| Document | Read it when |
| --- | --- |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Installing or configuring the Home Assistant side. Start here — both clients depend on it. |
| [docs/ESP32_CONTROLLER.md](docs/ESP32_CONTROLLER.md) | Flashing, configuring, or modifying the ESP32-S3 controller. |
| [clients/t560/README.md](clients/t560/README.md) | Building, deploying, or modifying the tablet panel. |
| [docs/CONTRACT.md](docs/CONTRACT.md) | Changing anything a client reads. This is the change-control surface. |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned work: Home Assistant-owned panel layout, colour-temperature proxies, portability. |
| [docs/MERGE.md](docs/MERGE.md) | Understanding why the repository is laid out this way, and which paths must never move. |

## Quick start

1. Install the **Media Controller** integration through HACS by adding
   `https://github.com/VahaC/ha-media-controller` as a custom **Integration**
   repository, then configure it against a Music Assistant player.
   Full steps: [docs/INTEGRATION.md](docs/INTEGRATION.md).
2. Copy the actual entity IDs Home Assistant assigned to the new controller
   device.
3. Set up a client:
   - ESP32-S3 — [docs/ESP32_CONTROLLER.md](docs/ESP32_CONTROLLER.md);
   - T560 tablet — [clients/t560/docs/BUILD_AND_INSTALL.md](clients/t560/docs/BUILD_AND_INSTALL.md).

## Repository layout

```text
custom_components/media_controller/   Home Assistant integration (HACS)
firmware/                             ESPHome package and image assets
clients/t560/                         GTK3 tablet panel (C, Python helpers)
docs/                                 Cross-component documentation
tests/                                Integration transformation tests
```

`custom_components/media_controller/` and `firmware/` are frozen paths. Device
configurations in the field point at `firmware/media-controller.yaml` and at
`firmware/assets/` by raw URL, and HACS downloads the integration from its path.
Moving either breaks installations that already exist. See
[docs/MERGE.md](docs/MERGE.md).

## Versioning

Each component is released on its own tag, because their audiences and update
mechanisms are different:

```text
integration-vX.Y.Z    custom_components/**
firmware-vX.Y.Z       firmware/**
panel-vX.Y.Z          clients/t560/**
```

`version` in `custom_components/media_controller/manifest.json` is bumped only
when the integration itself changes; it drives the HACS update prompt and must
not move for a client-only change.

A change to [docs/CONTRACT.md](docs/CONTRACT.md) requires a coordinated release
of the integration and every affected client.

## Tests

```text
python -m unittest discover -s tests -v          # integration transformations
cd clients/t560 && make test                     # panel JSON parsing + helpers
esphome config firmware/media-controller.yaml    # firmware validation
```

## License

MIT — see [LICENSE](LICENSE). It covers the integration, the firmware package,
and the clients.
