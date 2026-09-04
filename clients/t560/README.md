# T560 Music Panel

A native touch-only controller for the Samsung Galaxy Tab E SM-T560
(`gtelwifi`, ARMv7) running postmarketOS and Openbox. It follows the interaction
model of the ESP32 controller that lives in [firmware/](../../firmware), but
runs as a lightweight GTK3 application on the tablet.

It is one of the two clients of the Media Controller integration in this
repository; the other is the [ESP32-S3 controller](../../docs/ESP32_CONTROLLER.md).
Both read the same [contract](../../docs/CONTRACT.md).

The application does not use WebKit, a browser, HTML/JavaScript, text fields,
or an on-screen keyboard. Nothing is configured on the tablet: the room
controls, the poll intervals, the screen timeout, the backlight, and a restart
of the application are all reached from Home Assistant, and the only file that
is ever written by hand is an optional set of fallbacks.

## Implemented features

- Native dark UI designed for the 800x1219 usable screen area.
- Two skins, chosen from Home Assistant without reflashing or restarting anything. **Modern** is the default; **Cassette** is the faceplate of an early-1980s cassette deck, with the album art as the tape label, the playback position as the tape moving from one reel to the other, and reels that turn while the track plays. A skin is the whole interface: the navigation bar and the room controls follow it.
- The window runs fullscreen and covers the whole display, without
  decorations or window manager panels above it.
- A header row with the page title, a centered clock showing the time and
  the date, a Home Assistant link icon, and an upright battery indicator
  with the charge percentage.
- The battery indicator turns green and shows a bolt while the tablet is
  charging, and amber or red as the charge drops.
- The link icon reports only whether Home Assistant answers. It is teal and
  whole while every configured entity is read, amber and whole when Home
  Assistant replies but rejects a request, and red and broken only when the
  server cannot be reached at all. An entity that Home Assistant no longer
  has is therefore reported as amber, never as a lost connection. Hold the icon to
  read a tooltip naming the entity that Home Assistant rejected.
- Album art, track title, artist, playback progress, and volume.
- Previous, Play/Pause, Next, Volume Down, and Volume Up controls.
- Shuffle and Repeat Off/All/One controls.
- Queue browsing and playback of a selected queue item without replacing the queue.
- Playlist browsing and playback through `music_assistant.play_media`.
- A room page that is a **10 x 14 grid of cards the user arranges**, not a
  fixed number of tiles. A card carries a position and a size in cells, and
  the cell size is derived from whatever work area the page is given, so the
  bottom row is never cut off. Which entities exist comes from Home Assistant
  and where each one sits comes from the tablet; the two are separate on
  purpose.
- Which entities a panel may draw is the registry the Media Controller
  integration publishes: up to a hundred of them, with the name and the
  controls each one offers resolved there. Nothing about them is configured on
  the tablet.
- The panel is usable the moment it is configured in Home Assistant, without
  visiting the editor: with no saved arrangement it places every registry
  element as a 2 x 2 card, in registry order.
- A card whose registry element has been removed in Home Assistant keeps its
  place and says it is unassigned, rather than disappearing and taking the
  arrangement with it.
- Brightness, colour-temperature and thermostat-setpoint controls appear on a
  card only when the entity behind it actually supports them, as reported by
  the integration. On a card too small for the ADJUST button, the same corner
  is still the same target and is drawn as a compact slider glyph.
- **Thermostat cards**, since contract version 7. A tap turns the thermostat
  off and on, the ADJUST corner opens the setpoint on the same sheet a light's
  brightness uses, and a card of two cells or more says what the room is at
  and what it is set to — `21.5° / 22°` — instead of ON or OFF, which is not
  what anybody came to a thermostat for. A thermostat that is off shows the
  room temperature alone: that number is true either way, and the setpoint it
  used to be heading for is not. Temperatures carry no unit letter:
  the integration sends whatever the entity reports, in whatever unit Home
  Assistant is configured in, and the card draws the number and a degree sign.
  A thermostat costs no extra polling: the two numbers are attributes of the
  state document the card is already polled with.
- **Sensor blocks**. A sensor card is a reading, not a button: it shows the
  name and the value with its unit — `21.5 °C` — the bare value where the
  entity reports no unit. A tap on it acts on nothing. A sensor costs no
  extra polling: the value is the state itself and the unit is an attribute
  of the state document the card is already polled with.
- **A layout editor the panel serves itself**, on port 8730 by default, so
  the grid is arranged from a phone or a desktop rather than on a tablet with
  no keyboard. It has no password; see [The layout
  editor](#the-layout-editor) below for what that does and does not allow.
- Every save leaves a copy of the arrangement in Home Assistant, and the
  editor can put that copy back. A tablet that is wiped, reinstalled or
  replaced finds its own layout again.
- Direct Home Assistant REST API access without loading Lovelace.
- A separate token file with `0600` permissions.
- Watchdog, desktop entry, Openbox rule, and ARMv7 `APKBUILD`.
- A dedicated launcher icon installed into the `hicolor` icon theme, so the
  desktop launcher and the task bar show the panel icon. The icon is
  regenerated from geometry by `tools/make-app-icon.py`.
- A short Power press turns the display off; any key or touchscreen input wakes it.
- The tap that wakes the display only wakes it: the button handler holds a
  pointer grab while the display is off, so no control is pressed by mistake.
- The display turns off automatically after an inactivity timeout, set in
  Home Assistant and 30 seconds by default. Zero keeps the display on until
  the Power button is pressed.
- The poll interval, the playlist refresh interval, and that timeout are
  number entities on the panel's Home Assistant device. A change is applied
  within a poll cycle and restarts nothing.
- The backlight is a switch in Home Assistant, and its level a slider where
  the tablet grants write access to the kernel backlight. Pressing the Power
  button on the tablet is visible there, and the other way round.
- A button in Home Assistant restarts the panel application; the watchdog
  brings it back within about two seconds.
- The skin is a select on the panel's Home Assistant device, applied within a poll cycle.
- Which page the panel is on is visible in Home Assistant as a select, and
  setting it sends the panel to that page. Pressing a navigation button on
  the tablet updates it within a second.
- Battery charge and charger state are reported to Home Assistant on a change
  and at least once a minute, as a battery sensor and a charging sensor on the
  panel device, alongside a connectivity sensor that says whether the tablet
  is reporting at all.
- The same report carries how long the application has been running, the
  Wi-Fi signal read from `/proc/net/wireless`, and the tablet temperature read
  from `/sys/class/thermal`. All three are diagnostic sensors, and each is
  unavailable where the tablet has nothing to read.
- Camera motion detection: movement turns the display on while it is off, and
  postpones the automatic screen off while it continues. It is off by default
  because the built-in camera of this tablet cannot stream to userspace; see
  [CAMERA.md](docs/CAMERA.md).
- Camera analysis runs in a separate low-priority daemon, never in the panel
  process, and the panel keeps working when no camera node is usable.
- The physical Home button toggles between the panel and desktop while the
  display is on, and only wakes the display while it is off.
- The existing long-press Power menu is retained.

## The layout editor

The room page is arranged from a browser on the same network:

```text
http://<tablet address>:8730/
```

The panel prints the address to its log at start-up, an empty room page shows
it on screen, and the panel reports it to Home Assistant, which offers it as
the **Visit** link on the panel's device page.

The page is one screen: the grid on the left, and the registry grouped by
domain on the right. Pick an entity and tap a free cell to place it, drag a
card to move it, drag the corner to resize it, and use the panel above the
palette to change which entity a card acts on, its icon, its colour, or to
remove it. It is built for a phone as much as for a desktop.

The **Player skin** section lists the skins this build draws and shows a
picture of each one beside the list, because a name says nothing about a
layout. The pictures are static PNGs compiled into the binary, one per skin,
drawn by `tools/make-skin-previews.py` from the palettes in `panel_ui.c`; a
live preview would mean a second implementation of every skin, in JavaScript,
kept in step with the real one by hand. Choosing a skin — from the list or by
tapping its picture — asks Home Assistant, which stays the owner of that
value, and the panel adopts it on its next poll. The status line is what says
whether it actually did; the picture is a drawing, not evidence.

### It has no password, and that is deliberate

A tablet on a house network, serving one page that arranges its own room
controls, is not worth a login on a device with no keyboard. What makes that
defensible is what the server cannot do, and the eight routes are the whole of
it:

```text
GET    /               the editor page
GET    /skins/<n>.png  what one skin looks like
GET    /api/entities   the registry, out of the payload the panel already holds
GET    /api/layout     the arrangement on screen
PUT    /api/layout     save an arrangement
DELETE /api/layout     put back the copy Home Assistant holds
GET    /api/skins      the skins this build draws
PUT    /api/skin       ask Home Assistant for one of them
```

There is no general proxy to Home Assistant. Nothing here reads a state, calls
an arbitrary service, or reaches an entity the panel does not already draw;
the one route that takes a name from the caller — the skin preview — is
checked against the skins this build draws before it becomes a resource path,
so it cannot be used to read anything else out of the binary;
`/api/entities` is answered from the config payload the panel has cached and
never becomes a request to Home Assistant; `PUT /api/skin` calls
`select.select_option` on this panel's own skin select, with a name checked
against the skins this build draws, and nothing else. The panel's Home
Assistant token is not readable through any route.

The worst an unauthenticated caller on the network can do is rearrange the
room page of one tablet — and `DELETE /api/layout`, the **Restore** button in
the editor, undoes exactly that from the copy Home Assistant holds.

**Do not forward this port through a router.** It is meant for a house
network. Set `web_port=0` under `[panel]` in `config.ini` to switch the editor
off entirely.

### Where the arrangement lives

```text
~/.config/t560-music-panel/grid.json
```

Beside `config.ini` rather than in the cache: the cache is what Home Assistant
last said and is safe to lose, and this is the user's own arrangement and is
not. The format is small on purpose:

```json
{"v":1,"cols":10,"rows":14,
 "cards":[{"x":0,"y":0,"w":2,"h":2,"rid":"a3f1c92d",
           "icon":"lightbulb","color":"#4dd0e1"}]}
```

A card is keyed on `rid`, the identity of the registry element, never on an
entity ID: a Home Assistant entity ID is renamed by the user at will, and a
grid keyed on one would scatter the next time somebody tidied their entity
IDs. The card **type is not stored** — it follows from the domain of the
element behind the rid, so it cannot drift from what Home Assistant says.

A card that does not fit the grid, or that lands on a card already placed, is
dropped when the file is read rather than moved: where it should go instead is
a question only the person editing can answer. A card naming a rid the
registry does not carry is **kept**, because the registry is empty whenever
Home Assistant is unreachable and dropping cards against it would let one
failed poll erase an arrangement that the next save wrote back.

## Tablet configuration files

```text
~/.config/t560-music-panel/panel-id          (written on the first run)
~/.config/t560-music-panel/grid.json         (the room-page arrangement)
~/.config/t560-music-panel/token             (written when pairing succeeds)
~/.config/t560-music-panel/config.ini        (optional)
~/.cache/t560-music-panel/layout.json
~/.cache/t560-music-panel/discovered.ini
~/.cache/t560-music-panel/display-state.ini  (written by the button handler)
~/.cache/t560-music-panel/display-request.ini
```

**Only the `token` file is required.** `config.ini` is optional: Home
Assistant is found over mDNS, and the panel identifies itself by a
per-device ID derived from its hardware address on the first run. The file
exists to override one of those, or to hold the settings the motion detector
reads — the `[camera]` section.

The `[panel]` keys — `poll_interval_ms`, `playlist_poll_interval_ms`, and
`screen_off_seconds` — are **owned by Home Assistant** and edited there as
number entities on the panel device. What is left in `config.ini` is the
fallback the tablet uses before it has ever reached Home Assistant, and again
if the cache is lost. Nothing on the tablet has to be edited to change them.

Everything else — which entities this panel controls, their labels, and which
controls each tile offers — is configured in Home Assistant and read from the
panel's own config sensor, whose entity ID Home Assistant hands over during
pairing.

The token is not written by hand either. A panel without one shows a six-digit
pairing code and asks Home Assistant for a token; Home Assistant creates one
for a dedicated user, and the panel stores it with mode 0600. The code is the
**first** thing the setup in Home Assistant asks for, so the screen changes to
"Code accepted" while the rest of the form is filled in, and the token arrives
a few seconds after it is finished. A wiped tablet derives the same panel ID
again and re-pairs through the standard reauthentication prompt, keeping its
device and its room controls. Never commit the token.

`t560-announce-panel` publishes the panel over mDNS so that Home Assistant
offers to add it, and writes the resolved Home Assistant URL to
`discovered.ini`. The Openbox autostart starts it.

The layout is cached in `layout.json` after every successful read, so the
panel starts with the last known tiles when Home Assistant is unreachable at
boot. Only a tablet that has never reached Home Assistant waits on a
placeholder screen.

A layout change in Home Assistant restarts the panel the same way a
`config.ini` change does: the watchdog brings it back within about two
seconds, reading the fresh cache. The tablet does not reboot. A **settings**
change does not restart anything: the panel adopts a new poll interval on the
spot, and the Power button handler notices the new screen timeout in the cache
within half a second.

### The display, and who owns it

`t560-power-button.py` is the only owner of the backlight. It drives DPMS, it
holds the pointer grab that keeps a wake-up tap out of the interface, and it
applies the inactivity timeout — so Home Assistant reaches the display through
it rather than around it. Two processes forcing DPMS would race over that grab.

The panel writes `display-request.ini` when Home Assistant asks for the display
or the backlight level to change; the handler acts on it, deletes it, and
publishes what the display is really doing in `display-state.ini`. The panel
reads that file and reports it onward, together with the battery, on a change
and at least once a minute. Files rather than signals, because the handler
already wakes twice a second and busybox cannot send a real-time signal by
name.

Setting the backlight **level** needs write access to
`/sys/class/backlight/<device>/brightness`, which the session user does not
have by default. Grant it with a udev rule or by adding the user to the group
that owns the file; without it the tablet reports no controllable backlight and
the brightness control in Home Assistant stays unavailable. Turning the display
on and off works either way.

The Media Controller integration in
[custom_components/media_controller/](../../custom_components/media_controller)
must be installed and configured in Home Assistant first, and this tablet must
be added there as a panel; see
[docs/INTEGRATION.md](../../docs/INTEGRATION.md) and
[docs/ROOM_SLOTS.md](../../docs/ROOM_SLOTS.md).

## Source architecture

The application is split into focused C modules with explicit interfaces:

- `application` owns the application lifecycle and coordinates UI events with
  Home Assistant state;
- `app_config` validates and owns configuration data;
- `panel_config` reads the registry, the settings, and the commands Home
  Assistant publishes, and caches the payload;
- `panel_grid` is the arrangement itself: reading and writing `grid.json`,
  validating a card against the grid, and building the default 2 x 2
  arrangement a panel starts from. It knows nothing about GTK and is where the
  layout tests point;
- `panel_web` serves the layout editor over libsoup, in exactly eight routes
  and with no proxy to Home Assistant;
- `home_assistant_client` encapsulates authenticated asynchronous HTTP I/O;
- `panel_ui` builds and updates GTK widgets without knowing API details. The
  room page is one drawing area rather than a widget per card: a hundred cards
  would otherwise be a hundred widget trees, each with its own style context
  and its own invalidation, on an ARMv7 running a software renderer;
- `json_helpers` contains reusable, unit-tested JSON accessors;
- `system_status` reads the battery charge and charging state from
  `/sys/class/power_supply`, and the Wi-Fi signal and tablet temperature from
  `/proc/net/wireless` and `/sys/class/thermal`;
- `panel_display` asks the Power button handler to change the backlight, and
  reads back what it did;
- `main` is the minimal process entry point.

Two Python helpers run beside the application. `t560-power-button.py` owns
DPMS and the backlight: it handles the Power and Home buttons, the inactivity
timeout Home Assistant sets, the motion events, and the display requests the
panel forwards. `t560-motion-detector.py` captures camera frames and reports
motion to that handler with `SIGUSR2`.

The Makefile tracks header dependencies automatically. Run `make test` for the
unit tests and `make` for the application.

## Build and installation

The complete guide contains two end-to-end procedures:

- first installation on an unmodified tablet user account;
- updating an existing installation without replacing configuration or tokens.

See [BUILD_AND_INSTALL.md](docs/BUILD_AND_INSTALL.md).

`SHA256SUMS` describes the last binary built in a clean Alpine 3.20 ARMv7
container, together with the sources it was built from. **It predates the move
of the room configuration into Home Assistant**, so it no longer matches
`src/`; rebuild before deploying and regenerate the file.

The recommended deployment is rootless. The executable and launch scripts are
installed below `/home/vahac/.local`, and files are transferred through the
existing SSH connection without requiring SCP, SFTP, or administrative access.

## Openbox autostart

The ready-to-use [t560-openbox-autostart](openbox/t560-openbox-autostart)
starts Tint2, the cursor helper, the included Power button handler, and the
camera motion detector. A short Power press turns the display off, while any
key, touchscreen input, or detected motion wakes it. The same handler makes
Home screen-aware and retains the existing long-press Power menu. The autostart
does not start Badwolf, WebKit, or Matchbox Keyboard. Back up the current
autostart file before replacing it.

The first-installation procedure transfers the provided file as a candidate,
backs up the current Openbox autostart, tests the panel, and activates the new
autostart only after the test succeeds. The configuration helper changes only
the `Home` and `XF86HomePage` key bindings in `rc.xml` and keeps a backup.

## Alpine APK

The [APKBUILD](packaging/APKBUILD) limits the package to `armv7`. APK packaging
is optional and is not the recommended installation method on the current
tablet because it requires intentionally configured administrative access.

## Camera motion detection

`t560-motion-detector.py` captures the front camera through V4L2 at 320x240 and
2.5 FPS by default, compares consecutive frames as a 16x12 grid of block
averages, and reports confirmed motion to the button handler. A frame-wide
brightness change, such as a room light or the backlight itself, is subtracted
before the comparison and does not count as motion. The daemon needs only the
Python standard library and no OpenCV or neural-network runtime.

Every setting lives in the `[camera]` section of `config.ini`.
`motion_detection` is `off` by default: the `/dev/video0` DCAM shim of the
SM-T560 rejects `VIDIOC_REQBUFS`, so no application can capture frames from
the built-in sensor under the 3.10.17 kernel. `t560-motion-detector.py
--probe` reports each node and the exact call at which capture stops, and the
feature works as soon as a camera answers it with `capture works`, for example
a USB camera on the OTG port.

The measured driver behaviour, the architecture, and the tuning notes are
documented in [CAMERA.md](docs/CAMERA.md), and the kernel and root filesystem
changes that would make the built-in camera usable are listed in
[CAMERA_FIRMWARE.md](docs/CAMERA_FIRMWARE.md). Object recognition should still run
on a more powerful LAN server after the tablet detects motion.
