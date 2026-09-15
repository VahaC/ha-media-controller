# SM-T560 firmware: postmarketOS with a working front camera

Everything needed to put postmarketOS on a Samsung Galaxy Tab E 9.6 SM-T560
(`samsung-gtelwifi`, Spreadtrum SC7730, kernel 3.10.17) and to make its front
camera deliver frames to user space, so that the
[T560 music panel](../README.md) can wake its display when somebody walks up
to it. The stock postmarketOS kernel exposes `/dev/video0` but never delivers
a frame; the kernel package in this folder fixes that.

The full story, with every dead end on the way, is on my blog:

- [Samsung T560 camera support on postmarketOS: a proven step-by-step guide](https://vahac.com/blogs/samsung-t560-camera-support-postmarketos/)
- [Install postmarketOS on the Samsung T560](https://vahac.com/blogs/install-postmarketos-on-samsung-t560/), the prerequisite

This document is the compact, command-only version of both posts.

## What is in this folder

```text
README.md                        this guide
SHA256SUMS                       checksums of every file below
build-camera-kernel.cmd          Windows: build the kernel and export the boot image in WSL
flash-camera-boot.cmd            Windows: guarded flash of a boot image over SSH
boot/boot-sm-t560-camera-r20.img prebuilt boot image, kernel 3.10.17 #21-postmarketOS
pmaports/linux-samsung-gtelwifi/ the kernel package: APKBUILD, kernel config, ten camera patches
scripts/verify-patches.sh        PC: prove the patch series applies cleanly to the upstream tree
scripts/build-kernel.sh          PC: stage the package into pmaports and build it
scripts/export-boot.sh           PC: install the package into the rootfs chroot and export boot.img
scripts/tablet-backup-boot.sh    tablet: copy the 16 MiB boot partition to a file
scripts/tablet-flash-boot.sh     tablet: write one image to the boot partition, verify, never reboot
scripts/tablet-verify-camera.sh  tablet: check the kernel, the driver parameters and the detector
scripts/tablet-capture-frame.py  tablet: save one settled NV21 frame from the camera
scripts/nv21-to-png.py           PC: turn that frame into PNG files and print its statistics
scripts/enable-motion-detection.sh  tablet: switch the panel's motion detection on
scripts/test-motion-detection.sh    tablet: wave at the camera and read the detector log
scripts/twrp-restore-boot.sh     PC: restore the boot partition from TWRP over ADB
```

Only the files that differ from upstream pmaports are shipped in
`pmaports/linux-samsung-gtelwifi/`. The generic patches the `APKBUILD` lists
(gcc fixes, `sprdfb`) come from the pmaports checkout that `pmbootstrap init`
creates.

## What you get

- Kernel `Linux 3.10.17 #21-postmarketOS`, package `linux-samsung-gtelwifi-3.10.17-r20`.
- `/dev/video0` streams NV21 (and the other YUV 4:2:0 layouts) through the
  standard videobuf2 mmap API. 320x240 gives 115200-byte frames at about
  15 frames per second.
- The front sensor SR200PC20M is powered, clocked and started by the kernel
  itself, without the Android camera HAL.
- The panel's [motion detector](../scripts/t560-motion-detector.py) works
  unchanged and turns the display on when it sees movement.
- Three root-only module parameters for experiments, listed at the end.

Everything else about the tablet stays as it was: only the 16 MiB boot
partition `/dev/mmcblk0p20` is rewritten. The root filesystem, the recovery,
the user data and the panel installation are not touched.

## Prerequisites

- A Samsung Galaxy Tab E 9.6 **SM-T560** (Wi-Fi). Not the SM-T561 3G model:
  TWRP may call the tablet `SM-T561` or `omni_t561`, that is normal, but the
  bootloader string in `/proc/cmdline` must read `androidboot.bootloader=T560`.
- postmarketOS already installed and booting, with SSH access and `sudo` for
  your user, as described in the
  [installation post](https://vahac.com/blogs/install-postmarketos-on-samsung-t560/).
  If you have not done that yet, start there: `pmbootstrap init` with device
  `samsung-gtelwifi`, then `pmbootstrap install --android-recovery-zip` and
  flash the ZIP from TWRP.
- On the PC: Linux or WSL with `pmbootstrap` initialised for that device (the
  same checkout you installed from is ideal), `git`, GNU `patch`, `python3`.
  Windows users additionally need `ssh.exe` (the built-in OpenSSH client) for
  the `.cmd` launchers.
- For the rescue path: TWRP on the tablet and `adb` on the PC.
- For the motion-detection part: the panel installed as described in
  [BUILD_AND_INSTALL.md](../docs/BUILD_AND_INSTALL.md), so that
  `~/.local/bin/t560-motion-detector.py` exists and your user is in the
  `video` group.

Dropbear, the SSH server of this postmarketOS image, has no SFTP and no SCP.
Every file transfer below is a plain SSH pipe, which works from any OS.

## Step 1: install postmarketOS

Follow the [installation post](https://vahac.com/blogs/install-postmarketos-on-samsung-t560/).
In short: `pmbootstrap init` (channel `edge`, device `samsung-gtelwifi`,
`openrc`), build the device packages, `pmbootstrap install
--android-recovery-zip`, `pmbootstrap export`, copy
`pmos-samsung-gtelwifi.zip` to the tablet, install it from TWRP, log in over
SSH. The rest of this guide assumes that tablet.

## Step 2: back up the boot partition

**⚠️ Do this before anything else.** The backup is the only way back if a
kernel does not boot. On the tablet:

```sh
ssh -T user@tablet "cat > /tmp/tablet-backup-boot.sh" < scripts/tablet-backup-boot.sh
ssh -t user@tablet "sudo sh /tmp/tablet-backup-boot.sh /tmp/mmcblk0p20-backup.img"
```

It prints `BACKUP_SHA256=...`. Download the file through a pipe (no `-t`, a
terminal would corrupt the binary stream) and compare the hash:

```sh
ssh -T user@tablet "cat /tmp/mmcblk0p20-backup.img" > mmcblk0p20-backup.img
sha256sum mmcblk0p20-backup.img
ssh -T user@tablet "rm /tmp/mmcblk0p20-backup.img /tmp/tablet-backup-boot.sh"
```

The backup must be exactly 16777216 bytes. Keep it and its hash next to each
other; both rollback scripts below need them.

## Step 3: get a boot image

### Option A: use the prebuilt image

`boot/boot-sm-t560-camera-r20.img` is the image running on my tablet. It was
exported by pmbootstrap 3.11.1 from a rootfs chroot created with
`pmbootstrap init` for `samsung-gtelwifi`, so its initramfs is the ordinary
postmarketOS one and is not tied to my installation. Verify it before use:

```sh
sha256sum -c SHA256SUMS
```

### Option B: build it yourself

Run this on the Linux or WSL machine that holds your pmbootstrap setup.

1. Optional but recommended: prove that the patch series applies to the
   pristine upstream kernel without fuzz. It uses the tarball pmbootstrap has
   already downloaded when it can, otherwise it fetches 120 MB:

   ```sh
   sh scripts/verify-patches.sh
   ```

   Every line must read `OK`, followed by `PATCH_SERIES_VERIFIED`.

2. Stage the package into your pmaports checkout and build it. The script
   checks the SHA512 of every shipped file against the `APKBUILD` before and
   after copying:

   ```sh
   sh scripts/build-kernel.sh --dry-run
   sh scripts/build-kernel.sh
   ```

3. Install the package into the rootfs chroot and export the boot image. The
   script refuses to overwrite an existing output, checks that `vmlinuz`
   carries the build tag `#21-postmarketOS` and the camera driver, and prints
   the hashes the flash step needs:

   ```sh
   sh scripts/export-boot.sh boot/boot-sm-t560-camera.img
   ```

   Write down `BOOT_IMAGE_SHA256` and `EXPECTED_P20_SHA256_AFTER_FLASH`.

On Windows, `build-camera-kernel.cmd` runs steps 2 and 3 in WSL Ubuntu.

**⚠️ About `pkgrel`.** The package sets the kernel build tag to
`pkgrel + 1`, so `pkgrel=20` produces `#21-postmarketOS`. Bump `pkgrel` for
every rebuild you intend to flash, otherwise `apk` keeps the old package in
the chroot and you export a stale kernel. `export-boot.sh` catches that by
reading the banner inside `vmlinuz`.

### What the patches do

- `0001` adds a videobuf2 mmap capture path to the DCAM V4L2 driver
  (`REQBUFS`, `QBUF`, `DQBUF`, `STREAMON` on path 1) with a fixed capture
  context (CSI-2 input, YUV 8 bit, 1 lane, 800x600 sensor preview scaled to
  the requested size), and a minimal driver for the SR200PC20M front sensor
  that reuses the board's power sequence, enables MCLK at 24 MHz, writes the
  vendor register table and starts the stream.
- `0002`, `0004` fix the MCLK handling: the 3.10 clock framework panics on a
  NULL clock handle, so the handle is taken from the device tree and an
  unsupported exact rate falls back cleanly.
- `0003`, `0009` add and later retire a one-shot safety guard that was used
  while the driver was still unproven. `0009` leaves
  `gtelwifi_camera_disable` as the emergency switch.
- `0005` refuses the GREY (YUV400) format, which was never verified, and logs
  a stream that ended without a frame.
- `0006` adds a CSI-2 host and D-PHY register snapshot to the kernel log when
  DCAM times out. This is what showed that PHY A and PHY B never see the
  sensor.
- `0007`, `0008` select **CSI PHY C** (`phy_id = 4`) and program the capture
  unit for **UYVY** byte order, both as defaults and as module parameters.
  These two lines are the difference between zero frames or a flat grey
  picture and a real image.
- `0010` demotes the per-frame `DCAM: sof 1 wait` message to a trace; it
  flooded the log at 15 lines per second while the detector streamed.
- `config-samsung-gtelwifi.armv7` enables `VIDEOBUF2_CORE`,
  `VIDEOBUF2_DMA_CONTIG`, `CMA` (8 MB) and `IKCONFIG_PROC`.
- `fix-dtb_qcom-msm-id.patch` is the upstream `fix-dtb_qcom,msm-id.patch`
  under a name without a comma, which pmbootstrap handles more reliably on a
  Windows-mounted tree. The content is identical.

All driver changes are inside `#if defined(CONFIG_MACH_GTELWIFI)` so the tree
still builds for other Spreadtrum boards.

## Step 4: flash the boot partition

**⚠️ The write goes to `/dev/mmcblk0p20` and nowhere else.** `p21` holds
another Android image, the root filesystem lives elsewhere, and the script
refuses to run if the target is not exactly 16 MiB or the tablet is not an
SM-T560. It also never reboots: you do that yourself after the hash matches.

Upload the script and the image through SSH pipes, then run the guarded
write. It asks for the `sudo` password and then for the token
`FLASH-SM-T560-P20`, typed exactly:

```sh
ssh -T user@tablet "umask 077; cat > /tmp/tablet-flash-boot.sh" < scripts/tablet-flash-boot.sh
ssh -T user@tablet "umask 077; cat > /tmp/boot.img" < boot/boot-sm-t560-camera-r20.img
ssh -t user@tablet "sudo sh /tmp/tablet-flash-boot.sh /tmp/boot.img 0537fcf93154cba3850309880726f3c80e18970e2212a297f9ae980c33004cf3"
```

For an image you built yourself, pass its `BOOT_IMAGE_SHA256` instead. The
script verifies the upload, writes the image padded with zeros to the full
16 MiB, re-reads the whole partition and compares it with the padded hash
(`7f12ee7612e49611d9500f19a05e7b7ee76f1d7e330fadbd545d5ca3c859dc84` for the
prebuilt image). The last line must be `FLASH_VERIFIED_NO_REBOOT_PERFORMED`.
Only then:

```sh
ssh -T user@tablet "rm /tmp/boot.img /tmp/tablet-flash-boot.sh"
ssh -t user@tablet "sudo reboot"
```

On Windows, `flash-camera-boot.cmd [image]` does the three uploads and the
guarded write with `ssh.exe`; it reads the tablet address from
`T560_TABLET_IP` and the user from `T560_TABLET_USER`, like
[deploy-tablet.cmd](../deploy-tablet.cmd).

**⚠️ If the final hash does not match**, do not reboot. Run the same script
again with your backup file and its hash; a 16 MiB backup needs no padding and
restores the partition byte for byte.

## Step 5: verify the kernel after the reboot

```sh
ssh -T user@tablet "cat > /tmp/tablet-verify-camera.sh" < scripts/tablet-verify-camera.sh
ssh -t user@tablet "sudo sh /tmp/tablet-verify-camera.sh"
```

Expected: `uname -a` shows `#21-postmarketOS`, the three parameters read
`N`, `4` and `2`, `/dev/video0` is `crw-rw---- root video`, the count of
`DCAM: sof 1 wait` lines is 0, the boot partition hash is the padded hash
from step 4, and the last line is `CAMERA_KERNEL_VERIFIED`. For your own
build pass the tag and the hash `export-boot.sh` printed:

```sh
ssh -t user@tablet "sudo sh /tmp/tablet-verify-camera.sh '#22-postmarketOS' <EXPECTED_P20_SHA256_AFTER_FLASH>"
```

A healthy first camera open looks like this in `dmesg`:

```text
sensor_sr200pc20m_poweron : OK
camera-r18: DCAM capture YUV pattern=2 (0=YUYV 1=YVYU 2=UYVY 3=VYUY)
camera-r17: opening MIPI on CSI phy_id=0x4 lanes=1 mbps=480
SENSOR: MIPI on, phy 0x4, lane 1, bps 480
sr200pc20m: chip id 0xb4
sr200pc20m: 800x600 preview stream started
DCAM PATH S: 7
```

## Step 6: capture a frame

The capture helper uses the V4L2 client of the panel's motion detector, so
the panel must be installed. Stop the detector first if it is running, then
read twenty frames and keep the last one:

```sh
ssh -T user@tablet "cat > /tmp/tablet-capture-frame.py" < scripts/tablet-capture-frame.py
ssh -t user@tablet "pkill -f t560-motion-detector.py; python3 /tmp/tablet-capture-frame.py /tmp/frame.nv21 20"
ssh -T user@tablet "cat /tmp/frame.nv21" > frame.nv21
python3 scripts/nv21-to-png.py frame.nv21
```

`FRAME_SAVED ... format=NV21 width=320 height=240 bytes=115200` on the
tablet, and on the PC a luma range spanning most of 0 to 255 with chroma
means near 128. `frame.nv21.png` is the picture, `frame.nv21-luma.png` the
grey plane. Skipping the first frame matters: the sensor starts mid-frame and
the exposure settles over the first second.

## Step 7: turn on motion detection

The panel already carries the detector and the button handler; the only
change is one key in the configuration. On the tablet, as the panel user:

```sh
ssh -T user@tablet "cat > /tmp/enable-motion-detection.sh" < scripts/enable-motion-detection.sh
ssh -t user@tablet "sh /tmp/enable-motion-detection.sh"
```

It keeps a timestamped copy of `config.ini` and changes only
`motion_detection=on` in the `[camera]` section. The detector is started by
the Openbox autostart, so either reboot, or start it now:

```sh
ssh -t user@tablet "nohup python3 ~/.local/bin/t560-motion-detector.py >> ~/.local/state/motion-detector.log 2>&1 &"
```

Then test it. Turn the display off with a short Power press, wait for the
grace period (`motion_wake_grace_seconds`, 30 s by default), run the check
and wave at the front camera:

```sh
ssh -T user@tablet "cat > /tmp/test-motion-detection.sh" < scripts/test-motion-detection.sh
ssh -t user@tablet "sh /tmp/test-motion-detection.sh 15"
```

`MOTION_DETECTED_OK` plus a `backlight on` line in the power-button log means
the whole chain works: sensor, CSI-2, DCAM, videobuf2, detector, `SIGUSR2`,
display. The tuning keys are documented in
[config.ini.example](../config/config.ini.example) and
[CAMERA.md](../docs/CAMERA.md).

## Rollback

- **The tablet still boots and SSH works.** Upload the backup from step 2
  and write it with the same flash script; a 16 MiB file needs no padding:

  ```sh
  ssh -T user@tablet "umask 077; cat > /tmp/backup.img" < mmcblk0p20-backup.img
  ssh -t user@tablet "sudo sh /tmp/tablet-flash-boot.sh /tmp/backup.img <sha256 of the backup>"
  ```

- **The tablet does not boot.** Boot TWRP (Power + Home + Volume Up), connect
  USB, allow debugging, and restore over ADB. The script writes only
  `/dev/block/mmcblk0p20`, asks for the token `RESTORE-SM-T560-P20` and
  verifies the whole partition afterwards:

  ```sh
  sh scripts/twrp-restore-boot.sh mmcblk0p20-backup.img <sha256 of the backup>
  ```

- **The camera misbehaves but the tablet is fine.** Switch the driver off
  without reflashing; the parameter is root-only:

  ```sh
  ssh -t user@tablet "sudo sh -c 'echo Y > /sys/module/sprd_dcam/parameters/gtelwifi_camera_disable'"
  ```

  Every later open of `/dev/video0` is refused with `EPERM` until the next
  boot or until you write `N` back.

## Module parameters

All three live under `/sys/module/` and are readable and writable by root
only. They apply to the next camera open.

- `sprd_dcam/parameters/gtelwifi_camera_disable`: `N` by default. `Y`
  refuses every open of the camera node.
- `sprd_sensor/parameters/gtelwifi_camera_csi_phy_id`: `4` by default,
  CSI PHY C. `1` is PHY A and `2` is PHY B; on this board both stay idle and
  the CSI-2 host status remains `0x200`.
- `sprd_dcam/parameters/gtelwifi_camera_yuv_pattern`: `2` by default, UYVY.
  `0` YUYV, `1` YVYU, `3` VYUY. Anything else falls back to UYVY.

## Troubleshooting

- **Boot loop after flashing.** Restore the backup from TWRP (Rollback above).
  Then compare the hash of the image you flashed with the one `export-boot.sh`
  printed; a stale package in the chroot is the usual cause.
- **`DCAM timeout.` and no frames.** The capture unit is armed but no start of
  frame arrives: wrong CSI PHY. The parameter must read `4`.
- **Frames arrive but the picture is flat grey with a ghost image in colour.**
  Wrong byte order. The YUV pattern parameter must read `2`.
- **`S_FMT GREY` fails with `EINVAL`.** Intended; GREY maps to a DCAM mode that
  was never verified. Applications fall through to NV21, the detector does so
  by itself.
- **`t560-motion-detector.py --probe` stops at `REQBUFS failed: Not a tty`.**
  The tablet is still running the stock kernel; check `uname -a`.
- **The detector is not running after a reboot.** `motion_detection` is still
  `off`, or the panel is not installed. `tablet-verify-camera.sh` prints both.
- **The kernel log fills with `DCAM: sof 1 wait`.** The image is older than
  r20; rebuild from this package.
- **`pmbootstrap export` says the package is not installed.** Run
  `export-boot.sh` again after a successful `build-kernel.sh`; it installs the
  exact `pkgver-rpkgrel` from the `APKBUILD` and fails on anything else.

## Checksums

| File | Size | SHA256 |
| --- | --- | --- |
| `boot/boot-sm-t560-camera-r20.img` | 13758464 | `0537fcf93154cba3850309880726f3c80e18970e2212a297f9ae980c33004cf3` |
| `/dev/mmcblk0p20` after flashing it (zero-padded to 16 MiB) | 16777216 | `7f12ee7612e49611d9500f19a05e7b7ee76f1d7e330fadbd545d5ca3c859dc84` |

`SHA256SUMS` lists every other file in this folder; `sha256sum -c SHA256SUMS`
from this directory checks them all.
