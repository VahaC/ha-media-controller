# Camera motion detection

The UI process does not perform camera analysis. On this ARMv7 tablet a
separate low-priority daemon is safer: a camera failure cannot freeze the music
controls, and the daemon can be stopped when the camera is not needed.

## Measured result on the SM-T560: the built-in camera cannot be used

The detection daemon is complete and tested, but the camera of this tablet
cannot deliver frames to any application under the postmarketOS 3.10.17
kernel. Measured on the device with `t560-motion-detector.py --probe`:

```text
driver=DCAM card=DCAM bus=DCAM--01
capabilities=0x04000001 device_caps=0x00000000
format[0] YUYV ... format[11] GREY ... format[12] JPEG
camera: the driver keeps its own frame rate (S_PARM failed: Invalid argument)
capture setup stops here: REQBUFS failed: Not a tty
```

`/dev/video0` is a thin shim over the Spreadtrum DCAM block. It advertises
`V4L2_CAP_STREAMING`, enumerates thirteen pixel formats, and accepts
`VIDIOC_S_FMT GREY` at 320x240, but it implements none of the buffer calls:

- `VIDIOC_REQBUFS` returns `ENOTTY` for MMAP, USERPTR, and DMABUF;
- `read()` returns end of file and `mmap()` on the node returns `ENODEV`;
- `VIDIOC_STREAMON` returns `ERANGE`, and the kernel logs
  `V4L2: Failed to start stream`;
- `bytesperline` and `sizeimage` come back as zero.

The real capture path belongs to the Android vendor stack: `/dev/sprd_sensor`,
`/dev/sprd_isp`, `/dev/sprd_scale`, and physically contiguous buffers whose
addresses the camera HAL passes to the driver. Reaching frames from a normal
user process would require porting a videobuf2-based driver for this SoC,
which is kernel work outside this repository. Sending speculative vendor
ioctls at the running driver is not a substitute: one such probe with an
unset buffer pointer rebooted the tablet.

Therefore `motion_detection` is `off` by default. The daemon stays in the
project: it enables the feature immediately on any camera that answers the
probe with `capture works`, for example a USB camera on the OTG port, and it
exits with a single explanatory line otherwise.

The firmware of this tablet is built from source, so the missing piece can be
added there. [CAMERA_FIRMWARE.md](CAMERA_FIRMWARE.md) lists exactly what the
kernel and the root filesystem must provide, and the acceptance test that
proves it.

## Implemented daemon

[t560-motion-detector.py](../scripts/t560-motion-detector.py) implements the
first stage described below.

1. It reads the tablet camera through V4L2 at 320x240 and 2.5 frames/s by
   default, using memory-mapped streaming buffers and only the luminance
   plane. `GREY`, `YUYV`, `UYVY`, `NV12`, `NV21`, `YU12`, and `YV12` are
   accepted; the first format the driver grants is used.
2. Every frame is reduced to a 16x12 grid of block averages. Averaging a few
   sampled pixels per block is the blur step and removes sensor noise without
   a filter pass over the whole image.
3. Consecutive frames are compared block by block. The median change of the
   whole frame is subtracted first, so a room light, daylight, or the
   backlight itself does not count as motion.
4. A frame counts as motion when `motion_area_percent` of the blocks changed
   by more than `pixel_threshold`. `motion_frames` consecutive motion frames
   are required before an event is reported, and `cooldown_seconds` limits how
   often events are sent.
5. The event is delivered as `SIGUSR2` to `t560-power-button.py`, which owns
   DPMS. That handler turns the display on when it is off, and postpones the
   `screen_off_seconds` timeout while motion continues.

This is classic motion detection, not face or object recognition. It avoids
OpenCV, TensorFlow, and neural-network runtimes, and it is realistic on the
legacy 3.10.17 ARMv7 kernel. The daemon uses only the Python standard library:
`ctypes`, `fcntl.ioctl`, `mmap`, and `select`.

## Configuration

The `[camera]` section of `config.ini` holds every setting; see
[config.ini.example](../config/config.ini.example) for the documented keys and
their ranges. `motion_detection=off` stops the daemon at start-up and leaves
the camera unused.

`motion_wake_grace_seconds` belongs to the same section but is read by the
button handler. It keeps the person who just pressed Power from immediately
waking the display again. After an automatic screen off, motion wakes the
display within a couple of seconds instead, because the delay then only has to
outlast the backlight transition itself.

## Identify the camera node

The daemon probes every `/dev/video*` node in ascending order and uses the
first one that accepts a supported format. Do not assume `/dev/video0`:
Samsung downstream camera drivers often expose several nodes, and some are not
capture devices. Set `device=` explicitly when the wrong sensor is selected.

The daemon reports every node itself, which needs no administrative access and
works even while `motion_detection` is off:

```sh
python3 "$HOME/.local/bin/t560-motion-detector.py" --probe
```

Each node prints its driver, its capabilities, its pixel formats, and the exact
V4L2 call at which the capture path stops. A usable camera ends with
`capture works` followed by the size of the first captured frame. `v4l2-ctl`
from `v4l-utils` gives the same information in more detail, but installing it
requires root:

```sh
apk add v4l-utils
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

The selected node, driver, and negotiated format are recorded in
`~/.local/state/motion-detector.log` at start-up.

## Later stages

Person or face recognition should only be considered after V4L2 capture and
CPU use have been measured on the physical tablet. A useful split is to let
the tablet detect motion and send a JPEG to a stronger LAN server for object
recognition. Publishing motion to Home Assistant over MQTT or a webhook is a
second candidate: the daemon already produces debounced events, so only the
transport would be added.
