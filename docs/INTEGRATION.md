# Home Assistant integration

`custom_components/media_controller` is the server side of this project. Both
panels — the [ESP32-S3 panel](ESP32_PAIRED_CONTROLLER.md) and the
[T560 panel](../clients/t560/README.md) — read the entities it publishes and
call the services it registers. Nothing else in this repository works without
it.

Since contract version 9 it is also the **only** integration involved. An
ESP32 panel no longer speaks the ESPHome native API, so it never appears in
the ESPHome integration and contributes no entity through it; everything a
user sees comes from here.

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

A source has nothing else to configure. Its *Configure* asks the same one
question, so that a source can be moved to another player without being
deleted.

The integration creates, for a source:

- a bounded queue sensor;
- a playlists sensor;
- a config sensor.

And for each panel: a config sensor of its own, its readings, its settings,
and — where its device type has them — its theme and its diagnostics. See
[Panel settings, battery, and display](#panel-settings-battery-and-display) and the two sections after it.

**There are no proxy entities.** Every client reads entity IDs at runtime, so
it is handed the real entity and calls its own services. A source had four
proxies until contract version 9, for the classic ESP32 firmware that was
removed in the same version; the entry migration deletes them. See
[Room entities](#room-entities) below.

### Panels

A panel is any client that is paired rather than configured by hand. Two kinds
exist: a tablet running the T560 application, and an ESP32 running the
[paired firmware](ESP32_PAIRED_CONTROLLER.md). They behave identically here —
the same form, and the device type either announced or picked from a list — so
*the panel* below means either.

A panel **arrives by itself**, either by announcing itself over mDNS or by
polling for a token it does not have yet. Home Assistant shows it as a
discovered device: press *Configure* and the form asks, in this order:

1. **the six-digit code the panel is showing.** This is the only part of the
   setup that can fail on its own: the device may be off, on another network,
   or showing a code from an earlier attempt. Nothing is stored and nothing
   else is asked until the code is settled, and a wrong code can simply be
   retyped.
2. **which media player source it plays from**;
3. **its room entities**, on one page: a list per group — Weather, Lights,
   Switches, Climate devices, Covers — that it can add to and remove from
   freely.
4. **where Home Assistant is**, but only in the installation that has no
   internal URL configured and only for a panel Home Assistant has to reach
   directly. Setting one under *Settings → System → Network* removes this step
   for good.

Finishing the form is what releases the access token, and it travels one of two
ways depending on the panel. Either way nothing is typed on the panel, and
nothing but the token is configured there.

**A panel Home Assistant can reach** — the ESP32 firmware, which serves a small
web server anyway — is asked directly whether the typed code is the one on its
screen, before anything at all is created. Home Assistant then posts the token,
its own address and the panel's config sensor to the device once the entry
exists. This is the only way a panel installed from the web installer can be
set up: it was never told where Home Assistant is, so it has nowhere to ask.

**A panel that serves nothing** — the T560 tablet — collects the token on its
next poll, a few seconds later, and switches into normal operation.

Which one it is comes from the panel's own discovery record and needs no
setting; see **Discovery and pairing** in [CONTRACT.md](CONTRACT.md).

A mistyped code costs nothing in either case: no token is minted until the
panel has agreed. If a token is minted and then cannot be delivered — the
panel went off the network while the form was open — Home Assistant revokes it
rather than leaving an unused credential and its user behind, and asks for a
code again.

Step 2 has nothing to offer in an installation with no source yet, so it asks
for the Music Assistant player instead and creates one. Adding the first panel
is therefore still one sitting: the code, then what it plays from, then its
room entities.

A new ESP32-S3 panel is installed from
<https://vahac.github.io/ha-media-controller/> — a browser, a USB cable, and no
ESPHome. It joins the network from that page and then appears here by itself.
See [ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md).

That address is in Home Assistant too, where somebody holding a new board goes
looking for it: *Add device* → **Install firmware on a new ESP32-S3 panel**. It
configures nothing and stores nothing — the step carries the link and the three
steps that follow it. The address itself lives in one place in the code,
`INSTALLER_URL` in `const.py`, because Home Assistant does not allow a literal
URL inside a translation.

**No form asks for a panel ID.** A panel that cannot announce itself over mDNS
still has to poll `/api/media_controller/provision` before it can hold a token,
and that poll carries its identifier, so Home Assistant offers it as a
discovered device from the poll itself — see `_async_offer` in `provision.py`.
A panel offered this way is always the polling kind: nothing is known about
where it is, so Home Assistant waits to be asked. It is offered again every
five minutes while it stays unadded, which is what makes a dismissed card
recoverable without a restart.

The identifier itself is the device's, never a person's to know: a tablet
derives it from its own hardware on first run and writes it to
`~/.config/t560-music-panel/panel-id`, and a paired ESP32 uses its MAC address
without separators — a value it never displays, which is why asking for it was
never a question anybody could answer. The mDNS record carries two things the
poll does not, the kind of panel and its name, so the pairing form asks for
those two when the panel arrived by polling. The kind is defaulted from the
identifier by `profile_from_panel_id`, and the name from the kind.

Each panel is its own config entry and its own Home Assistant device, with its
own config sensor, linked to the source it reads. *Configure* on a panel device
opens one page carrying the source choice and every room-entity list, so
moving a panel to another Music Assistant player is a remapping like any
other: the device keeps its token, its device, and its entity IDs.

### Room entities

A panel's room controls are a list with no fixed length. *Configure* shows
every group on one page — Weather, Sensors, Lights, Switches, Climate
devices, Covers — each a selector holding everything in it: adding an entity
to one adds a tile, clearing one removes it, and there is no numbered slot to
run out of. One *Submit* saves the lot. A tile is named as Home Assistant
names the entity, until somebody names it otherwise in the panel's own layout
editor — see **Card names and icons** below.

There is no group for media players: a panel plays from the source chosen at
the top of the same page, and that is the player it draws.

Only the ceiling comes from the device type: 100 entities for a
tablet, 64 for an ESP32 panel. Only the tablet offers colour temperature.

Lights, switches and climate have cards on both panels. A thermostat is
toggled with a tap and its setpoint is moved on the tablet's adjust sheet or
by a long press on the ESP32; both panels show what the room is at and what it
is set to.

Covers are part of contract version 7 and have a card on the **tablet**. A tap
opens or closes the blind, and its ADJUST corner carries how far open it is as
a percentage — where the cover reports one — and a STOP button, which is what
a blind that takes ten seconds to travel actually needs. The paired ESP32 has
no cover card yet and ignores those elements, as the contract permits.

Weather is drawn as a reading block on both panels: the condition and the
temperature, with the humidity where it is reported. A tap on it acts on
nothing.

Sensors are drawn as a reading block on both panels: the name and the value
with its unit — `21.5 °C` — the bare value where the entity reports no unit.
A tap on it acts on nothing. See [ROOM_SLOTS.md](ROOM_SLOTS.md).

There is no exception to any of this any more. Until contract version 9 there
was one: an ESP32 on the classic firmware had four numbered slots, stored on
the source entry and backed by proxy entities, because that firmware resolved
both the entity ID and the service domain while compiling. It also reached
Home Assistant over the ESPHome native API, which is the dependency version 9
removed, so both went together. Upgrading deletes the stored slots and the
proxies; choose the same entities again on the panel.

### The appearance of an ESP32 panel

An ESP32 panel carries twelve more configuration entities: eight
`text.<panel>_color_*` holding `#RRGGBB`, and four
`number.<panel>_opacity_*` holding 0 - 255. They colour the player page, and
setting one restyles all three of the panel's home layouts at once.

They are new in contract version 9 and they are not new functionality: they
are exactly the twelve values that used to be ESPHome entities on the panel's
*ESPHome* device. Removing the ESPHome native API would have taken the only
way to restyle the player with it, so they moved into the contract instead.
The panel keeps what it applied in its own flash, so it comes back looking the
same after a reboot with Home Assistant down.

The T560 panel has none of them: its two skins carry their own palettes, so
there is nothing to apply a progress-ring colour to.

### What an ESP32 panel reports about itself

Seven more diagnostic sensors, again moved rather than added:
`heap_free`, `heap_max_block`, `heap_min_free`, `heap_fragmentation`,
`psram_free`, `loop_time` and `reset_reason`. They ride the status report the
panel already sends, so they cost no extra request, and they are what makes a
panel that reboots at three in the morning diagnosable without a serial cable.

`loop_time` is the longest **single** main-loop iteration in the last
interval, not an average: that is the number a stutter shows up in.

`reset_reason` is a phrase rather than a measurement, and it changes once per
reboot. If your recorder keeps long history it is worth excluding — the
integration cannot do that for you, because a whole entity is excluded from
the recorder only in the recorder's own configuration:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.*_reset_reason
```

Everything the config sensors carry is already excluded from the recorder by
the integration: the queue payload alone would be written on every track
change, and a panel's room states move every time anything in the house is
switched.

A client that does not report a block gets none of the entities that read it,
rather than a row of sensors that are unavailable for the life of the
installation. That is why a T560 panel has neither set.

### Card names and icons

Two things about a card are not chosen here and not chosen on the device
either: they are stored in Home Assistant, against the registry element, and
edited in the small layout editor each panel serves on itself. That is what
makes a house with a tablet and an ESP32 panel agree about what a lamp is
called and what it looks like without either of them telling the other, and
what makes a panel that is wiped or replaced get both back with its registry.

**A display name** is what the tile says. Leave it empty — the *Auto* button
beside the field clears it — and the tile is named as Home Assistant names the
entity, which is what every tile did before names could be set and what a tile
goes on doing through a rename. Type something and that is what the tile says
instead. It may be up to 64 characters of any script, and it **never renames
the Home Assistant entity**: `light.desk_lamp` keeps its own name, its own
entity ID and its own registry row.

**An icon** comes from a catalog this integration publishes, at
`/api/media_controller/icons`, with the pictures themselves at
`/api/media_controller/icon/<id>/<variant>`. Both are authenticated with the
panel's own token and neither is ever handed to a browser: the editor page a
panel serves asks *its own device* for pictures, and the device answers out of
what it has already downloaded.

The catalog is the reason for the arrangement. A card used to store a number —
an index into an array of six pictures compiled into the ESP32 firmware — so
the set could grow only by reflashing every device in the house, and
reordering the array would have silently moved everybody's icons. A card now
stores a stable identifier, and adding a picture is:

1. drop a 128 x 128 PNG with an alpha channel into
   `custom_components/media_controller/icons/`;
2. add a row to `ICONS` in
   `custom_components/media_controller/icon_catalog.py`;
3. run `python tools/make-icon-assets.py`, which renders the variant the ESP32
   draws — 40 x 40, in the exact bytes LVGL blits, because that firmware
   cannot scale an image at draw time;
4. bump `version` in `manifest.json`, as any change under
   `custom_components/**` requires.

No client is rebuilt and no device is reflashed. Panels notice within six
hours, or at once after a restart, because the catalog carries a `revision`
they compare. **Automatic** is always offered and means *let the domain
decide*, which is what every card does until somebody says otherwise.

A picture a client cannot get — an unreachable Home Assistant, a failed
download, an identifier this build has never heard of — is never fatal. The
card falls back to artwork the client carries itself, and the room page draws,
navigates and responds exactly as it did.

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
| **Screen rotation** | Display and touch orientation in clockwise degrees. | yes, all quarter turns |
| **Restart panel app** | Restarts the application on the panel. | yes, reboots the device |
| **Battery**, **Charging** | What the device reports about its power. | no — mains powered |
| **Connected** | Whether the device is reporting at all. | yes |
| **Uptime** | When the panel application last started. | yes |
| **Last report** | When the device was last heard from. | yes |
| **Wi-Fi signal**, **Temperature** | Diagnostics from the device. | no |
| **Firmware** | The build the panel is on, and the one it could be on. | yes — the T560 has none |

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

**Screen rotation** follows the same stored-settings path. A T560 offers 0°
and 180°; a paired ESP32 offers 0°, 90°, 180° and 270°. The display and touch
coordinates change together. Until a value is selected, the client keeps its
existing orientation.

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

The integration reads what the entity behind a room element actually
supports and publishes a plain control list — `toggle`, `brightness`,
`color_temp` — in the config sensor. Clients draw from that list and never
inspect `supported_color_modes` themselves. The list is also limited by what
the client can draw: a colour-temperature lamp is toggled and dimmed on an
ESP32 panel, and offers its full control set on the T560.

That is what makes it safe for a client to address the real entity with no
proxy in between: it renders a plain list, and works out nothing for itself.

Entity IDs are assigned by Home Assistant's entity registry, and no client has
to be told any of them: a panel is handed the three it needs — the player, the
queue sensor and the playlists sensor — in its own config sensor, so a URL, a
token and its panel ID are the whole of what it bootstraps from.

Changing which entity a card points at, or moving a source to another Music
Assistant player, therefore needs no reinstall on any client. The change is in
the next payload each of them polls.

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


The T560 panel reads the same queue and playlists sensors over the Home
Assistant REST API, and the room entities of its own registry directly. It
reads its own config sensor on every poll cycle, because that sensor is also
how a request to turn the display off or to restart reaches it.

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

### Updating a paired ESP32 panel

A paired ESP32 panel has a **Firmware** entity and appears under **Settings →
Updates**. Pressing Install downloads the released image *in Home Assistant*,
checks it against the SHA-256 the installer site publishes, and then tells the
panel over its own authenticated channel that a version is waiting. The panel
fetches it from Home Assistant over the local network — it never talks to the
internet — and keeps its Wi-Fi, its pairing, its token and its room layout,
because an update writes the application partition and nothing else.

Three things about that entity are worth knowing, because each of them looks
like a bug from the outside:

- **it can show a newer build on the installer page and offer nothing.** A
  firmware built against a newer client contract than this integration speaks
  would install and then ignore half of what it is sent, so it is held back
  until the integration is upgraded first. The entity says so in its
  `held_back_version` attribute;
- **a panel on firmware 0.5.0 is never offered one.** That build has no update
  client in it at all, so there is nothing to tell — it has to be moved
  forward once over USB from the installer page, and the repair issue says so.
  After that one install it never needs a cable again;
- **an installation with no route to the internet is offered nothing**, and
  the entity reports its version as unknown rather than up to date. Home
  Assistant is the thing that downloads the image, so a Home Assistant that
  cannot reach the release genuinely has no update to give.

The **T560 tablet has no Firmware entity**: it is deployed over SSH, and a
button that could not install anything would be worse than none. It keeps the
repair issue that names it when it is behind.

The update procedure, the rollback, and the USB recovery path are in
[ESP32_PAIRED_CONTROLLER.md](ESP32_PAIRED_CONTROLLER.md) under *Updating*; the
protocol is **Panel firmware endpoint** in [CONTRACT.md](CONTRACT.md).

Read [CONTRACT.md](CONTRACT.md) before changing the payload shape of the queue
or playlists sensors, the config sensor, the status report, or a service
signature. Those changes reach both clients.

## Development

Pure transformation tests use the standard library:

```text
python -m unittest discover -s tests -v
```

`tests/` at the repository root belongs to the integration. The T560 panel has
its own tests under `clients/t560/tests/`.
