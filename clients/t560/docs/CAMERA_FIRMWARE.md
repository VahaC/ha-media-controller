# Firmware requirements for camera motion detection

This document lists what the postmarketOS firmware of the SM-T560 must provide
so that [t560-motion-detector.py](../scripts/t560-motion-detector.py) can
detect motion. The daemon itself is finished and needs no change: it uses the
standard V4L2 streaming API and nothing else. The measurement that led to this
document is in [CAMERA.md](CAMERA.md).

Nothing here requires a new user-space camera stack. The goal is a
`/dev/video*` node that behaves like any ordinary V4L2 capture device.

## Measured state of the current build

Kernel `3.10.17 #8-postmarketOS`, node `/dev/video0`, driver name `dcam`,
registered under `/sys/devices/virtual/video4linux/video0`.

| V4L2 call | Result today | Needed |
| --- | --- | --- |
| `VIDIOC_QUERYCAP` | works, reports `0x04000001` | keep, plus `device_caps` |
| `VIDIOC_ENUM_FMT` | works, 13 formats | keep |
| `VIDIOC_S_FMT` | accepts `GREY` 320x240 | must also fill `bytesperline`, `sizeimage` |
| `VIDIOC_S_PARM` | `EINVAL` | optional |
| `VIDIOC_REQBUFS` | `ENOTTY` for MMAP, USERPTR, DMABUF | **must work** |
| `VIDIOC_QUERYBUF` / `QBUF` / `DQBUF` | not reachable | **must work** |
| `VIDIOC_STREAMON` | `ERANGE`, kernel logs `V4L2: Failed to start stream` | **must work** |
| `read()` on the node | returns end of file | optional |
| `mmap()` on the node | `ENODEV` | **must work** (through videobuf2) |

The driver advertises `V4L2_CAP_STREAMING` without implementing any part of
it. The frame addresses are currently supplied by the Android camera HAL
through vendor ioctls on `/dev/sprd_sensor`, `/dev/sprd_isp`, and
`/dev/sprd_scale`; there is no HAL on postmarketOS, so nothing ever programs a
buffer address and `STREAMON` fails.

## 1. Kernel: give the DCAM node videobuf2 streaming

This is the substantial item. Inside the existing `dcam` V4L2 driver:

- create a `struct vb2_queue` per capture path with
  `io_modes = VB2_MMAP | VB2_READ`, `type = V4L2_BUF_TYPE_VIDEO_CAPTURE`,
  `timestamp_flags = V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC`;
- use `vb2_dma_contig_memops` (simplest, needs CMA below), or
  `vb2_dma_sg_memops` together with the existing `mm` IOMMU
  (`/dev/sprd_iommu_mm`) if contiguous memory is too expensive;
- point `vidioc_reqbufs`, `vidioc_querybuf`, `vidioc_qbuf`, `vidioc_dqbuf`,
  `vidioc_streamon`, `vidioc_streamoff`, and the file operations `mmap` and
  `poll` at the matching `vb2_ioctl_*` / `vb2_fop_*` helpers;
- in `.buf_queue`, program the DCAM frame address from
  `vb2_dma_contig_plane_dma_addr(vb, 0)` instead of the address the HAL used
  to pass in. This is the line that replaces the vendor ioctl path and the
  reason `STREAMON` currently returns `-ERANGE`;
- in the frame-done interrupt, call `vb2_buffer_done(vb, VB2_BUF_STATE_DONE)`
  with `bytesused` set.

Two buffers of 320x240 are enough for this project, but do not special-case
the size: `REQBUFS` must honour the count the application asks for.

## 2. Kernel: power the sensor from the driver

Without an Android HAL, nothing performs the sensor power-up, clock, and
`s_stream` sequence. The driver must do it itself when the node is opened and
streaming starts, through the sensor subdev registered from the device tree
(`v4l2_subdev_call(sensor, core, s_power, 1)` and
`v4l2_subdev_call(sensor, video, s_stream, 1)`).

Confirm in the device tree that the **front** sensor node, its regulators, its
reset and power-down GPIOs, and its MCLK are enabled, and that the sensor
driver is built in. After boot, its probe line must be visible:

```sh
dmesg | grep -i -E "sensor|dcam"
```

The current build shows no sensor probe line at boot, only DCAM register and
reset messages when the node is opened.

## 3. Kernel: report the format correctly

`VIDIOC_S_FMT` and `VIDIOC_G_FMT` currently return `bytesperline = 0` and
`sizeimage = 0`. Standard applications compute their buffer layout from those
fields. Fill them in `try_fmt`/`s_fmt`/`g_fmt` for every advertised format.

Also set `device_caps` and add `V4L2_CAP_DEVICE_CAPS` to `capabilities`, and
advertise `V4L2_CAP_READWRITE` only if `VB2_READ` is enabled.

## 4. Kernel configuration

Make sure the build enables:

```text
CONFIG_MEDIA_SUPPORT=y
CONFIG_MEDIA_CAMERA_SUPPORT=y
CONFIG_VIDEO_DEV=y
CONFIG_VIDEO_V4L2=y
CONFIG_VIDEOBUF2_CORE=y
CONFIG_VIDEOBUF2_DMA_CONTIG=y     # or CONFIG_VIDEOBUF2_DMA_SG=y
CONFIG_CMA=y
CONFIG_DMA_CMA=y
CONFIG_CMA_SIZE_MBYTES=8          # 320x240 needs far less; 8 MB is safe
CONFIG_IKCONFIG=y
CONFIG_IKCONFIG_PROC=y            # exposes /proc/config.gz for diagnosis
```

The last two are not needed for the camera. They are worth adding because the
current build has no `/proc/config.gz`, so the configuration of a running
tablet cannot be inspected at all.

## 5. Root filesystem

- `libxscrnsaver` (`/usr/lib/libXss.so.1`). It is missing today, so the panel's
  button handler cannot read the X idle timer and leaves the inactivity
  timeout to the X server. With the library present, the handler owns the
  timeout, logs every screen-off decision, and postpones the timeout while the
  camera reports motion.
- `v4l-utils` is optional; `t560-motion-detector.py --probe` reports the same
  information without root.
- The panel user must stay in the `video` group, since `/dev/video0` is
  `root:video 0660`. This already holds.
- There is no `apk` binary in the current rootfs, so every package has to be
  part of the image.

## Acceptance test

Flash the firmware, then run on the tablet:

```sh
python3 "$HOME/.local/bin/t560-motion-detector.py" --probe
```

The node must report `capture works` and a first frame whose size matches the
requested one, for example:

```text
camera: /dev/video0 [dcam] GREY 320x240 stride 320
  capture works: GREY 320x240 stride 320
  first frame: 76800 bytes, 76800 needed
```

Then set `motion_detection=on` in the `[camera]` section of `config.ini` and
restart the daemon. Nothing else in this repository has to change.

## If the driver work is not worth it

Two alternatives, both worse:

- Drive the vendor ioctl API from user space. Every ioctl number and structure
  is in the kernel tree, but the sequence also needs ION allocations, sensor
  power sequencing, and ISP setup, and it breaks with every kernel revision.
  Sending a speculative vendor ioctl at the running driver already rebooted
  the tablet once, so this path has to be developed against the source, not by
  probing.
- Attach a UVC camera to the OTG port. `CONFIG_USB_VIDEO_CLASS=y` in the
  firmware is then the only kernel change, and the daemon works unmodified.
