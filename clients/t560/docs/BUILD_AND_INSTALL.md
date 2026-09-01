# Build and installation guide

This project builds and installs a native application on the existing
postmarketOS system. It does not build or flash a postmarketOS image, kernel,
boot image, recovery image, or Android firmware.

The instructions below match the current Samsung SM-T560 installation:

- regular SSH access as `vahac`;
- no privilege-elevation utility and no assumed root password;
- Dropbear SSH without SCP or SFTP helpers;
- application files installed under `/home/vahac/.local`;
- all required GTK and Home Assistant client libraries already present;
- configuration edited with `nano`.

The recommended artifact is the small ARMv7 executable named `t560-panel`.

## Project locations

Windows source directory:

```text
D:\Sources\ha-media-controller\clients\t560
```

Tablet installation directories:

```text
/home/vahac/.local/bin
/home/vahac/.local/state
/home/vahac/.config/t560-music-panel
```

Installed files:

```text
/home/vahac/.local/bin/t560-panel
/home/vahac/.local/bin/t560-panel-watchdog
/home/vahac/.local/bin/t560-open-panel
/home/vahac/.local/bin/t560-restart-panel
/home/vahac/.local/bin/t560-power-button.py
/home/vahac/.local/bin/t560-motion-detector.py
/home/vahac/.local/bin/t560-home-button
/home/vahac/.local/bin/t560-configure-openbox.py
/home/vahac/.config/t560-music-panel/config.ini
/home/vahac/.config/t560-music-panel/token
/home/vahac/.local/share/applications/t560-home-assistant.desktop
/home/vahac/.local/share/icons/hicolor/<size>/apps/t560-music-panel.png
```

## Build the ARMv7 executable on Windows

Start Docker Desktop and open PowerShell:

```powershell
cd D:\Sources\ha-media-controller\clients\t560

docker run --rm --platform linux/arm/v7 `
  -v "D:\Sources\ha-media-controller\clients\t560:/src" `
  -w /src alpine:3.20 `
  sh -lc "apk add --no-cache build-base gtk+3.0-dev libsoup3-dev json-glib-dev file && make clean && make && file t560-panel"
```

The output file is:

```text
D:\Sources\ha-media-controller\clients\t560\t560-panel
```

The final `file` output must contain all of the following:

```text
ELF 32-bit
ARM
EABI5
/lib/ld-musl-armhf.so.1
```

The legacy WM class is intentionally retained for Openbox window matching. Its
GTK deprecation warning is suppressed only at that compatibility call site.

Do not deploy a binary identified as x86-64 or aarch64.

## Define the rootless SSH transfer helper

The current Dropbear server has neither SCP nor SFTP support. Use the existing
SSH connection to transfer Base64-encoded file content.

Run this once in the current PowerShell session:

```powershell
$TabletIp = "192.168.1.105"

function Send-T560File {
    param(
        [string]$LocalPath,
        [string]$RemotePath
    )

    $ResolvedPath = (Resolve-Path -LiteralPath $LocalPath).Path
    $EncodedData = [Convert]::ToBase64String(
        [IO.File]::ReadAllBytes($ResolvedPath)
    )
    $RemoteCommand = "base64 -d > '$RemotePath'"
    $EncodedData | ssh.exe "vahac@${TabletIp}" $RemoteCommand

    if ($LASTEXITCODE -ne 0) {
        throw "Transfer failed: $LocalPath"
    }
}
```

Change `$TabletIp` if NetworkManager assigns a different address.

# First installation

Follow every step in this section for a new installation.

## 1. Build the executable

Run the ARMv7 Docker build described above. Confirm that
`D:\Sources\ha-media-controller\clients\t560\t560-panel` exists.

## 2. Create user-owned directories

In PowerShell:

```powershell
ssh.exe "vahac@${TabletIp}" "mkdir -p ~/.local/bin ~/.local/state ~/.local/share/applications ~/.config/t560-music-panel ~/.config/openbox ~/.local/share/icons/hicolor/16x16/apps ~/.local/share/icons/hicolor/24x24/apps ~/.local/share/icons/hicolor/32x32/apps ~/.local/share/icons/hicolor/48x48/apps ~/.local/share/icons/hicolor/64x64/apps ~/.local/share/icons/hicolor/128x128/apps ~/.local/share/icons/hicolor/256x256/apps ~/.local/share/icons/hicolor/512x512/apps"
```

No root access is required.

## 3. Transfer application files

In the same PowerShell session where `Send-T560File` was defined:

```powershell
Send-T560File .\t560-panel /home/vahac/.local/bin/t560-panel
Send-T560File .\scripts\t560-panel-watchdog /home/vahac/.local/bin/t560-panel-watchdog
Send-T560File .\scripts\t560-open-panel /home/vahac/.local/bin/t560-open-panel
Send-T560File .\scripts\t560-restart-panel /home/vahac/.local/bin/t560-restart-panel
Send-T560File .\scripts\t560-power-button.py /home/vahac/.local/bin/t560-power-button.py
Send-T560File .\scripts\t560-motion-detector.py /home/vahac/.local/bin/t560-motion-detector.py
Send-T560File .\scripts\t560-home-button /home/vahac/.local/bin/t560-home-button
Send-T560File .\scripts\t560-configure-openbox.py /home/vahac/.local/bin/t560-configure-openbox.py
Send-T560File .\config\config.ini.example /home/vahac/.config/t560-music-panel/config.ini.example
Send-T560File .\openbox\t560-openbox-autostart /home/vahac/.config/openbox/autostart.t560-new
Send-T560File .\data\t560-home-assistant.desktop /home/vahac/.local/share/applications/t560-home-assistant.desktop.new
Send-T560File .\data\icons\hicolor\16x16\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/16x16/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\24x24\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/24x24/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\32x32\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/32x32/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\48x48\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/48x48/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\64x64\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/64x64/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\128x128\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/128x128/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\256x256\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/256x256/apps/t560-music-panel.png
Send-T560File .\data\icons\hicolor\512x512\apps\t560-music-panel.png /home/vahac/.local/share/icons/hicolor/512x512/apps/t560-music-panel.png
```

Create the initial configuration without overwriting an existing one, and set
permissions:

```powershell
ssh.exe "vahac@${TabletIp}" 'chmod 755 ~/.local/bin/t560-panel ~/.local/bin/t560-panel-watchdog ~/.local/bin/t560-open-panel ~/.local/bin/t560-restart-panel ~/.local/bin/t560-power-button.py ~/.local/bin/t560-motion-detector.py ~/.local/bin/t560-home-button ~/.local/bin/t560-configure-openbox.py ~/.config/openbox/autostart.t560-new; python3 -m py_compile ~/.local/bin/t560-power-button.py ~/.local/bin/t560-motion-detector.py ~/.local/bin/t560-configure-openbox.py; chmod 700 ~/.config/t560-music-panel; if test ! -f ~/.config/t560-music-panel/config.ini; then cp ~/.config/t560-music-panel/config.ini.example ~/.config/t560-music-panel/config.ini; fi; chmod 600 ~/.config/t560-music-panel/config.ini; mv ~/.local/share/applications/t560-home-assistant.desktop.new ~/.local/share/applications/t560-home-assistant.desktop; chmod 644 ~/.local/share/applications/t560-home-assistant.desktop; ls -l ~/.local/bin/t560-*'
```

## 4. Verify runtime libraries

Run:

```powershell
ssh.exe "vahac@${TabletIp}" 'ldd ~/.local/bin/t560-panel 2>&1; command -v xdotool || echo "xdotool not found"; ls /usr/lib/libXss.so.1 2>/dev/null || echo "libXss not found"'
```

Every library must resolve to an absolute path. Any line containing `not found`
identifies a real missing dependency.

`libXss.so.1` is optional. The button handler reads the X idle timer through it
to turn the display off after the configured inactivity timeout. Without that
library the handler asks the X server to apply the same timeout instead, which
works but is not logged per event.

Do not use `apk info -e` for this check. The current root filesystem contains
manually installed libraries whose package database records are unavailable.

## 5. Configure Home Assistant entity IDs

Connect to the tablet:

```powershell
ssh.exe "vahac@${TabletIp}"
```

Confirm that `nano` is available and edit the configuration:

```sh
command -v nano
nano "$HOME/.config/t560-music-panel/config.ini"
```

Set the Home Assistant URL and the panel identifier:

```ini
[home_assistant]
url=http://192.168.1.100:8123
panel_id=t560
```

There are no entity IDs here. Add this tablet as a panel in the Media
Controller integration first (Settings -> Devices & services -> Media
Controller -> Add a panel -> T560 panel), fill its room-control slots, and
`panel_id` is the panel name lowercased with spaces replaced by underscores. A
panel named `T560` publishes `sensor.t560_config`, and everything the panel
draws comes from there. Add `config_entity=` only if that sensor was renamed
in Home Assistant.

The `[panel]` section holds the tablet-local settings: polling timings and
the inactivity timeout that turns the display off. They stay on the tablet
because the Power button handler and the motion detector read them directly,
without going through Home Assistant.

```ini
[panel]
poll_interval_ms=1000
playlist_poll_interval_ms=60000
screen_off_seconds=30
```

Set `screen_off_seconds=0` to keep the display on until the Power button is
pressed. Other values are clamped to 5-3600 seconds.

In `nano`, save with `Ctrl+O`, press `Enter`, and exit with `Ctrl+X`.

## 6. Create the Home Assistant token file

Create a dedicated long-lived access token in the Home Assistant user profile.
Edit the token file over SSH:

```sh
nano "$HOME/.config/t560-music-panel/token"
chmod 600 "$HOME/.config/t560-music-panel/token"
```

The file must contain only the token value, without quotes, labels, or shell
syntax. Never commit or transfer this token back into the source repository.

## 7. Stop Badwolf for the current session

Run as the regular user:

```sh
pkill -f '[t]560-badwolf-watchdog' 2>/dev/null || true
pkill -x badwolf 2>/dev/null || true
```

This does not change autostart yet.

## 8. Test the native panel

`t560-configure-openbox.py` rewrites both the Home key bindings and the
`t560-music-panel` application rule, which keeps the panel window
fullscreen and undecorated.

Run:

```sh
mkdir -p "$HOME/.local/state"
export DISPLAY=:0
if [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi
export GTK_THEME=Adwaita:dark

"$HOME/.local/bin/t560-configure-openbox.py" \
  "$HOME/.config/openbox/rc.xml"
openbox --reconfigure
nohup python3 "$HOME/.local/bin/t560-power-button.py" \
  >>"$HOME/.local/state/power-button.log" 2>&1 </dev/null &
nohup python3 "$HOME/.local/bin/t560-motion-detector.py" \
  >>"$HOME/.local/state/motion-detector.log" 2>&1 </dev/null &

nohup "$HOME/.local/bin/t560-panel" \
  >"$HOME/.local/state/t560-music-panel.log" 2>&1 \
  </dev/null &
```

Check the process and log:

```sh
sleep 3
ps | grep '[t]560-panel'
tail -n 100 "$HOME/.local/state/t560-music-panel.log"
```

Verify on the touchscreen:

1. The panel opens fullscreen and no panel or decoration is visible
   above it.
2. The link icon in the header turns from amber to teal once the first
   poll succeeds, and becomes a red broken link when Home Assistant is
   unreachable.
3. The header clock shows the current time and date.
4. The upright battery indicator shows the charge percentage, and turns
   green with a bolt within ten seconds of connecting the charger.
5. Album art, title, artist, progress, and volume appear.
6. Player buttons work.
7. Queue and playlist selection work.
8. Configured room controls work.
9. Matchbox Keyboard does not open.
10. A short Power press turns the display off.
11. Any physical key or touchscreen input wakes the display, and the
    wake-up tap does not activate the control under the finger.
12. A long Power press opens the existing power menu.
13. Home toggles between the panel and desktop while the display is on.
14. If the display is off, Home wakes it without toggling the panel.
15. The display turns off on its own after `screen_off_seconds` without input,
    and any touch wakes it again.
16. With `motion_detection=on`, walking in front of the tablet while the
    display is off turns it on, and the display stays on while the movement
    continues. The camera log records both:

```text
motion: detected
```

```text
motion: backlight on
```

17. Pressing Power to turn the display off does not wake it again while
    `motion_wake_grace_seconds` has not elapsed.

Items 16 and 17 apply only to a tablet with a usable camera. The built-in
camera of the SM-T560 is not usable and `motion_detection` is `off` by
default, so the daemon logs one line and exits; every other feature keeps
working. Confirm the camera state with `t560-motion-detector.py --probe`.

Do not enable autostart until this test passes.

## 9. Enable the provided Openbox autostart

The provided autostart keeps Tint2 and the cursor helper and starts the included
Power and Home button handler. It starts neither Badwolf nor Matchbox Keyboard.

Back up the current Openbox autostart only once:

```sh
if [ -f "$HOME/.config/openbox/autostart" ] && \
   [ ! -f "$HOME/.config/openbox/autostart.before-t560-music-panel" ]; then
    cp "$HOME/.config/openbox/autostart" \
       "$HOME/.config/openbox/autostart.before-t560-music-panel"
fi
```

Activate the reviewed file:

```sh
mv "$HOME/.config/openbox/autostart.t560-new" \
   "$HOME/.config/openbox/autostart"
chmod 755 "$HOME/.config/openbox/autostart"
```

The Openbox `rc.xml` file is not replaced. The configuration helper changes only
the `Home` and `XF86HomePage` bindings and saves the original file as
`rc.xml.before-t560-home-button`. The long-press Power menu remains intact.

The existing Tint2 configurations already reference
`~/.local/share/applications/t560-home-assistant.desktop`. The installed desktop
entry changes that existing launcher slot into a `Restart Music Panel` button.
Tint2 reloads the updated launcher after the next login or reboot.

The desktop entry refers to the `t560-music-panel` icon, which is installed
into the user icon theme at
`~/.local/share/icons/hicolor/<size>/apps/t560-music-panel.png`. Tint2 resolves
the name through the icon theme, so the launcher on the desktop shows the panel
icon instead of the generic audio icon. Regenerate the icon files with
`python3 tools/make-app-icon.py` after the geometry or the colours change.

## 10. Start the watchdog

Stop the one-off test process and start the persistent watchdog:

```sh
pkill -x t560-panel 2>/dev/null || true
nohup "$HOME/.local/bin/t560-panel-watchdog" \
  >/dev/null 2>&1 </dev/null &
```

Verify:

```sh
sleep 3
ps | grep '[t]560-panel'
tail -n 100 "$HOME/.local/state/t560-music-panel.log"
```

Reboot once after the watchdog test passes. The panel should start with Openbox.

# Update an existing installation

Use this procedure for every later source-code update. It preserves
`config.ini`, the Home Assistant token, and the Openbox configuration.

## 1. Rebuild the ARMv7 executable

On Windows, run the Docker build from the beginning of this document:

```powershell
cd D:\Sources\ha-media-controller\clients\t560

docker run --rm --platform linux/arm/v7 `
  -v "D:\Sources\ha-media-controller\clients\t560:/src" `
  -w /src alpine:3.20 `
  sh -lc "apk add --no-cache build-base gtk+3.0-dev libsoup3-dev json-glib-dev file && make clean && make && file t560-panel"
```

## 2. Define the transfer helper

Define `$TabletIp` and `Send-T560File` again if this is a new PowerShell session.

## 3. Transfer update candidates

Transfer new files with `.new` suffixes so a failed transfer cannot damage the
currently installed application:

```powershell
Send-T560File .\t560-panel /home/vahac/.local/bin/t560-panel.new
Send-T560File .\scripts\t560-panel-watchdog /home/vahac/.local/bin/t560-panel-watchdog.new
Send-T560File .\scripts\t560-open-panel /home/vahac/.local/bin/t560-open-panel.new
Send-T560File .\scripts\t560-restart-panel /home/vahac/.local/bin/t560-restart-panel.new
Send-T560File .\scripts\t560-power-button.py /home/vahac/.local/bin/t560-power-button.py.new
Send-T560File .\scripts\t560-motion-detector.py /home/vahac/.local/bin/t560-motion-detector.py.new
Send-T560File .\scripts\t560-home-button /home/vahac/.local/bin/t560-home-button.new
Send-T560File .\scripts\t560-configure-openbox.py /home/vahac/.local/bin/t560-configure-openbox.py.new
```

Do not transfer `config.ini` or `token` during an update.

## 4. Validate the new executable

Run:

```powershell
ssh.exe "vahac@${TabletIp}" 'chmod 755 ~/.local/bin/t560-panel.new ~/.local/bin/t560-panel-watchdog.new ~/.local/bin/t560-open-panel.new ~/.local/bin/t560-restart-panel.new ~/.local/bin/t560-power-button.py.new ~/.local/bin/t560-motion-detector.py.new ~/.local/bin/t560-home-button.new ~/.local/bin/t560-configure-openbox.py.new; python3 -m py_compile ~/.local/bin/t560-power-button.py.new ~/.local/bin/t560-motion-detector.py.new ~/.local/bin/t560-configure-openbox.py.new; ldd ~/.local/bin/t560-panel.new 2>&1'
```

Stop if any dependency is reported as `not found`.

## 5. Atomically activate the update

Connect to the tablet:

```powershell
ssh.exe "vahac@${TabletIp}"
```

Stop the watchdog and application:

```sh
pkill -f '[t]560-panel-watchdog' 2>/dev/null || true
pkill -x t560-panel 2>/dev/null || true
pkill -f '[t]560-power-button.py' 2>/dev/null || true
pkill -f '[t]560-motion-detector.py' 2>/dev/null || true
```

Keep one rollback copy and activate the new files:

```sh
cp "$HOME/.local/bin/t560-panel" \
   "$HOME/.local/bin/t560-panel.previous"
cp "$HOME/.local/bin/t560-panel-watchdog" \
   "$HOME/.local/bin/t560-panel-watchdog.previous"
cp "$HOME/.local/bin/t560-open-panel" \
   "$HOME/.local/bin/t560-open-panel.previous"
cp "$HOME/.local/bin/t560-restart-panel" \
   "$HOME/.local/bin/t560-restart-panel.previous"
cp "$HOME/.local/bin/t560-power-button.py" \
   "$HOME/.local/bin/t560-power-button.py.previous"
if [ -f "$HOME/.local/bin/t560-motion-detector.py" ]; then
    cp "$HOME/.local/bin/t560-motion-detector.py" \
       "$HOME/.local/bin/t560-motion-detector.py.previous"
fi
if [ -f "$HOME/.local/bin/t560-home-button" ]; then
    cp "$HOME/.local/bin/t560-home-button" \
       "$HOME/.local/bin/t560-home-button.previous"
fi
if [ -f "$HOME/.local/bin/t560-configure-openbox.py" ]; then
    cp "$HOME/.local/bin/t560-configure-openbox.py" \
       "$HOME/.local/bin/t560-configure-openbox.py.previous"
fi
cp "$HOME/.config/openbox/rc.xml" \
   "$HOME/.config/openbox/rc.xml.t560-deploy-previous"

mv "$HOME/.local/bin/t560-panel.new" \
   "$HOME/.local/bin/t560-panel"
mv "$HOME/.local/bin/t560-panel-watchdog.new" \
   "$HOME/.local/bin/t560-panel-watchdog"
mv "$HOME/.local/bin/t560-open-panel.new" \
   "$HOME/.local/bin/t560-open-panel"
mv "$HOME/.local/bin/t560-restart-panel.new" \
   "$HOME/.local/bin/t560-restart-panel"
mv "$HOME/.local/bin/t560-power-button.py.new" \
   "$HOME/.local/bin/t560-power-button.py"
mv "$HOME/.local/bin/t560-motion-detector.py.new" \
   "$HOME/.local/bin/t560-motion-detector.py"
mv "$HOME/.local/bin/t560-home-button.new" \
   "$HOME/.local/bin/t560-home-button"
mv "$HOME/.local/bin/t560-configure-openbox.py.new" \
   "$HOME/.local/bin/t560-configure-openbox.py"

chmod 755 "$HOME/.local/bin/t560-panel" \
          "$HOME/.local/bin/t560-panel-watchdog" \
          "$HOME/.local/bin/t560-open-panel" \
          "$HOME/.local/bin/t560-restart-panel" \
          "$HOME/.local/bin/t560-power-button.py" \
          "$HOME/.local/bin/t560-motion-detector.py" \
          "$HOME/.local/bin/t560-home-button" \
          "$HOME/.local/bin/t560-configure-openbox.py"

"$HOME/.local/bin/t560-configure-openbox.py" \
  "$HOME/.config/openbox/rc.xml"
DISPLAY=:0 openbox --reconfigure
```

## 6. Restart and verify

```sh
: >"$HOME/.local/state/t560-music-panel.log"
nohup "$HOME/.local/bin/t560-panel-watchdog" \
  >/dev/null 2>&1 </dev/null &
nohup python3 "$HOME/.local/bin/t560-power-button.py" \
  >>"$HOME/.local/state/power-button.log" 2>&1 </dev/null &
nohup python3 "$HOME/.local/bin/t560-motion-detector.py" \
  >>"$HOME/.local/state/motion-detector.log" 2>&1 </dev/null &

sleep 3
ps | grep '[t]560-panel'
ps | grep '[t]560-power-button.py'
ps | grep '[t]560-motion-detector.py'
tail -n 100 "$HOME/.local/state/t560-music-panel.log"
tail -n 20 "$HOME/.local/state/power-button.log"
tail -n 20 "$HOME/.local/state/motion-detector.log"
```

Verify the main player page and at least one Home Assistant action on the
touchscreen. Then press Power briefly, confirm that the display turns off, and
confirm that both a physical key and a touchscreen tap wake it. Tap directly
on a player button while the display is off: it must only wake the display.
Test both Home
paths: panel-to-desktop-to-panel while the display is on, and wake-only while
the display is off. Finally, leave the tablet untouched for the configured
`screen_off_seconds` and confirm that the display turns off by itself. The
handler log records the reason:

```text
idle 30.0s: backlight off
```

## 7. Roll back a failed update

If the new version fails:

```sh
pkill -f '[t]560-panel-watchdog' 2>/dev/null || true
pkill -x t560-panel 2>/dev/null || true
pkill -f '[t]560-power-button.py' 2>/dev/null || true
pkill -f '[t]560-motion-detector.py' 2>/dev/null || true

mv "$HOME/.local/bin/t560-panel.previous" \
   "$HOME/.local/bin/t560-panel"
mv "$HOME/.local/bin/t560-panel-watchdog.previous" \
   "$HOME/.local/bin/t560-panel-watchdog"
mv "$HOME/.local/bin/t560-open-panel.previous" \
   "$HOME/.local/bin/t560-open-panel"
mv "$HOME/.local/bin/t560-restart-panel.previous" \
   "$HOME/.local/bin/t560-restart-panel"
mv "$HOME/.local/bin/t560-power-button.py.previous" \
   "$HOME/.local/bin/t560-power-button.py"
if [ -f "$HOME/.local/bin/t560-motion-detector.py.previous" ]; then
    mv "$HOME/.local/bin/t560-motion-detector.py.previous" \
       "$HOME/.local/bin/t560-motion-detector.py"
fi
if [ -f "$HOME/.local/bin/t560-home-button.previous" ]; then
    mv "$HOME/.local/bin/t560-home-button.previous" \
       "$HOME/.local/bin/t560-home-button"
else
    rm -f "$HOME/.local/bin/t560-home-button"
fi
if [ -f "$HOME/.local/bin/t560-configure-openbox.py.previous" ]; then
    mv "$HOME/.local/bin/t560-configure-openbox.py.previous" \
       "$HOME/.local/bin/t560-configure-openbox.py"
else
    rm -f "$HOME/.local/bin/t560-configure-openbox.py"
fi
mv "$HOME/.config/openbox/rc.xml.t560-deploy-previous" \
   "$HOME/.config/openbox/rc.xml"

chmod 755 "$HOME/.local/bin/t560-panel" \
          "$HOME/.local/bin/t560-panel-watchdog" \
          "$HOME/.local/bin/t560-open-panel" \
          "$HOME/.local/bin/t560-restart-panel" \
          "$HOME/.local/bin/t560-power-button.py"

DISPLAY=:0 openbox --reconfigure

nohup "$HOME/.local/bin/t560-panel-watchdog" \
  >/dev/null 2>&1 </dev/null &
nohup python3 "$HOME/.local/bin/t560-power-button.py" \
  >>"$HOME/.local/state/power-button.log" 2>&1 </dev/null &
```

# Change configuration later

Edit configuration with `nano`:

```sh
nano "$HOME/.config/t560-music-panel/config.ini"
```

Restart the application after saving:

```sh
pkill -x t560-panel
```

The watchdog starts it again within two seconds.

The `screen_off_seconds` value is read by the button handler at start-up.
Restart that handler after changing it:

```sh
pkill -f '[t]560-power-button.py'
nohup python3 "$HOME/.local/bin/t560-power-button.py" \
  >>"$HOME/.local/state/power-button.log" 2>&1 </dev/null &
```

The `[camera]` section is read by the motion detector at start-up, except for
`motion_wake_grace_seconds`, which the button handler above reads. Restart the
detector after changing any camera key:

```sh
pkill -f '[t]560-motion-detector.py'
nohup python3 "$HOME/.local/bin/t560-motion-detector.py" \
  >>"$HOME/.local/state/motion-detector.log" 2>&1 </dev/null &
```

# Camera motion detection

An update does not replace an existing `config.ini`, and a configuration
without a `[camera]` section keeps the documented defaults: detection is on
and the node is probed automatically. Copy the section from
[config.ini.example](../config/config.ini.example) into the tablet
configuration only when a value has to be changed:

```sh
nano "$HOME/.config/t560-music-panel/config.ini"
```

Detection is `off` by default. The built-in camera of this tablet cannot be
used: `/dev/video0` is a Spreadtrum DCAM shim that rejects `VIDIOC_REQBUFS`,
so no application can capture frames from it. The measurement is recorded in
[CAMERA.md](CAMERA.md).

Check any camera, including one attached later, with the built-in probe. It
needs no administrative access and works while detection is off:

```sh
python3 "$HOME/.local/bin/t560-motion-detector.py" --probe
```

The probe prints the driver, the pixel formats, and the exact V4L2 call at
which capture stops. On this tablet it ends with:

```text
capture setup stops here: REQBUFS failed: Not a tty
```

A usable camera ends with `capture works` instead. Set `motion_detection=on`
then, and write its node into `device=` when several nodes accept capture. The
start-up line of the log names the node, the driver, and the negotiated
format:

```text
camera: /dev/video0 [USB Camera] GREY 320x240 stride 320
```

Tuning:

- False events from sensor noise: raise `pixel_threshold`, `motion_frames`,
  or `motion_area_percent`.
- Movement is missed: lower `motion_area_percent`, or lower
  `frame_interval_ms` so that faster movement is still compared frame by
  frame.
- CPU use is too high: raise `frame_interval_ms`, or lower `width` and
  `height`.
- The display must never turn off while somebody is in the room: keep
  `motion_detection=on` and leave `screen_off_seconds` at its normal value,
  because detected motion postpones the automatic screen off.

Measure the cost on the tablet before declaring the settings final:

```sh
top -n 1 | grep '[t]560-motion-detector'
```

# Logs and diagnostics

Application log:

```text
/home/vahac/.local/state/t560-music-panel.log
```

Button handler and camera logs:

```text
/home/vahac/.local/state/power-button.log
/home/vahac/.local/state/motion-detector.log
```

Follow them over SSH:

```sh
tail -f "$HOME/.local/state/t560-music-panel.log"
tail -f "$HOME/.local/state/motion-detector.log"
```

Common conditions:

- `Home Assistant HTTP 401`: replace the token.
- A teal link icon with empty controls: correct the entity IDs in
  `config.ini`.
- `cannot open display`: confirm `DISPLAY=:0` and the X session owner.
- `not found` in `ldd`: the corresponding shared library is genuinely missing.
- immediate watchdog restart loop: inspect the log before restarting again.
- `no usable camera; motion detection stops`: no `/dev/video*` node accepted a
  supported format. The display then behaves exactly as before TB-6.
- `the Power button handler is not running`: motion was detected but nothing
  owns DPMS. Start `t560-power-button.py` again.

# Restore the previous Badwolf autostart

Stop the native panel:

```sh
pkill -f '[t]560-panel-watchdog' 2>/dev/null || true
pkill -x t560-panel 2>/dev/null || true
```

Restore the saved file:

```sh
cp "$HOME/.config/openbox/autostart.before-t560-music-panel" \
   "$HOME/.config/openbox/autostart"
chmod 755 "$HOME/.config/openbox/autostart"
```

No postmarketOS reflash is required.

# Optional APK packaging

The project includes `packaging/APKBUILD`, but APK installation is not the
recommended method on the current tablet because system-wide package
installation requires administrative access. Use the rootless procedure above.

Build and sign an APK only after administrative access has been intentionally
configured and the rootless installation has been verified on the hardware.
