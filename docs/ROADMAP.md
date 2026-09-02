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
2. **Capability-forwarding proxies.** `ControllerLight` mirrors
   `supported_color_modes`, `color_temp_kelvin`, and the min/max Kelvin bounds
   of its target instead of declaring a fixed colour mode. This is a
   [contract](CONTRACT.md) change and requires a contract version bump.
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
list is forbidden on the tablet for performance reasons.

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

The classic firmware keeps its compile-time token so that devices already in the
field are not disturbed; its
[limitation](ESP32_CONTROLLER.md#rest-token-limitation) is now a documented
property of that variant rather than an open problem.

Still outstanding: the paired firmware has passed `esphome config` and a full
compile but has not run on the physical device. The payload-size, memory,
reconnect and album-art testing this item always called for is now the hardware
checklist at the end of its document.

## 4. One interface, two transports

The two firmwares share
[media-controller-ui.yaml](../firmware/media-controller-ui.yaml), and the seam
between interface and transport is a list of names in its header: the `cmd_`
scripts a widget calls, the three scripts that turn a payload into widgets, and
the thirteen state ids the interface reads. It holds today because nothing in
the interface names a Home Assistant entity or performs a Home Assistant call.

A widget that reaches for `homeassistant.service` directly, or a substitution
that creeps into the interface package, would compile happily under the classic
firmware and break the paired one. `.github/workflows/firmware.yml` now checks
both: the interface package may contain no `homeassistant.` call and no
substitution other than `ha_url` and `asset_base_url`.

What is still only a convention is the rest of the seam — the `cmd_` names, the
three payload-to-widget scripts, and the thirteen state ids. Renaming one of
them breaks the other firmware in a way nothing catches until it is compiled,
which is why both firmwares are validated on every change to `firmware/**`.
