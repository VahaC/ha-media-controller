# Home Assistant integration

`custom_components/media_controller` is the server side of this project. Both
clients — the [ESP32-S3 controller](ESP32_CONTROLLER.md), the same board on the
[paired firmware](ESP32_PAIRED_CONTROLLER.md), and the
[T560 panel](../clients/t560/README.md) — read the entities it publishes and
call the services it registers. Nothing else in this repository works without
it.

The exact entity and service surface is specified in [CONTRACT.md](CONTRACT.md).

## Two kinds of thing

The integration adds two kinds of entry, and telling them apart is most of
knowing how to set it up:

| | **Media player source** | **Panel** |
| --- | --- | --- |
| What it is | One Music Assistant player, wrapped so panels can read it | One piece of hardware with a screen |
| Where Home Assistant lists it | Under **Services**: it has no hardware of its own | Under **Devices** |
| How many | One per player | Any number, each reading one source |
| Added by | Choosing the player | The device announcing itself, then a six-digit code |

A panel plays from a source, so a source exists first. Home Assistant does not
offer the choice while there is none: adding the integration asks for the
player straight away, and a panel that pairs before any source exists offers to
build one on the spot.

Both ESP32 firmwares also speak the ESPHome API, so an ESP32 appears twice in
Home Assistant on purpose: once as its ESPHome device — logs, OTA, diagnostics
— and once here, as a panel. The two are separate integrations and neither
replaces the other.

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
6. Select the required Music Assistant player. That is the whole form: a media
   player source is the player and nothing else.

Panels are added afterwards, and normally add themselves.

An ESP32 running the **classic** firmware needs one more step, and only that
device does: open *Configure* on the source and pick **Room controls
(classic-firmware ESP32 only)**. The form states the limit — four slots, 1
and 2 lights, 3 and 4 switches — and an empty slot hides that tile. Do this
*before* flashing: the YAML is filled in with the entity IDs of the proxies
this form creates. Every other client carries its room controls on its own
panel entry, and this item in the menu can be ignored.

The integration creates:

- a bounded queue sensor;
- a playlists sensor;
- a config sensor per client, carrying its room-control layout;
- one proxy entity per configured slot of a classic-firmware ESP32.

The proxy entities make room mappings changeable through Options Flow without
reflashing the ESP32. A proxy whose source is unavailable is itself
unavailable; the other controller functions continue working. Clearing a slot
removes its proxy.

**Panels have no proxies.** They read entity IDs at runtime, so they are
handed the real entity and call its own services. See
[Room entities](#room-entities) below.

### Panels

A panel is any client that is paired rather than configured by hand. Two kinds
exist: a tablet running the T560 application, and an ESP32 running the
[paired firmware](ESP32_PAIRED_CONTROLLER.md). They behave identically here —
the device type is chosen from a list, and everything after that is the same
form — so *the panel* below means either.

A panel **announces itself on the local network**. Home Assistant shows it as a
discovered device: press *Configure* and the form asks, in this order:

1. **the six-digit code the panel is showing.** Home Assistant then waits for
   the panel to answer with the same code, which is the only part of the setup
   that can fail on its own: the device may be off, on another network, or
   showing a code from an earlier attempt. Nothing is stored and nothing else
   is asked until it has answered, and a wrong code can simply be retyped.
2. **which media player source it plays from**;
3. **its room entities**, on one page: a list per group — Weather, Lights,
   Switches, Media players, Climate devices, Covers — that it can add to and
   remove from freely.

Finishing the form is what releases the access token: the panel collects it on
its next poll, a few seconds later, and switches into normal operation. Nothing
is typed on the panel, and nothing but the token is configured there.

Step 2 has nothing to offer in an installation with no source yet, so it asks
for the Music Assistant player instead and creates one. Adding the first panel
is therefore still one sitting: the code, then what it plays from, then its
room entities.

A panel that cannot announce itself is added with *Add device* → *Panel*, where
the panel ID has to match the one the device uses. A tablet derives that ID from
its own hardware on first run and writes it to
`~/.config/t560-music-panel/panel-id`; a paired ESP32 uses its MAC address,
without separators, which its log prints at boot. Either way two devices never
claim the same Home Assistant device.

Each panel is its own config entry and its own Home Assistant device, with its
own config sensor, linked to the source it reads. *Configure* on a panel device
opens one page carrying the source choice and every room-entity list, so
moving a panel to another Music Assistant player is a remapping like any
other: the device keeps its token, its device, and its entity IDs.

### Room entities

A panel's room controls are a list with no fixed length. *Configure* shows
all six groups on one page — Weather, Lights, Switches, Media players, Climate
devices, Covers — each a selector holding everything in it: adding an entity
to one adds a tile, clearing one removes it, and there is no numbered slot to
run out of. One *Submit* saves the lot. A label may be typed for each entity
below the groups; leave it empty and the entity's own name is used.

Only the ceiling comes from the device type: 100 entities for a
tablet, 64 for a paired ESP32. Only the tablet offers colour temperature.

Lights, switches and climate have cards on both panels. A thermostat is
toggled with a tap and its setpoint is moved on the tablet's adjust sheet or
by a long press on the ESP32; both panels show what the room is at and what it
is set to. Media players, covers and weather can be added now, but no client
draws a card for them yet and they are ignored until one does — each becomes a
card in a contract version of its own, so a panel gains one when it is
updated and never breaks on a payload that carries one it does not know. See
[ROOM_SLOTS.md](ROOM_SLOTS.md).

The room controls of an ESP32 running the **classic** firmware are the exception
to all of this. They are still four numbered slots, they live on the source
entry itself, behind *Configure* → *Room controls (classic-firmware ESP32
only)*, and they are backed by proxy entities, because that firmware resolves
both the entity ID and the service domain at compile time.

### Panel settings, battery, and display

A panel device carries entities that describe the device rather than the room.
They exist so that nothing on a wall-mounted panel has to be reached over SSH.

| Entity | What it does | Paired ESP32 |
| --- | --- | --- |
| **Update interval** | How often the panel asks for player and room state. | yes |
| **Library refresh interval** | How often it refreshes playlists. | yes |
| **Screen timeout** | Inactivity before the display turns off; 0 never. | no — use its own *Screen Timeout* |
| **Screen brightness** | Backlight level. | yes |
| **Screen** | Backlight on or off, and what it currently is. | yes |
| **Page** | Which page the panel shows, and sending it to another. | yes |
| **Player skin** | Which of its layouts the panel draws. | yes, its three home layouts |
| **Restart panel app** | Restarts the application on the panel. | yes, reboots the device |
| **Battery**, **Charging** | What the device reports about its power. | no — mains powered |
| **Connected** | Whether the device is reporting at all. | yes |
| **Uptime** | When the panel application last started. | yes |
| **Last report** | When the device was last heard from. | yes |
| **Wi-Fi signal**, **Temperature** | Diagnostics from the device. | no |

A panel reports only what it has, and Home Assistant leaves the rest unknown.
An ESP32 has no battery to report, and its screen timeout is owned by a *Screen
Timeout* number on its own ESPHome device instead — its range is narrower than
the contract's, and two owners for one setting is a bug waiting to happen.

The settings and the two intervals are stored in Home Assistant and are
applied by the tablet within one poll cycle, without restarting it. They keep
their value while the tablet is off, and the same keys in `config.ini` on the
tablet are only the fallback used before it has ever reached Home Assistant.

Nothing can be pushed to a tablet, so *Screen* and *Restart panel app* are
requests the panel reads on its next poll — normally within a second — and
*Screen* shows what was asked for until the tablet confirms what its display
actually did. **Battery**, **Charging**, and the backlight level are pushed the
other way: the panel reports them on a change and at least once a minute, and
every entity that depends on a report goes unavailable when none has arrived
for three minutes. The tablet's application version appears as the device's
software version.

A panel that serves a layout editor of its own reports where it answers, and
Home Assistant turns that into the **Visit** link on the panel's device page:
the tablet's editor is then reached from the device page rather than from an
address and a port somebody has to remember. The link appears with the first
report after the panel starts, and disappears again if the editor is switched
off on the tablet.

**Screen brightness** is the one control the tablet can refuse. Writing the
kernel's backlight device needs a permission the session user does not have by
default, and the control stays unavailable where it is missing. Turning the
display on and off works regardless: that goes through DPMS.

**Page** works both ways, like *Screen*: it shows the page a person navigated
to on the tablet, and setting it sends the panel there. That is what makes a
panel addressable from an automation — a doorbell can put the room page in
front of whoever walks past.

**Player skin** chooses which of its layouts a panel draws, and its options are
that panel's own:

- On a **T560** — *Modern*, the default dark interface, or *Cassette*, the
  faceplate of a cassette deck with the album art as the tape label and the
  playback position as the tape moving from one reel to the other. A skin there
  is the whole interface: the navigation bar and the room controls follow it.
- On a **paired ESP32** — *Classic*, *Minimal Ring* or *Cover Card*, the three
  home layouts the firmware already draws.

It is a setting rather than a request, so it is applied on the next poll,
within a second, and restarts nothing.

The paired ESP32 keeps its *Screen Style* select on its own ESPHome device.
That select is still where the value lives and what it restores from after a
reboot, exactly as `config.ini` is the tablet's fallback; this entity writes to
it. So the two agree rather than compete, and the layout is reachable from the
panel device without having to go and find the ESPHome one. Until someone
chooses here, the device keeps whatever it restored — Home Assistant sends no
skin at all rather than sending its own idea of a default.

**Uptime** is the moment the application started rather than a duration, so it
sits still while the application does and moves when the watchdog restarts it.
**Last report** is when the tablet was last heard from; together with
**Connected** it is how a tablet that quietly fell off the Wi-Fi is spotted.
**Wi-Fi signal** and **Temperature** are unavailable on hardware that exposes
neither.

### Dimming the panel at night

Nothing here is a night mode: the screen timeout and the backlight are
ordinary entities, so an automation does it. Two automations, one each way:

```yaml
automation:
  - alias: Panel dims for the night
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.hallway_panel_screen_brightness
        data:
          value: 15
      - action: number.set_value
        target:
          entity_id: number.hallway_panel_screen_timeout
        data:
          value: 15

  - alias: Panel returns to daytime
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.hallway_panel_screen_brightness
        data:
          value: 100
      - action: number.set_value
        target:
          entity_id: number.hallway_panel_screen_timeout
        data:
          value: 60
```

Substitute the entity IDs Home Assistant gave your panel. Brightness needs the
backlight permission described above; the timeout alone already helps, and a
timeout of `0` at the other end keeps the panel lit all day. A panel that was
asleep when the automation ran picks the values up on its next poll, because
these are settings rather than commands.

### Capabilities

The integration reads what the entity behind a slot or a room entity actually
supports and publishes a plain control list — `toggle`, `brightness`,
`color_temp` — in the config sensor. Clients draw from that list and never
inspect `supported_color_modes` themselves. The list is also limited by what
the client can draw: a colour-temperature lamp in an ESP32 slot is toggled and
dimmed, and offers its full control set on the T560.

That is true of a panel's room entities as well, and it is what makes it safe
for a panel to address the real entity rather than a proxy: the client still
renders a plain list, and still works out nothing for itself.

Entity IDs are assigned by Home Assistant's entity registry. Open the new
controller device and copy its actual entity IDs for the firmware substitutions.
Do not assume the example IDs are the IDs Home Assistant chose.

The integration listens to the Music Assistant player selected in Config Flow.
The ESPHome device also uses its `player_entity` substitution for native media
state and control actions. If the selected player is changed later in Options
Flow, update that substitution during the next ESPHome/OTA update as well.

Changing which entity a slot points at needs no reflash: the ESP32 is bound to
the slot proxy, and it reads the button labels and which buttons to show from
the config sensor on every connection.

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


The T560 panel reads the same queue and playlists sensors and the proxy
entities of its own panel entry over the Home Assistant REST API. It reads its
own config sensor on every poll cycle, because that sensor is also how a
request to turn the display off or to restart reaches it.

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
