# Roadmap

Planned work that crosses component boundaries. Single-component work belongs in
that component's own documentation.

## 1. Home Assistant owns the room configuration

**Specified in [ROOM_SLOTS.md](ROOM_SLOTS.md).** That document supersedes the
planned shape below, which is kept as the record of how the problem was framed.

Today the T560 panel reads its tile list from `config.ini` on the tablet, and
the ESP32 reads entity IDs from flash-time substitutions. Adding a room control
therefore means editing a file over SSH, or reflashing. The goal is that every
device a client controls is defined in Home Assistant.

What blocks it now:

- `config_flow.py` has four fixed slots — `light_1`, `light_2`, `fan`, `ac` —
  while the panel already shows six tiles.
- Proxy lights declare `ColorMode.BRIGHTNESS` only, so a tile that offers a
  colour-temperature control must bypass the proxy and address the real light.
- Tile labels, order, and enabled controls exist only in `config.ini`; Home
  Assistant has no representation of them.

Planned shape:

1. **Dynamic slots.** Options Flow gains a repeatable room item: source entity,
   label, kind (`light` / `switch`), and enabled controls (`brightness`,
   `color_temperature`). Proxies are created from that list instead of from
   constants.
2. **Capability-forwarding proxies.** The proxy light mirrors
   `supported_color_modes`, `color_temp_kelvin`, and the min/max Kelvin bounds
   of its target instead of declaring a fixed colour mode. This is a
   [contract](CONTRACT.md) change and requires a contract version bump.
   *(Overtaken: contract version 6 replaced the proxies with a registry of
   real entities, and version 9 removed the last of them. A client reads
   `controls`, `min_kelvin` and `max_kelvin` off the element and calls the
   real light.)*
3. **A layout sensor.** `sensor.<controller>_panel_layout` carries the whole
   tile list in its attributes, the same mechanism the queue and playlists
   sensors already use:

   ```json
   {
     "tiles": [
       {
         "entity": "light.controller_light_1",
         "label": "LIGHT 1",
         "type": "light",
         "features": ["brightness", "color_temperature"],
         "order": 1
       }
     ]
   }
   ```

   Exclude it from the recorder; it is configuration, not history.
4. **Client bootstrap.** `config.ini` keeps only what cannot come from Home
   Assistant: `url`, the token, one bootstrap entity ID for the layout sensor,
   and tablet-local settings (`screen_off_seconds`, the whole `[camera]`
   section, poll intervals). **Done, and gone further than planned:**
   `screen_off_seconds` and both poll intervals are owned by Home Assistant as
   of contract version 3, and the `config.ini` keys are the fallback used
   before a tablet has ever reached it. Only the `[camera]` section is still
   tablet-local.
5. **Offline cache.** The panel must render the last known layout when Home
   Assistant is unreachable at boot. Today the configuration is local and this
   problem does not exist; after the move it does.

Clients must keep requesting single entities. Reading the whole `/api/states`
list is forbidden on the tablet for performance reasons. They must also keep
polling only for what the page on screen draws: see **Request only what the
active page draws** in [the contract](CONTRACT.md).

## 2. Panel portability

The panel is not tied to postmarketOS. It is tied to Linux, X11, and Openbox:

- the GTK3 application needs only `gtk+-3.0`, `libsoup-3.0`, `json-glib-1.0`;
- the battery indicator reads `/sys/class/power_supply` and degrades to hidden
  when it is absent;
- `t560-power-button.py` is strictly X11: `libX11`, `libXext` (DPMS), `libXss`
  (idle), `XGrabPointer`, `xset`, `xdotool`;
- `t560-configure-openbox.py` writes an Openbox `rc.xml`;
- `t560-motion-detector.py` uses raw V4L2 ioctls and works with any UVC camera.

Consequences:

- Any X11 Linux runs it after a rebuild — Alpine, Debian, Raspberry Pi OS,
  Arch, Fedora. Only packaging changes.
- Another X11 window manager needs a replacement for the Openbox key binding
  only.
- Wayland needs `t560-power-button.py` rewritten against
  `ext-idle-notify-v1`, output power management, and DBus. There is no
  `XGrabPointer` equivalent for the consumed wake touch.
- The real constraint is geometry, not the operating system: the window default
  is 800x1219 portrait and several widget sizes are absolute.

A Raspberry Pi with a portrait touchscreen is the cheapest second target, and
motion detection would actually work there — the SM-T560 camera driver rejects
`VIDIOC_REQBUFS`, which is why it ships disabled.

Renaming the `t560-` prefix to something hardware-neutral belongs to that work,
not before it.

## 3. Removing the REST token from the firmware

**Answered, by a second firmware rather than by changing the first.**
[media-controller-paired.yaml](../firmware/media-controller-paired.yaml) is
paired from Home Assistant with a six-digit code, is handed a revocable token,
and keeps no entity ID and no secret in the build. See
[ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md).

The classic firmware kept its compile-time token, so that devices already in
the field were not disturbed. Contract version 9 removed that firmware
altogether — it was built on the ESPHome native API, which is the dependency
that version exists to remove — so the question no longer has two answers.

Still outstanding: the paired firmware has passed `esphome config` and a full
compile but has not run on the physical device. The payload-size, memory,
reconnect and album-art testing this item always called for is now the hardware
checklist at the end of its document.

## 3a. Installing a panel without a toolchain

**Answered.** The paired firmware is published as one universal image and
installed from a browser over USB: see **The web installer** in
[ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md). Nothing personal is
compiled into it — no Wi-Fi credentials, no Home Assistant address, no token,
no API key, no update password — so one file serves everybody and publishing
it leaks nothing.

Three things had to move for that to be possible, and they are worth knowing
about because each one is a small contract of its own:

1. **`ha_url` became a runtime value.** It is still a substitution, and a
   package-built device still wins with it at every boot, but the firmware
   reads a `ha_base` global that pairing can fill in instead.
2. **Pairing gained a direction.** A client that advertises a non-zero port
   serves a provisioning endpoint and Home Assistant posts to it; a client
   that advertises port 0 polls, which is what the tablet does. See
   **Discovery and pairing** in [CONTRACT.md](CONTRACT.md).
3. **Wi-Fi comes over the USB cable**, through Improv in the installer page,
   with a captive portal as the recovery path.

Still outstanding, and honestly outstanding:

- **none of it has run on hardware.** The image compiles and is scanned for
  credentials in continuous integration; the first USB install, Improv, the
  captive portal and pairing in the pushed direction are all unverified. The
  checklist at the end of
  [ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md) covers them.
- **over-the-air updates landed in contract version 8**, and the reasoning
  that used to stand here is worth keeping because it is what shaped the
  answer. A password compiled into a public binary is not a password, so the
  shipped image still has no `ota: platform: esphome`. What it has instead is
  `platform: http_request`, which opens no port and only fetches when the
  firmware decides to — and the firmware decides to only when Home Assistant
  has put a version in the config sensor that panel reads with the token
  minted for it alone. The authority is the pairing, not a shared secret.
  Home Assistant downloads and verifies the image and serves it over the
  local network, because a panel on an isolated VLAN cannot reach GitHub. See
  **Panel firmware endpoint** in [CONTRACT.md](CONTRACT.md).

  Two things about it are still honestly outstanding. **None of it has run on
  hardware**: the download, the write, a deliberately broken build and the
  rollback are all unverified, and the checklist in
  [ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md) covers them. And
  **a panel on 0.5.0 has to be moved forward once over USB** — that build has
  no update client at all, so there is nothing in it to tell, and no change on
  either side can reach it. Home Assistant offers such a panel nothing and
  raises the repair issue that sends its owner to the installer page instead.
- **GitHub Pages has to be switched on once, by hand.** Settings → Pages →
  Source: GitHub Actions. The workflow is written and cannot set it.

## 4. One interface, one transport

**Settled.** There were two firmwares sharing
[media-controller-ui.yaml](../firmware/media-controller-ui.yaml). Contract
version 9 removed the classic one, because it was built on
`platform: homeassistant` sensors and `homeassistant.service` calls and so
required the ESPHome integration by construction. The split it existed for is
worth keeping anyway, and this item records why.

The seam between the interface package and the transport half is a list of
names in the interface's header: the `cmd_` scripts a widget calls, the
scripts that turn a payload into widgets, the `refresh_` scripts a page calls
when it opens, the theme globals, and the state ids the interface reads. It
holds because nothing in the interface names a Home Assistant entity or
performs a Home Assistant call.

That rule is not bookkeeping. It is what let the same interface be compiled
into an image that has **no Home Assistant address in it at all** — the
factory image the web installer publishes — and it is what would let a second
transport exist again without touching a widget.
`.github/workflows/firmware.yml` enforces the half of it that can be
enforced: the interface package may contain no `homeassistant.` call and no
substitution other than `asset_base_url`. The rest — the `cmd_` names, the
payload-to-widget scripts and the state ids — is still a convention, and
renaming one now breaks a compile rather than the other firmware.

### What the removal took with it

The classic firmware read `slots`: four numbered room controls backed by proxy
entities, resolved while compiling. It could never have had the on-device
grid, and that was a property of the hardware binding rather than a phase of
work nobody had reached:

- its four buttons resolved `${light1_entity}` and the service domain
  (`light.toggle` versus `switch.toggle`) while compiling, so it could not act
  on an entity it learned at runtime;
- the four buttons had absolute LVGL geometry and compile-time icon assets, so
  there was no place to put a fifth;
- it had no cache, so there was nothing for a user-arranged layout to live in
  across a reboot.

So the grid was always a paired-firmware feature, and planning it as something
both would eventually get would have been planning something that could not be
built. All of it has landed, and there is now only one client to have landed
it on. See [ROOM_SLOTS.md](ROOM_SLOTS.md).

One thing outlived the removal without being cleaned up: the interface package
still draws `page_switches`, the four fixed room buttons, and still declares
the `cmd_slot_*` scripts that go with them. Nothing reaches that page —
`room_page_index` points at the grid — and nothing fills those buttons, since
a panel has been sent no `slots` block since contract version 6. Taking them
out means rearranging an LVGL page list that works, on hardware nobody has
regression-tested lately, for no user-visible gain; it is worth doing on a
change that is already touching those pages, and not on its own.

