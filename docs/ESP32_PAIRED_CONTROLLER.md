# ESP32-S3 controller, paired

The same hardware and the same screens as the
[classic firmware](ESP32_CONTROLLER.md), configured from Home Assistant instead
of from a YAML file. You flash it once with no entity IDs and no token; the
device shows a six-digit code, Home Assistant discovers it and asks you to type
that code, and you then choose the player and the room controls in the Home
Assistant UI. Changing which lamp a button drives is a Home Assistant action,
not a reflash.

It is the same idea the [T560 panel](../clients/t560/README.md) already uses,
and the same mechanism: both are paired, both hold a token Home Assistant
minted for them, and both read the [contract](CONTRACT.md) over the REST API.

## Which firmware to use

Both are maintained, both work against one Home Assistant at the same time, and
they share every pixel of their interface. Pick on setup and latency.

| | [`media-controller.yaml`](../firmware/media-controller.yaml) | [`media-controller-paired.yaml`](../firmware/media-controller-paired.yaml) |
| --- | --- | --- |
| Setup | nine entity IDs and a token, typed into YAML | a six-digit code shown on the screen |
| Changing a room control | reflash | Home Assistant UI |
| What a slot may hold | slots 1–2 a light, 3–4 a switch, fixed at compile time | any light or switch, in any of the four |
| Token | in `secrets.yaml`, permanent, yours to manage | minted at pairing, revoked when you remove the device |
| Transport | ESPHome native API, pushed | REST, polled about once a second |
| State latency | immediate | up to one poll interval |
| In Home Assistant | an ESPHome device and a controller entry | an ESPHome device and a panel entry |
| Theme, opacities, diagnostics | on the ESPHome device | on the ESPHome device, unchanged |
| Screen and page control from Home Assistant | no | yes |
| Interface | [`media-controller-ui.yaml`](../firmware/media-controller-ui.yaml) | the same file |

The honest trade is latency. The classic firmware is told about a change; this
one asks. Volume and the track position step rather than glide, exactly as they
do on the tablet.

Nothing about the classic firmware changed, and an already flashed device needs
no attention.

## Validation status

`esphome config` and a full ESPHome 2026.8.0 compile pass — 38.0% RAM, 21.9%
flash, within a rounding error of the classic firmware. **This firmware has not
yet run on the physical device.** Work through the
[hardware checklist](#hardware-verification) before treating it as done; the
one-second poll and its effect on `Loop Time` is the part that cannot be judged
from a build.

## Prerequisites

1. The Media Controller integration, installed and configured against a Music
   Assistant player ([INTEGRATION.md](INTEGRATION.md)). The paired device
   attaches to a controller; it does not replace one.
2. ESPHome for compiling and flashing.

You do **not** need a long-lived access token. Home Assistant creates one for
this device, gives it a dedicated non-administrator user, and revokes it when
you remove the device.

## Configure and flash

Paste this into the device configuration in ESPHome Device Builder. It is the
whole thing; `packages:` downloads the maintained firmware, the shared
interface, and the image assets from this repository.

```yaml
substitutions:
  # Keep the existing ESPHome device name when updating an already adopted
  # device; changing it creates a different device identity in Home Assistant.
  device_name: media-controller
  friendly_name: Media Controller

  # Where Home Assistant is. The only address the firmware needs, and the only
  # value copied from anywhere. Use an IP address if .local names are
  # unreliable on your network.
  ha_url: "http://homeassistant.local:8123"

packages:
  media_controller:
    url: https://github.com/VahaC/ha-media-controller
    ref: main
    files:
      - firmware/media-controller-paired.yaml
    refresh: 1h

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

`ha_url` is the one address the device needs. Home Assistant advertises itself
over mDNS, but ESPHome can publish records and not browse for them, so unlike
the tablet this device cannot find the URL for itself.

The API encryption key stays here too, and it is not the same kind of secret as
the token. The token is a credential for Home Assistant's API, which Home
Assistant mints and hands over. The encryption key is a credential for *this
device's* API, where Home Assistant is the client connecting in — it would have
to be talking to the device already in order to deliver it. In practice nobody
types it: ESPHome Device Builder generates it into `secrets.yaml` and the
ESPHome integration reads it from the dashboard.

A ready-made copy of the block above is in
[firmware/media-controller-paired.example.yaml](../firmware/media-controller-paired.example.yaml).

## Pairing

1. Flash and let the device boot. It shows six digits and
   *Add this device in Home Assistant*.
2. Home Assistant discovers it. **Settings → Devices & Services** shows a new
   *ESP32-S3 controller (paired)* card; if it does not appear, add
   **Media Controller** by hand and choose that device type.
3. Type the six digits from the screen.
4. Choose which controller it plays from, then fill the four room slots. Any of
   them may be a light or a switch. Leave one empty to hide its tile.
5. The screen switches to the player by itself. Nothing else is typed.

The code is generated once and kept in flash, so a reboot in the middle of the
process does not change the digits you are reading. An approval lasts five
minutes and survives being polled; a wrong code five times cancels it and the
device shows a fresh one after a restart.

### If pairing does not finish

| On screen | What it means |
| --- | --- |
| *Add this device in Home Assistant* | Home Assistant has no panel with this device's ID yet. Add it. |
| *Enter this code in Home Assistant* | It is waiting for the code, or the one typed was wrong. |
| *Accepted — finish the setup form* | The code was right. The token follows once you finish choosing the controller and the room slots. |
| *Home Assistant returned an error* | `ha_url` is wrong, or Home Assistant is unreachable. |

If the token is ever rejected — you removed the device in Home Assistant, or
revoked its user — the firmware notices the first refused request, forgets the
token and returns to a pairing code on its own.

## What it does at runtime

Once a second it asks Home Assistant for the config sensor and the player. The
config sensor is what names all the others, which is why it is fetched every
cycle and not merely when a layout changes: it is also the channel Home
Assistant sends screen and page commands through.

Room entities are polled at a fifth of that rate, one request each. An
`http_request` on ESP-IDF blocks the main loop, so six requests a second would
be six stalls a second in front of LVGL. A lamp somebody switched elsewhere can
take five seconds to catch up; a lamp switched *here* does not wait, because the
button asks for a fresh read as soon as Home Assistant has had time to act.

The queue is fetched when the track title changes rather than on every tick,
because it is the one large payload. Playlists have an interval of their own.
Both intervals are owned by Home Assistant and arrive with the rest.

Everything it learned — the token, the config sensor, the player, the queue and
playlist sensors and the four slot entities — is kept in flash, so a device that
boots while Home Assistant is down still draws its last known room and asks for
the right entities the moment it comes back.

## What Home Assistant gains

Because it is a panel rather than a controller, the device gets the panel
entities described in the [contract](CONTRACT.md): a page selector, a screen
switch, a brightness number, a restart button, and the sensors that say whether
it is being heard from. It reports its uptime and its display state once a
minute.

Two contract features are deliberately not wired up:

- **`screen_off_seconds`.** The device already owns a *Screen Timeout* number on
  its ESPHome device, and its range (5–120 s) is narrower than the contract's.
  Two owners for one setting is a bug waiting to happen, so `number.<panel>_screen_off`
  does nothing here — use *Screen Timeout*.
- **Battery and Wi-Fi signal.** It is mains powered, and the configuration you
  paste decides whether it is on Wi-Fi or Ethernet at all, so the package cannot
  declare a signal sensor. Both are optional in the contract.

## Room slots

Four, the number of buttons on the room page. Unlike the classic firmware, none
of them is tied to a domain: the entity arrives with the payload and the
firmware reads the domain off it, so a switch in slot 1 and a light in slot 4
both work. A long press dims a light and is ignored by a switch.

Colour temperature is not offered. The device has four buttons and a long-press
brightness gesture, and no control to set a temperature with.

## Hardware verification

None of this has run on the physical device yet.

1. Flash with no entity substitutions. The pairing code appears within a few
   seconds of boot.
2. Home Assistant discovers the device without being told its address.
3. The typed code is accepted, and the screen leaves the pairing page by itself
   once the setup form is finished.
4. Title, artist, album art, volume, position, play/pause, next, previous,
   shuffle and repeat all follow the player. Judge how the one-second poll
   feels; the volume and the progress ring are where it shows.
5. The queue loads, highlights the current entry, and jumps on selection.
6. Playlists load, Unicode names render, and a selected playlist starts.
7. All four room buttons show state and toggle. Put a `switch` in slot 1 and a
   `light` in slot 4 to prove the domain is read at runtime.
8. Change a slot target in Home Assistant. The button repoints within a poll,
   with no reflash. This is the whole point of the firmware.
9. Reboot with Home Assistant stopped. The device must keep its token, draw its
   last known room, and recover on its own when Home Assistant returns.
10. Delete the panel in Home Assistant. The device must return to a pairing
    code by itself.
11. The screen switch, brightness number, page selector and restart button on
    the panel device all work, and the restart does **not** repeat on the next
    boot.
12. Watch `Media Controller Heap Free`, `Heap Min Free` and `Loop Time` under
    the poll load. Two blocking requests a second in the steady state is the new
    cost, briefly more when the room page refreshes. `Loop Time` is the number
    to watch: an `http_request` on ESP-IDF blocks the main loop, so this is the
    change most likely to show up as a stutter. If it does, raise **Update
    interval** on the panel device — Home Assistant owns it and no reflash is
    needed.
13. A classic device on the same Home Assistant keeps working throughout.
