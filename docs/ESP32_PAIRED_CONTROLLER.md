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
| Home layout | *Screen Style* on the ESPHome device | also *Player skin* on the panel entry, which writes to it |
| Screen and page control from Home Assistant | no | yes |
| Interface | [`media-controller-ui.yaml`](../firmware/media-controller-ui.yaml) | the same file |

The honest trade is latency. The classic firmware is told about a change; this
one asks. Volume and the track position step rather than glide, exactly as they
do on the tablet.

Nothing about the classic firmware changed, and an already flashed device needs
no attention.

## Validation status

`esphome config` and a full ESPHome 2026.8.0 compile pass — 38.7% RAM, 22.9%
flash, against the classic firmware's 38.0% and 21.9%. The difference is the
room grid: the external component, its gzipped editor page, ArduinoJson, the
HTTP server, and four more image assets. **This firmware has not yet run on the
physical device.** Work through the
[hardware checklist](#hardware-verification) before treating it as done. Three
things cannot be judged from a build: the one-second poll and its effect on
`Loop Time`, the cost of building a full grid of 64 cards in one go, and
whether a 60 px card is legible and hittable in the hand.

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
   *ESP32-S3 panel* card; if it does not appear, add **Media Controller** by
   hand and choose that device type.

   If this is the first device in a fresh installation and no media player
   source exists yet, step 4 asks for the Music Assistant player and creates
   one for you.
3. Type the six digits from the screen.
4. Choose which media player source it plays from, then fill the four room
   slots. Any of them may be a light or a switch. Leave one empty to hide its
   tile.
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
| *Accepted — finish the setup form* | The code was right. The token follows once you finish choosing the source and the room slots. |
| *Home Assistant returned an error* | `ha_url` is wrong, or Home Assistant is unreachable. |

If the token is ever rejected — you removed the device in Home Assistant, or
revoked its user — the firmware notices the first refused request, forgets the
token and returns to a pairing code on its own.

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

Once a second it asks Home Assistant for the config sensor and the player. The
config sensor is what names all the others, which is why it is fetched every
cycle and not merely when a layout changes: it is also the channel Home
Assistant sends screen and page commands through.

Room states arrive inside the same config poll, in the `room_states` block
the integration renders beside the registry: one small array per element,
keyed by rid, refreshed with every poll. They used to come from a template
rendered by POST `/api/template`, one request for the whole page — but that
endpoint answers administrators only, and this device's token belongs to a
dedicated non-administrator user, so Home Assistant refused it with 401 and
every card stayed blank. A lamp somebody switched elsewhere now catches up
with the next one-second poll; a lamp switched *here* does not wait, because
the card asks for a fresh read as soon as Home Assistant has had time to act.

The queue is fetched when the track title changes rather than on every tick,
because it is the one large payload. Playlists have an interval of their own.
Both intervals are owned by Home Assistant and arrive with the rest.

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
Assistant raises a repair issue naming it and telling you to install it again
from ESPHome Device Builder — its `packages:` block re-downloads the
maintained firmware, so nothing in your own configuration changes. If Home
Assistant is the older one, the device says so in its ESPHome log instead:

```text
[W][config]: Home Assistant speaks contract 5 and this firmware needs 6:
update Media Controller
```

The number is `contract_version` in the substitutions block. It is not a knob
to turn per device: it says what this firmware understands, and changing it
only makes the device lie about itself.

Two contract features are deliberately not wired up:

- **`screen_off_seconds`.** The device already owns a *Screen Timeout* number on
  its ESPHome device, and its range (5–120 s) is narrower than the contract's.
  Two owners for one setting is a bug waiting to happen, so `number.<panel>_screen_off`
  does nothing here — use *Screen Timeout*.
- **Battery.** It is mains powered, so the package does not report a battery
  value. This is optional in the contract.

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

### Why only this firmware has a grid

The classic firmware never gets one, and this is a property of the variant
rather than a phase of work that has not happened yet.

ESPHome binds an entity ID at compile time in **both** directions: a
`homeassistant` sensor names the entity it reads, and a `homeassistant.service`
call names the entity it writes. A card that arrives at runtime carries an
entity ID that was not in the image, so a classic device could neither read its
state nor act on it. That is why the classic firmware has four numbered slots
backed by proxy entities: a proxy is a compile-time name that Home Assistant can
repoint behind it, and it is the only way that build can follow a change made in
the Home Assistant UI.

This firmware resolves both at runtime — it holds a token and calls the REST
API — so a card it was never flashed with works. The classic firmware keeps its
four fixed buttons and its `slots` payload, unchanged and un-deprecated.

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
    code by itself.
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
17. A classic device on the same Home Assistant keeps working throughout: its
    four buttons, its heading, its hint and its `slots` payload are untouched.
