# ESP32-S3 panel

A touchscreen panel for Home Assistant and Music Assistant, built for the
ESP32-S3 480x480 ST7701S + GT911 board commonly sold as `ESP32-S3-4848S040`.

It is configured from Home Assistant rather than from a YAML file. You install
it once with no entity IDs and no token; the device shows a six-digit code,
Home Assistant discovers it and asks you to type that code, and you then choose
the player and the room controls in the Home Assistant UI. Changing which lamp
a button drives is a Home Assistant action, not a reinstall.

**The ESPHome integration is not involved at any point.** A panel does not
appear in it, is never adopted, needs no encryption key, and contributes no
entity through it. Everything you see in Home Assistant comes from
`media_controller`. See [Home Assistant, and no ESPHome](#home-assistant-and-no-esphome).

**The recommended way to install it is a browser.** Open
<https://vahac.github.io/ha-media-controller/>, plug the board into the same computer with a USB cable, and
press Install. No ESPHome, no YAML, no `secrets.yaml`, and no account anywhere.
See [The web installer](#the-web-installer) below.

It is the same idea the [T560 panel](../clients/t560/README.md) already uses,
and the same mechanism: both are paired, both hold a token Home Assistant
minted for them, and both read the [contract](CONTRACT.md) over the REST API.

## Which firmware to use

There are two ways to install one firmware. **Start with the factory image**;
the package build is for people who already run ESPHome and would rather keep
this device beside their others.

| | Factory image | [`media-controller-paired.yaml`](../firmware/media-controller-paired.yaml) |
| --- | --- | --- |
| How you install it | a web page and a USB cable | ESPHome, from a package |
| What you configure first | nothing | Wi-Fi and an address, in YAML |
| Wi-Fi | typed into the installer page, over USB | `secrets.yaml` |
| Where Home Assistant is | sent during pairing | `ha_url` in YAML |
| Setup in Home Assistant | a six-digit code shown on the screen | the same |
| Changing a room control | Home Assistant UI | the same |
| Token | minted at pairing, revoked when you remove the device | the same |
| Transport | REST, polled about once a second | the same |
| Updates | over the air, from Home Assistant | the same, or `esphome run` |
| In the ESPHome dashboard | no | no, unless you opt in |
| Interface | [`media-controller-ui.yaml`](../firmware/media-controller-ui.yaml) | the same file |

The factory image and the paired package are the **same firmware**. The factory
image is that firmware plus three things a shipped binary needs and a personal
one does not: an empty address, Wi-Fi over USB and a recovery access point. See
[firmware/media-controller-factory.yaml](../firmware/media-controller-factory.yaml).

There used to be a third column here: `firmware/media-controller.yaml`, the
classic firmware, which read nine entity IDs and a long-lived token out of
substitutions and reached Home Assistant over the ESPHome native API. Contract
version 9 removed it. See
[Moving a classic device forward](#moving-a-classic-device-forward).

### Home Assistant, and no ESPHome

**You do not need ESPHome to install or run this firmware, and a panel never
appears in the ESPHome integration.**

Both halves of that are new in contract version 9. Installing without ESPHome
has been true since version 8 — the factory image is a finished file, the web
installer writes it to the board and hands it your Wi-Fi, and Home Assistant
does the rest. What was still true until version 9 is that a panel *also* spoke
the ESPHome native API: it turned up in the ESPHome integration as a discovered
device asking to be adopted, and about a dozen of the entities you saw came
from there rather than from `media_controller`. So a panel's backlight had two
owners, and an installation had a dependency on an integration it did not
otherwise need.

`api:` is gone from the firmware, and nothing suppresses discovery by hand.
ESPHome publishes the `_esphomelib._tcp` mDNS record only when the native API
is compiled in, and that record is the only thing the ESPHome integration's
discovery looks for. No key, no record, nothing to find. What a panel does
advertise is `_media-controller._tcp`, which is what this integration finds it
by.

Nothing was lost from Home Assistant. The twelve appearance values became the
`theme` block of the contract and are now `text.<panel>_color_*` and
`number.<panel>_opacity_*` on the panel's own device; the seven diagnostics
became the `diagnostics` block of the status report and are now
`sensor.<panel>_heap_free` and the rest. Both are described under
[What Home Assistant gains](#what-home-assistant-gains).

Two things were lost from ESPHome, and both are honest losses:

- **adoption in ESPHome Device Builder.** A panel is installed from the web
  installer and updated from Home Assistant instead; see
  [Updating](#updating);
- **the log stream in the ESPHome dashboard.** Logs still come out of UART0
  over the USB-C port at 115200 baud, which is the same cable the device is
  flashed with. `esphome logs firmware/media-controller-factory.yaml` reads
  them over serial, and so does any terminal — `screen`, `picocom`, the
  Arduino IDE's serial monitor. What is gone is reading them over the
  network.

ESPHome is still how the firmware is *built*. The image published by the
installer is compiled by ESPHome in this repository's continuous integration,
from [`media-controller-factory.yaml`](../firmware/media-controller-factory.yaml)
and the package beside it. That is a maintainer's tool, in the same sense that
a compiler is: it is not something a person installing a panel has to have,
know about, or keep in step.

### Keeping a package build in the ESPHome dashboard

If you build this firmware as an ESPHome package and you want the device in
your dashboard anyway, add the native API in **your own** device YAML, on top
of the package:

```yaml
packages:
  panel: github://VahaC/ha-media-controller/firmware/media-controller-paired.yaml@main

# Opt-in. This is not part of the maintained package.
api:
  encryption:
    key: !secret media_controller_api_key
```

Know what it does before you do it: the device starts publishing
`_esphomelib._tcp` again, so the ESPHome integration discovers it and offers to
adopt it, and you get a second Home Assistant device carrying entities beside
the ones this contract already provides. Everything in this document keeps
working; you are adding a second channel, not switching to one.

The factory image cannot opt in — it is a published binary, and a key inside it
would be the same key on every panel flashed from it.

### Moving a classic device forward

`firmware/media-controller.yaml` was built on `platform: homeassistant` sensors
and `homeassistant.service` calls. That is the ESPHome integration by
construction, so it could not survive a version whose whole point is that the
integration is not needed, and contract version 9 removed it.

A device still running it keeps running: nothing reaches out and stops it. What
does stop is maintenance — the file is gone from this repository, so a
`packages:` block that points at it no longer resolves once your ESPHome next
refreshes the package.

It is the same board. Install the factory image over USB from the web installer
and the device becomes a paired panel, with everything in this document.

Two things do not come across, and neither can:

- **the room controls.** They were four numbered slots backed by proxy
  entities — `light.<source>_slot_1` and the rest — and those proxies are
  deleted from Home Assistant. Choose the same entities again in the panel's
  options; they become registry elements, and you arrange them on a grid
  instead of on four fixed buttons. Anything that referenced a proxy — an
  automation, a script, a dashboard card — has to be pointed at the real
  entity;
- **the history of those proxies.** A deleted entity takes its recorder
  history with it. If you want it, export it before you install.

Everything else survives: the source config entry, the Music Assistant player
it is bound to, the queue and playlist sensors, and every automation that uses
them.

## Validation status

Firmware 0.4.0 passes `esphome config` on ESPHome 2026.8.0, in both shapes:
the paired package through a device wrapper, and the factory entrypoint. The
**factory image compiles**, and the merged image was scanned for addresses,
tokens and placeholder credentials and carries none.

**None of it has run on the physical device.** Work through the
[hardware checklist](#hardware-verification) before treating any of it as done.
Nothing below has been observed on hardware: not the first USB install, not
Improv, not the captive portal, not discovery, not pairing in either direction.
Three things in particular cannot be judged from a build: the one-second poll
and its effect on `Loop Time`, the cost of building a full grid of 64 cards in
one go, and whether a 60 px card is legible and hittable in the hand.

One board-specific choice in the factory image is also unverified. Its
`logger:` is moved to `UART0`, because GPIO19 and GPIO20 — which an ESP32-S3
uses for native USB — are the touchscreen's I²C bus on this board, so the
ESP-IDF default of `USB_SERIAL_JTAG` can reach nothing over the USB-C socket.
That is what Improv needs a working port for. If the serial step does not
appear in the installer, this is the first thing to check.

## Prerequisites

1. The Media Controller integration, installed and configured against a Music
   Assistant player ([INTEGRATION.md](INTEGRATION.md)). The paired device
   attaches to a controller; it does not replace one.
2. Either a browser that can talk to a USB serial port, or ESPHome. See below.

You do **not** need a long-lived access token. Home Assistant creates one for
this device, gives it a dedicated non-administrator user, and revokes it when
you remove the device.

## The web installer

<{INSTALLER_URL}>

One image, the same for every board. It contains no Wi-Fi credentials, no Home
Assistant address, no access token and no update password, so it is not
personal to anybody and nothing about publishing it leaks anything. It has no
ESPHome native API either, which is why a panel flashed from it never appears
in the ESPHome integration.

### What you need

* an **ESP32-S3-4848S040** — the 4-inch 480×480 board with an ST7701S display
  and a GT911 touchscreen. It is the only board this image is built for;
* a **USB-C data cable**, plugged into the computer the browser is running on.
  The panel has to be attached to that machine, not to a server elsewhere in
  the house: the browser talks to the serial port directly;
* desktop **Chrome**, **Edge** or **Opera**. Web Serial does not exist in
  Safari or Firefox, and does not exist in any browser on iOS or Android. The
  page checks and says so rather than failing at the flash step;
* the page over **HTTPS**. Web Serial is refused in an insecure context, which
  is why the installer is published on GitHub Pages and cannot be served from
  `http://homeassistant.local:8123`.

### Connect → Install → Configure Wi-Fi

1. Plug the panel in and press **Connect**. Pick the serial port.
2. Press **Install**, and confirm erasing the device on a first install.
3. When the flash finishes, the same dialog offers **Wi-Fi**. Enter the network
   and the password.

The credentials travel down the USB cable and nowhere else. They are not sent
to the page, to GitHub, or to any build server — there is no per-user build:
everybody installs the same file, and nothing about the network reaches
anything but the board in front of you.

If the port does not appear, or the install refuses to start, put the board
into download mode by hand: hold **BOOT**, tap **RESET**, release **BOOT**,
then press **Connect** again.

### Recovering a panel whose Wi-Fi changed

A panel that cannot reach the network it was given raises its own access point,
**Media Controller Setup**, about a minute after it gives up. Join it from a
phone; a page opens where you enter the new network, and the panel restarts
onto it. It keeps its Home Assistant pairing throughout — only the network
changed.

The access point is open, because a password shared by every copy of a public
binary would not be one. It exists only while the panel cannot reach a network,
and it can be avoided entirely by plugging the panel into a computer and using
the installer's **Connect** button, which offers the Wi-Fi step again without
reinstalling anything.

### Updating

**From Home Assistant.** A paired panel has a **Firmware** entity on its
device page and appears under **Settings → Updates** like anything else. Press
**Install** and the panel takes the new build over your own network; it keeps
its Wi-Fi, its pairing, its token and its room layout, because an update
writes the application and nothing else.

It takes a couple of minutes. During the download the panel keeps working;
during the write it shows **UPDATING** and stops responding to touch entirely,
which is why that screen asks you not to switch it off. It restarts on its own
and comes back on the new build.

Nothing about this needs a password, and the reason is worth stating: the
panel is not listening for an update. It fetches one, and only after Home
Assistant has put a version in the config sensor that panel reads with the
token minted for it alone at pairing. Home Assistant does the downloading —
the panel never talks to the internet — checks the released image against its
published SHA-256, and serves the bytes it verified over the local network.
Somebody who has downloaded the public binary has nothing that lets them flash
your panel with it, and revoking a panel's token stops updates the way it
stops everything else.

If the new build does not come back, the panel's bootloader puts the previous
one back on its own. It keeps the old image until the new one has re-read its
config sensor and had a status report accepted; a build that crashes never
gets that far, and one that runs but can never reach Home Assistant again
restarts itself after ten minutes so the bootloader can undo it. Either way
the panel returns to the build it was on, with everything intact.

**Two panels this does not cover.**

- **A panel still running 0.5.0** has to be updated over USB once. That build
  has no update client in it at all, so there is nothing to tell — no change
  to Home Assistant can reach it. Home Assistant knows this and offers it
  nothing; it raises the repair issue that points here instead. After that one
  USB install it never needs a cable again.
- **A panel installed from the ESPHome package** keeps its own ESPHome OTA as
  well, with the password its owner chose, and is updated from ESPHome Device
  Builder as before. Nothing about that changes.

**Over USB, which stays the recovery path.** Connect the panel and press
**Install** again with the same page. Installing over an existing panel keeps
its Wi-Fi credentials and its Home Assistant pairing, so it comes back on its
own; choosing **erase device** clears both and the panel shows a new pairing
code. This is what to reach for when a panel is on 0.5.0, when it has no
working network, or when anything else has gone wrong badly enough that Home
Assistant cannot see it.

`ota: platform: esphome` — the one with a password and a listening socket — is
still **not** in this image and will not be. A password compiled into a file
anybody can download protects nothing: a shared one would let anyone on the
network replace the firmware on every panel installed from this page.

The one exception is narrow and worth knowing about, and it has not changed:
while the recovery access point is up, ESPHome's captive portal also serves a
firmware upload at `/update`, and it has no password either. It is reachable
only from that access point, only while the panel cannot reach a network, and
the same build disables that route on the ordinary house network. If that is
not a trade you want, do not use the recovery portal — reconfigure over USB
instead.

### Which version you installed

The page installs one named version, and the binary it names lives under a path
carrying that version, so a link to a build keeps meaning the same build.

The page carries **that one version only**: each deploy replaces the whole
site. An older image is rebuilt from its tag, or attached to its release by
hand at release time.

## The ESPHome package path

For an installation that already runs ESPHome and wants this device in that
dashboard, with over-the-air updates and an encryption key it manages itself.
Everything about the running firmware is identical to the factory image; only
the way it is built and installed differs.

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

`ha_url` is the one address a package-built device needs. Home Assistant
advertises itself over mDNS, but ESPHome can publish records and not browse for
them, so unlike the tablet this device cannot find the URL for itself.

It is a **bootstrap** value rather than the address the firmware uses. At every
boot a non-empty `ha_url` is copied into the `ha_base` global, so a device
built this way behaves exactly as it always did: editing the address and
reflashing still moves the device to another Home Assistant. The factory image
leaves the substitution empty, which is what makes it universal — there the
address arrives during pairing and is kept in flash.

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

1. Let the device boot onto your network. It shows six digits and
   *Add this device in Home Assistant*.
2. Home Assistant discovers it over mDNS — the device advertises
   `_media-controller._tcp.local.` with its MAC as the panel ID.
   **Settings → Devices & Services** shows a new *ESP32-S3 panel* card. If
   mDNS does not get through — a VLAN, a bridge that drops multicast — the
   card still appears, a few seconds later: an unpaired device polls Home
   Assistant for a token it does not have yet, and that poll carries the
   same panel ID, so Home Assistant offers it from there instead. Nothing is
   added by hand and no identifier is ever typed.

   If this is the first device in a fresh installation and no media player
   source exists yet, step 4 asks for the Music Assistant player and creates
   one for you.
3. Type the six digits from the screen.
4. Choose which media player source it plays from, then fill the four room
   slots. Any of them may be a light or a switch. Leave one empty to hide its
   tile.
5. The screen switches to the player by itself. Nothing else is typed.

The code is generated once and kept in flash, so a reboot in the middle of the
process does not change the digits you are reading.

**The screen does not sleep while the code is up.** *Screen Timeout* is
suspended for as long as the device is unpaired, and a device that was already
asleep when its token was revoked lights up again by itself. A code nobody can
read is not a code, and the person walking to the panel with a phone in their
hand is not touching it. The normal timeout resumes the moment the device is
paired, counted from then.

### Which way round it runs

The exchange goes in one of two directions, and Home Assistant picks by
reading the discovery record. It needs no setting and no second service type.

**Home Assistant posts to the device**, when the record advertises a port —
which the ESP32 firmware does, because it serves a web server anyway. Home
Assistant asks the device whether the typed code is the one on its screen, and
only then mints a token; a mistyped code therefore costs nothing and leaves no
credential and no Home Assistant user behind. Once the panel's entry exists,
Home Assistant posts the three things it needs — its own address, the token,
and the entity ID of the config sensor — to the device's provisioning
endpoint. **This is the only way a factory-image device can be paired**, since
it has no address to ask at.

**The device polls Home Assistant**, when the record advertises port 0, which
is what a T560 tablet does because it serves nothing. Home Assistant holds the
approval and answers the poll that carries the right code. A package-built
ESP32 with an `ha_url` can be paired either way, and falls back to this one if
its own endpoint does not answer.

Where Home Assistant gets its own address from, in the first case, is its
configured internal URL — **Settings → System → Network**. If it has none the
setup asks you to type one, as the last step rather than the first, so the
installation that has an internal URL is never asked at all.

### What guards the endpoint

The provisioning endpoint on the device is unauthenticated, because the caller
has no credentials yet. What stands in the way of anything else using it:

* it answers only while the device is **unpaired**. The moment a token is
  stored, every route but the read-only identity one refuses with `409`;
* the code is six digits shown on the device's own screen and nowhere else;
* five wrong codes close it for five minutes, which turns a million-guess
  search into about a year of them;
* the code is compared in constant time, the request body is capped at a
  kilobyte, and every field inside it has a limit of its own;
* the address it accepts must be an origin — scheme and host, no path — so a
  payload cannot redirect the requests the device makes afterwards;
* nothing a caller sends is ever logged. The token is not printed at any log
  level.

An approval on the Home Assistant side lasts five minutes and survives being
polled; five wrong codes cancel it there too.

If a token is minted and then cannot be delivered — the panel went off the
network between typing the code and finishing the form — Home Assistant revokes
it rather than leaving it behind, and asks for a code again through the
ordinary reauthentication prompt.

### If pairing does not finish

| On screen | What it means |
| --- | --- |
| *Add this device in Home Assistant* | Home Assistant has no panel with this device's ID yet. Add it. |
| *Enter this code in Home Assistant* | It is waiting for the code, or the one typed was wrong. |
| *Accepted — finish the setup form* | The code was right. The token follows once you finish choosing the source and the room slots. |
| *Home Assistant returned an error* | `ha_url` is wrong, or Home Assistant is unreachable. |

A factory-image device shows only the first of those, because it never polls:
it has no address to poll. It waits, and the code stays on screen until Home
Assistant posts to it.

If the token is ever rejected — you removed the device in Home Assistant, or
revoked its user — the firmware notices the first refused request, forgets the
token and returns to a pairing code on its own. **It forgets only the Home
Assistant pairing.** Wi-Fi credentials are untouched, so the device stays on
the network and can be paired again without a cable.

### `HTTP Request failed ... Code: 404` in the log

Expected, and not a fault. `404` is how the provisioning endpoint says *no
panel with this ID exists yet*; there is no other answer it could give before
the device has been added. ESPHome logs every non-2xx response as an error and
briefly flags the `http_request` component, and neither can be switched off
from YAML.

What the firmware does instead is stop asking so often: after two minutes of
nothing but `404` the poll drops from three seconds to fifteen, and any other
answer puts it straight back to three. The status is logged once per change
rather than once per poll. An unopened device on a shelf therefore stays quiet,
and one being added is still responsive.

## What it does at runtime

Once a second it asks Home Assistant for the config sensor, and for the player
while a page that draws it is showing. The config sensor is what names all the
others, which is why it is fetched every cycle and not merely when a layout
changes: it is also the channel Home Assistant sends screen and page commands
through.

Everything else is asked for only behind the page that displays it. The player
is read on the three home layouts, and on the queue page, where a title change
is what says the queue has moved on; the playlists are read only on the
playlists page; the forecast only on the room page. Each of those pages also
fetches once at the moment it opens, through the `refresh_` script the
interface package calls from its `on_load`, so it never opens on data that
stopped being read when somebody navigated away. A device parked on the player
page makes one request a second, not four.

Room states arrive inside the same config poll, in the `room_states` block
the integration renders beside the registry: one small array per element,
keyed by rid, refreshed with every poll. They used to come from a template
rendered by POST `/api/template`, one request for the whole page — but that
endpoint answers administrators only, and this device's token belongs to a
dedicated non-administrator user, so Home Assistant refused it with 401 and
every card stayed blank. A lamp somebody switched elsewhere now catches up
with the next one-second poll; a lamp switched *here* does not wait, because
the card asks for a fresh read as soon as Home Assistant has had time to act.

The queue is fetched when the queue page opens, and again when the track title
changes while that page is the one showing, rather than on every tick: it is
the one large payload. Playlists have an interval of their own, which runs
only behind the playlists page. Both intervals are owned by Home Assistant and
arrive with the rest.

Everything it learned — the token, the config sensor, the player, the queue and
playlist sensors — is kept in flash, so a device that boots while Home Assistant
is down asks for the right entities the moment it comes back. The room
**arrangement** is in flash too, in a blob of its own, because it is the user's
own work rather than something Home Assistant can send again; the registry it
arranges is Home Assistant's and arrives with the first poll.

## What Home Assistant gains

Because it is a panel rather than a controller, the device gets the panel
entities described in the [contract](CONTRACT.md): a page selector, a screen
switch, a brightness number, a restart button, and the sensors that say whether
it is being heard from. It reports its uptime, display state, Wi-Fi signal and
internal temperature once a minute.

It also reports which version of the [contract](CONTRACT.md) it implements,
and reads the integration's own out of the config sensor, so that neither half
can be silently behind the other. If this device is the older one, Home
Assistant raises a repair issue naming it and pointing at the web installer. If
Home Assistant is the older one, the device says so in its serial log instead —
see [the note on logs above](#home-assistant-and-no-esphome):

```text
[W][config]: Home Assistant speaks contract 5 and this firmware needs 6:
update Media Controller
```

The number is `contract_version` in the substitutions block. It is not a knob
to turn per device: it says what this firmware understands, and changing it
only makes the device lie about itself.

### The appearance of the player

Eight colours and four opacities, as `text.<panel>_color_*` and
`number.<panel>_opacity_*` on the panel's device. A colour is `#RRGGBB`; an
opacity is 0 – 255. They are the twelve values that used to be ESPHome
entities, and they do exactly what they did.

Home Assistant owns them and sends them in the `theme` block of the config
sensor. The device applies them on the next poll and keeps what it applied in
its own flash, so a reboot while Home Assistant is down comes back looking the
same rather than grey. A value the device cannot parse leaves the colour it
already has, rather than resetting it.

Setting one restyles every layout at once — Classic, Minimal Ring and Cover
Card share the palette — and costs no re-layout: a colour is not part of the
configuration revision, so nothing is rebuilt and nothing flickers.

### Diagnostics

Seven readings, all under **Diagnostic** on the panel's device:

| Entity | What it says |
| --- | --- |
| `sensor.<panel>_heap_free` | Free heap now. It falls as the interface is used and comes back; one that only ever falls is a leak |
| `sensor.<panel>_heap_max_block` | The largest single free block. Plenty free with no large block is what an album-art decode fails on |
| `sensor.<panel>_heap_min_free` | The least free heap since the device started — how close it came overnight |
| `sensor.<panel>_heap_fragmentation` | How fragmented the heap is, as a percentage |
| `sensor.<panel>_psram_free` | Free PSRAM: the LVGL buffers and every decoded image |
| `sensor.<panel>_loop_time` | The **longest single** main-loop iteration in the last interval, not an average. This is the one that shows up as a gesture the panel ignored |
| `sensor.<panel>_reset_reason` | Why the device last restarted. Carried over from the previous boot, so read it beside the uptime |

They ride the status report the device already sends once a minute, so they
cost no extra request. The T560 panel does not report them and does not get
them: the entities exist only for a client that fills them.

### The screen timeout

`number.<panel>_screen_off` works. It did nothing on this firmware until
contract version 9, because a *Screen Timeout* number on the device's ESPHome
device owned the value and had a narrower range; that number is gone with the
rest of them, and this is the only owner left. Zero means never, which is what
a hallway panel on mains power usually wants. It does not apply while the
device is showing a pairing code; see [Pairing](#pairing).

**Battery** is the one contract field this device deliberately does not report.
It is mains powered. The field is optional and the sensor stays unavailable.

## Room controls

The room page is an **8 x 8 grid of 60 px cells** built at runtime, and what is
on it is decided in two places that never meet:

- **Home Assistant owns the registry.** The `entities` block of the config
  sensor says what this device may control: a `rid`, a real entity ID, a name,
  a domain and a list of controls, up to the 64 the `esp32_s3_panel` profile
  allows. Add and remove them in the device's options; see
  [ROOM_SLOTS.md](ROOM_SLOTS.md).
- **The device owns the arrangement.** Where each card sits and how large it is
  lives on the device, in NVS, and is edited in a small web page the device
  serves. Home Assistant has no opinion about it.

A card is keyed on `rid` and never on an entity ID. A Home Assistant entity ID
is renamed by the user at will, and a layout keyed on one would scatter the
next time somebody tidied their entity IDs.

A tap toggles. A long press dims a light and is ignored by a switch. Colour
temperature is still not offered: the device has a tap and a long press, and no
control to set a temperature with.

The page carries no heading and no hint. Eight rows of exactly 60 px need all
480 of them, and "tap to toggle | hold lights to dim" stops being true the
moment the person arranging the page decides what is on it.

Before anybody opens the editor the device lays the registry out for itself, as
2 x 2 cards in registry order, so the page is useful the moment it is configured
in Home Assistant rather than after a second, undiscoverable step.

### Why a grid is possible at all

Because nothing on this device is bound at compile time.

The classic firmware could never have had one, and that was a property of the
build rather than a phase of work nobody had got to. ESPHome binds an entity ID
while compiling in **both** directions: a `homeassistant` sensor names the
entity it reads, and a `homeassistant.service` call names the entity it writes.
A card that arrives at runtime carries an entity ID that was not in the image,
so that firmware could neither read its state nor act on it — which is why it
had four numbered slots backed by proxy entities, a proxy being a compile-time
name Home Assistant can repoint behind.

This firmware resolves both at runtime: it holds a token and calls the REST
API, so a card it was never flashed with works. Contract version 9 removed the
classic firmware and the slots with it, and the registry is now the only shape
a room control has.

### The layout editor

The device serves the editor on **port 80**, at `http://<device-ip>/`. It is the
same page the T560 panel serves; the two differ only where the device does.

The address is in the device's ESPHome log at start-up, and the device reports
it to Home Assistant with every status report, which turns it into the
**Visit** link on the device's *panel* page — the one this integration owns,
beside the battery and screen entities, not the ESPHome device page. So the
editor is one click from where its rooms were configured, rather than an IP
address somebody has to look up. A device that is not on the network yet
reports no address and gets no link.

**It has no password, on purpose.** A phone is where a grid gets arranged, and a
device that had to be logged into would not be. What makes the missing password
survivable is the shape of the API rather than a promise:

- there are exactly **ten routes**, and not one of them is a general proxy to
  Home Assistant. Nothing there can read a state, call an arbitrary service, or
  reach an entity the device does not already draw. The two routes that take a
  name from the caller — the skin preview and the card picture — compare it
  with what this build actually holds, and neither builds a path out of it;
- the one route that reaches Home Assistant at all, `POST /api/card`, changes
  the display name and the icon of a card **this device is already drawing**
  and nothing else. It cannot name an entity, add an element, or touch another
  device, and every value in it is checked here and again by the integration
  that owns the registry;
- the registry is served from the payload the device has already parsed, so a
  request to the editor never becomes a request to Home Assistant;
- the Home Assistant token never leaves the device and is readable through no
  route;
- **Restore** puts back the copy Home Assistant holds, so the worst an
  unauthenticated caller can do to a layout is undone by one button.

> **Do not forward this port through a router, and do not expose the device's
> IP address to the internet.** Everything above is a statement about what is
> reachable from the local network. It is not a substitute for a password, and
> nothing here is safe to publish.

The three writes are `POST` rather than the `PUT` and `DELETE` the T560 panel
uses. ESPHome's ESP-IDF web server registers URI handlers for `GET`, `POST` and
`OPTIONS` only, so a `PUT` never reaches a handler at all. The routes are:

| Route | Purpose |
| --- | --- |
| `GET /` | the editor page, one gzipped asset in flash |
| `GET /skins/<name>.png` | what one skin looks like |
| `GET /icons/<id>` | one card picture, out of what this device downloaded |
| `GET /api/entities` | the registry, the catalog, the grid size, the last restore and card write |
| `GET /api/layout` | the arrangement on screen |
| `POST /api/layout` | adopt and persist an arrangement |
| `POST /api/layout/restore` | ask for the copy Home Assistant holds |
| `GET /api/skins` | the skins this build draws, and the one on screen |
| `POST /api/skin` | ask Home Assistant for a skin |
| `POST /api/card` | ask Home Assistant for a card's display name and icon |

`POST /api/skin` calls `select.select_option` on this device's own *Player
Skin* select and nothing else, and the name is checked against the three skins
this build draws before it is sent. Home Assistant stays the owner of the value:
the device writes nothing locally and adopts the new skin on its next poll.

`POST /api/card` calls the integration's card-appearance endpoint for one
`rid` this device already draws. The name is trimmed, checked for control
characters and bounded at 64 characters here before it is sent; the icon has to
be one the published catalog carries. Home Assistant stays the owner of both:
the device writes nothing locally and the new name arrives on its next poll,
which is also what makes a house with a tablet and an ESP32 panel agree about
what a lamp is called without either of them telling the other. The write
cannot be answered inside the request — an HTTP call blocks the main loop — so
the device answers `queued` and reports the outcome on `GET /api/entities`,
exactly as **Restore** does.

### The card artwork

The pictures a card draws are **downloaded from Home Assistant** and are not
compiled in. Six are still linked into this firmware, and they are the
fallback: what a card shows before Home Assistant has answered, while it is
unreachable, when a download fails, and for an identifier this build has never
heard of. A room page that cannot reach Home Assistant is a page with plain
artwork on it, never an empty one.

Adding a picture to the catalog therefore costs no reflash. It used to: a card
stored a **1-based index into an array compiled into this firmware**, so the
set could grow only by flashing every device in the house, and reordering the
array would have silently moved everybody's icons. A card now stores a stable
identifier, in Home Assistant, against the registry element.

How the downloads behave, and why:

- the **catalog** — which identifiers exist, and what to call them — is asked
  for once after pairing and then every six hours. It changes when the
  integration is upgraded and never otherwise. It is deliberately not a block
  on the config sensor, which this device polls once a second;
- **one picture at a time**, spread over the poll tick rather than fetched in a
  burst. Each is six kilobytes through a request that blocks the main loop, and
  a burst is exactly what would be felt as a stall under a finger;
- what the **cards** draw comes first, always. The rest of the catalog is
  fetched only while somebody has the editor open, because a list of every
  picture is the only place the rest of it is looked at;
- a picture is decoded **once per identifier and shared**. A page of sixty-four
  cards naming three pictures holds three of them, not sixty-four, and the
  cache is bounded at sixteen — about 100 KB, taken from PSRAM where there is
  any. A picture a card is drawing is never evicted, because LVGL holds the
  address of its descriptor for as long as the widget exists;
- a download that fails is **left alone for a minute** rather than retried on
  every tick, so an unreachable Home Assistant does not become a request per
  loop;
- what arrives is a **pre-rendered variant and not a PNG**: an eight-byte
  header and then ARGB8888 at exactly 40 x 40, which is the size a card draws.
  This build sets `LV_COLOR_16_SWAP` and leaves `LV_DRAW_SW_SUPPORT_SWAPPED`
  off, so LVGL cannot transform a source at all, and the device has no PNG
  decoder to spare either. A body of the wrong length or the wrong header is
  refused rather than half-stored: it would be a buffer of the wrong shape
  handed to a renderer.

`GET /icons/<id>` serves the editor whatever the device has already
downloaded, wrapped in a BMP header on the way out — the pixels need no
rearranging, because they are already in the order a 32-bit BMP with an alpha
mask describes. There is no second download for the browser and no proxy: the
Home Assistant token never comes near it. An identifier the device has not
fetched yet is a 404, and the editor drops the image and keeps the name, which
is what it already does for a skin this build carries no picture of.

### The skin previews

A skin name says nothing about a layout, so the editor shows a picture of each
one beside the list. The pictures are **static PNGs linked into flash** beside
the editor, one per skin in `components/media_controller_grid/previews/`, and
`GET /skins/<name>.png` serves the one whose name matches. They are drawn by
`tools/make-skin-previews.py` from the same numbers the interface draws with —
the widget geometry in `media-controller-ui.yaml` — which is what makes them
reproducible from the repository rather than from a camera.

They are static on purpose. A live preview would mean a second implementation
of every home layout, in JavaScript, kept in step with the real one by hand;
the picture beside the list is a drawing of a layout and the status line under
it is what says whether the device actually adopted the skin.

Which skins the editor lists is the `skins:` block of
`media_controller_grid:`, which is the `esp32_s3_panel` profile's list in
`custom_components/media_controller/profiles.py` — the editor therefore offers
exactly what this build draws. A skin with no picture is still offered; the
tile shows its name and drops the image.

What they cost: about 6.4 kB of flash for the three of them, against about
8.8 kB for the gzipped editor beside them. They are **not** gzipped — a PNG is
already deflate-compressed, and wrapping one in a gzip member makes it about
twenty bytes larger — and are kept small where it pays instead: 144x144, and
quantised to a 48-colour palette.

Restoring is asked for and then watched rather than answered in one request:
fetching the copy from Home Assistant blocks the device's main loop, so the
device takes the request, answers `queued`, does the work on its own loop, and
reports the outcome on `GET /api/entities`.

### What a card draws

| Group | Tap | Long press | At one cell |
| --- | --- | --- | --- |
| `light` | toggle | sweeps brightness | icon and a tap |
| `switch` | toggle | — | icon and a tap |
| `climate` | toggle | sweeps the setpoint | icon and a tap |
| `weather` | — (a reading, never a button) | — | value, name where it fits |
| `sensor` | — (a reading) | — | value, name where it fits |

A `cover` element is drawn as a card with no action, because no cover card is
written for it **here** yet. The T560 draws the cover card defined by contract
version 7; this firmware does not, and a `cover` element reaches it carrying
controls it ignores. That client-specific subset is permitted and does not
make the firmware contract-incompatible. See **Registry entries** in
`docs/CONTRACT.md`.

A card two cells square or larger carries its name; a thermostat carries a
reading above the name as well — the temperature the room is at and the
setpoint, as `21.5° / 22°`. A large weather block is headed by its name, the
way the T560 panel draws it: the hero temperature large beneath it, the
condition with the humidity under the hero, and the coming days at the bottom
with the high in orange and the low in blue. It wears the same sky background
as the T560 reading. A sensor block carries its value with its unit, as
`21.5 °C`. A
thermostat that is **off** shows the room temperature alone: that number is
true either way, and the setpoint it used to be heading for is not. The
card's border already says which of the two it is.
At one cell there is 54 px of paint and room for the icon or the name but not
both, and the icon is the half that still says what the card is; that rule is
the same for every card type but one. A sensor below two cells in either
direction carries no icon: the name goes on top and the value under it, and
where both do not fit the name is dropped and the value stays, because the
value outranks the name.
A long name wraps onto a second line where the card has room for it, rather
than being ellipsized where it does not have to be. Exactly two lines are
kept; what sits above the name moves up by one line with it, and where even
that does not fit the name stays on one line.

A thermostat's setpoint sweep is **not** sent per tick, unlike a light's
brightness. The value moves on the device while the finger is down and goes to
Home Assistant once, on release: a lamp answers on mains wiring, and a
thermostat is very often a battery radiator valve on a Zigbee or Z-Wave mesh
that ten calls a second would flood with a value nobody has finished choosing.
Only a press that actually moved the value sends anything, so holding a card
for a moment and letting go writes nothing.

The sweep also needs a **running** thermostat. An off one shows the room
temperature rather than the setpoint, so sweeping it would move a number with
nothing on screen changing; turning it on is a tap, and the sweep is there the
moment it runs.

A tap does nothing on an element Home Assistant offered no `toggle` for — a
thermostat that cannot be turned off is a card that reads rather than acts.
A reading never acts at all: a weather or a sensor card is not clickable, has
no pressed face and carries no event callback, so a tap on it cannot become a
service call — the same contract the T560 panel keeps.

### Where the layout lives

On the device it is one NVS blob of 512 bytes: 64 records of 8 bytes, each
holding the `rid`, the cell and the span. It is a blob and not a string global
because `max_restore_data_length` is capped at 254 bytes, which a grid was
never going to fit.

The eighth byte of a record still holds the old icon index, and it is still
read. A layout document written by an older editor names one of the six
built-in pictures, and a card keeps drawing it until the first time anybody
chooses anything — at which point the choice goes to Home Assistant, where the
registry keeps it, and the stored index is shadowed. The editor clears it on
the next save. Nothing writes an index again.

After every save the device also sends a copy to Home Assistant, at
`/api/media_controller/panel_layout/<panel_id>`, where `panel_id` is the MAC
this device paired and reports with. Home Assistant stores it opaquely and never
parses it. That copy is what makes a wiped or replaced device recover its own
arrangement: press **Restore** in the editor. A save that cannot reach Home
Assistant still succeeds locally and says so.

## Hardware verification

None of this has run on the physical device yet.

### Installing and getting onto the network

Only the factory image needs these; a package-built device is flashed by
ESPHome as it always was.

- **First install.** Install the factory image from the web installer onto a
  board that has never run this firmware. The flash completes and the device
  restarts on its own.
- **Improv.** The installer offers the Wi-Fi step after the install. Enter a
  network and confirm the panel joins it. This is the step that depends on
  `logger:` being on `UART0`; if the step never appears, that is where to look.
- **On its own power.** Unplug the panel from USB and power it from a supply.
  It rejoins the network after a cold boot.
- **Captive portal.** Take the network away — change the router's password, or
  switch the SSID off. About a minute later the panel raises **Media Controller
  Setup**. Join it from a phone, enter a different network, and confirm the
  panel moves to it and keeps its Home Assistant pairing.
- **Reinstalling.** Install again over a working panel without erasing: it
  keeps its Wi-Fi and its pairing and comes back to the player screen. Then
  install with **erase device** and confirm it shows a new pairing code.
- **Two panels at once.** Install the same image on a second board and confirm
  the two do not collide: different hostnames, different mDNS records, two
  separate cards in Home Assistant.

### Pairing, and the panel itself

1. The pairing code appears within a few seconds of boot, and is the same code
   after a reboot in the middle of pairing.
1a. Set *Screen Timeout* to its minimum, leave the panel on the pairing page
    untouched for twice that, and confirm the code is still lit. Then finish
    pairing and confirm the screen starts sleeping again.
2. Home Assistant discovers the device without being told its address, and the
   card names it as an *ESP32-S3 panel*. Block multicast between the panel and
   Home Assistant and confirm the card still appears — from the panel's own
   poll — within a few seconds.
2a. Type a wrong code. The form says so, no Home Assistant user appears under
    **Settings → People**, and no token is created. Do it five times and
    confirm the device refuses for five minutes and says so, then accepts the
    right code afterwards.
2b. On a Home Assistant with no internal URL configured, confirm the setup asks
    for the address as its last step, and that the panel reaches Home Assistant
    at what was typed.
3. The typed code is accepted, and the screen leaves the pairing page by itself
   once the setup form is finished. The address and the token survive a reboot:
   power-cycle the panel and confirm it goes straight to the player.
3a. Pull the panel's power between typing the code and finishing the form. Home
    Assistant must revoke the token it minted — no leftover *Media Controller*
    user under **Settings → People** — and ask for a code again when the panel
    comes back.
4. Title, artist, album art, volume, position, play/pause, next, previous,
   shuffle and repeat all follow the player. Judge how the one-second poll
   feels; the volume and the progress ring are where it shows.
5. The queue loads, highlights the current entry, and jumps on selection.
6. Playlists load, Unicode names render, and a selected playlist starts.
7. The room page draws a card per registry element, 2 x 2 by default, and each
   one shows state and toggles. Mix a `switch` and a `light` to prove the
   domain is read at runtime; a long press must dim the light and do nothing
   to the switch.
8. Fill the registry to its limit of 64 elements, with Cyrillic names, and
   confirm the config payload is not cut off: the cards must all appear and
   the log must show `The registry now carries 64 element(s)`. A truncated
   response is silent, which is what made this worth checking.
9. Open `http://<device-ip>/` from a phone. Move a card, resize it, change its
   icon, save. The page redraws within a second and the layout survives a
   reboot.
9a. Give a card a display name, including a Cyrillic one, and confirm it
    appears on the physical card within a poll and survives a reboot. Clear
    the field and confirm the Home Assistant entity name comes back. Try a
    name over 64 characters and one with a newline pasted into it: both must
    be refused with a message rather than stored.
9b. Choose an integration-hosted icon the firmware carries no copy of —
    `desk-lamp` or `desk-led-strip` — and confirm it appears on the physical
    card. Watch the log for `Cached the icon` and for the cache count; give
    two cards the same icon and confirm only one copy is held. Check free
    PSRAM and internal heap before and after opening the editor, which is
    what prefetches the whole catalog.
9c. With Home Assistant stopped, reboot. Every card must draw built-in
    artwork, navigation and taps must keep working, and the log must not
    fill with icon requests. Start Home Assistant again and confirm the
    pictures arrive without a reboot.
10. Erase the device's flash and reflash it, then press **Restore** in the
    editor. The arrangement must come back from Home Assistant.
11. Change the skin in the editor. Home Assistant's *Player Skin* select moves,
    and the device follows on its next poll.
12. Change a registry element in Home Assistant. The card repoints within a
    poll, with no reflash. This is the whole point of the firmware.
13. Reboot with Home Assistant stopped. The device must keep its token, draw
    its last known arrangement from flash, and recover on its own when Home
    Assistant returns.
14. Delete the panel in Home Assistant. The device must return to a pairing
    code by itself, keep its Wi-Fi, and be pairable again without a cable.
    Confirm the panel's Home Assistant user and token are gone.
15. The screen switch, brightness number, page selector and restart button on
    the panel device all work, and the restart does **not** repeat on the next
    boot.
16. Watch `Media Controller Heap Free`, `Heap Min Free`, `Free PSRAM` and
    `Loop Time` under the poll load. Two blocking requests a second in the
    steady state is the cost, plus one more every five seconds for the room
    states. `Loop Time` is the number to watch: an `http_request` on ESP-IDF
    blocks the main loop, so this is the change most likely to show up as a
    stutter. Watch it again while a full grid is rebuilt — 64 cards is about
    190 LVGL objects created at once — and while the editor is open. If it
    stutters, raise **Update interval** on the panel device; Home Assistant
    owns it and no reflash is needed.
17. Confirm the panel does **not** appear in the ESPHome integration. Check
    **Settings → Devices & services** for a discovered ESPHome device while
    the panel is on the network, and check ESPHome Device Builder for an
    adoptable one. Dump the panel's mDNS records as well — `avahi-browse -art`
    or `dns-sd -B _services._dns-sd._udp` — and confirm `_media-controller._tcp`
    is there and `_esphomelib._tcp` is not.
