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
- Up to six room-control tiles, defined entirely in Home Assistant. The
  entity, the label, and which controls a tile offers come from the Media
  Controller integration; nothing about them is configured on the tablet.
- Brightness and color-temperature controls appear on a tile only when the
  entity behind it actually supports them, as reported by the integration.
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

## Tablet configuration files

```text
~/.config/t560-music-panel/panel-id          (written on the first run)
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
- `panel_config` reads the layout, the settings, and the commands Home
  Assistant publishes, and caches the payload;
- `home_assistant_client` encapsulates authenticated asynchronous HTTP I/O;
- `panel_ui` builds and updates GTK widgets without knowing API details;
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
