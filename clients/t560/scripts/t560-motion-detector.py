#!/usr/bin/python3

"""Detect motion with the front camera and keep the tablet display awake.

The panel process must stay responsive, so camera capture runs in this
separate low-priority daemon: a camera failure cannot freeze the music
controls. Frames are captured through V4L2 at a low resolution and frame rate,
reduced to a coarse grid of block averages, and compared with the previous
frame. Confirmed motion is reported to the Power button handler with SIGUSR2.
That handler owns DPMS and decides whether to turn the display on or to
postpone the automatic screen off.
"""

import configparser
import ctypes
import errno
import os
import select
import signal
import sys
import time

try:  # Linux-only modules; the analysis helpers stay importable elsewhere.
    import fcntl
    import mmap
except ImportError:  # pragma: no cover - development hosts only
    fcntl = None
    mmap = None


CONFIG_FILE = "~/.config/t560-music-panel/config.ini"
POWER_BUTTON_NAME = "t560-power-button.py"

# The grid is the whole "blur" step: every block is the average of a few
# sampled pixels, which removes sensor noise without a real blur filter.
GRID_COLUMNS = 16
GRID_ROWS = 12
CELL_SAMPLES = 4

FRAME_TIMEOUT_SECONDS = 2.0
MAX_FRAME_FAILURES = 5
MAX_OPEN_ATTEMPTS = 5
OPEN_RETRY_SECONDS = 15.0
STOP_POLL_SECONDS = 0.25
MOTION_LOG_GAP_SECONDS = 10.0
BUFFER_COUNT = 2
NICE_INCREMENT = 5
MAX_ENUMERATED_FORMATS = 32

# Detection is off by default: the built-in camera of the SM-T560 cannot
# stream to userspace. See docs/CAMERA.md before switching it on.
DEFAULT_SETTINGS = {
    "motion_detection": False,
    "device": "auto",
    "width": 320,
    "height": 240,
    "frame_interval_ms": 400,
    "pixel_threshold": 12,
    "motion_area_percent": 8,
    "motion_frames": 2,
    "cooldown_seconds": 2,
}

# Inclusive limits for the integer keys of the [camera] section.
SETTING_LIMITS = {
    "width": (160, 640),
    "height": (120, 480),
    "frame_interval_ms": (100, 5000),
    "pixel_threshold": (2, 128),
    "motion_area_percent": (1, 100),
    "motion_frames": (1, 10),
    "cooldown_seconds": (1, 60),
}

TRUE_VALUES = {"1", "on", "true", "yes", "enabled"}
FALSE_VALUES = {"0", "off", "false", "no", "disabled"}

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_ANY = 0
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_STREAMING = 0x04000000
V4L2_CAP_DEVICE_CAPS = 0x80000000

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2


def log(message):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def four_cc(code):
    """Return the V4L2 pixel format constant of a four-character code."""
    return (
        ord(code[0])
        | ord(code[1]) << 8
        | ord(code[2]) << 16
        | ord(code[3]) << 24
    )


def four_cc_name(value):
    """Return the printable four-character code of a pixel format."""
    characters = [chr((value >> shift) & 0xFF) for shift in (0, 8, 16, 24)]
    return "".join(
        character if character.isprintable() else "?"
        for character in characters
    )


# Every supported format keeps the luminance samples in the first plane. The
# value is the byte offset of the first luminance sample and the distance in
# bytes between two luminance samples of one row.
PLANE_LAYOUTS = {
    four_cc("GREY"): (0, 1),
    four_cc("YUYV"): (0, 2),
    four_cc("YVYU"): (0, 2),
    four_cc("UYVY"): (1, 2),
    four_cc("VYUY"): (1, 2),
    four_cc("NV12"): (0, 1),
    four_cc("NV21"): (0, 1),
    four_cc("YU12"): (0, 1),
    four_cc("YV12"): (0, 1),
}

PREFERRED_FORMATS = ("GREY", "YUYV", "UYVY", "NV21", "NV12", "YU12", "YV12")


def parse_boolean(value, default, key):
    """Return the boolean meaning of a configuration value."""
    text = value.strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    log(f"WARNING: {key} is not a boolean: {value.strip()!r}")
    return default


def camera_settings(path=CONFIG_FILE):
    """Return the validated [camera] section with the defaults applied."""
    settings = dict(DEFAULT_SETTINGS)
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.expanduser(path), encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error) as error:
        log(f"WARNING: could not read {path}: {error}")
        return settings

    enabled = parser.get("camera", "motion_detection", fallback=None)
    if enabled is not None:
        settings["motion_detection"] = parse_boolean(
            enabled, DEFAULT_SETTINGS["motion_detection"], "motion_detection"
        )

    device = parser.get("camera", "device", fallback="").strip()
    if device:
        settings["device"] = device

    for key, (minimum, maximum) in SETTING_LIMITS.items():
        value = parser.get("camera", key, fallback=None)
        if value is None:
            continue
        try:
            number = int(value.strip())
        except ValueError:
            log(f"WARNING: {key} is not an integer: {value.strip()!r}")
            continue
        settings[key] = min(max(number, minimum), maximum)

    return settings


def sample_plan(width, height, stride, pixel_bytes=1, offset=0,
                columns=GRID_COLUMNS, rows=GRID_ROWS, samples=CELL_SAMPLES):
    """Pre-compute the byte slices averaged for every block of the grid.

    The plan is built once per camera format, so analysing a frame costs a
    fixed and small number of slice and sum operations.
    """
    columns = max(1, min(columns, width))
    rows = max(1, min(rows, height))
    plan = []
    for row in range(rows):
        top = row * height // rows
        bottom = max(top + 1, (row + 1) * height // rows)
        row_step = max(1, (bottom - top) // samples)
        row_positions = list(range(top, bottom, row_step))[:samples]
        for column in range(columns):
            left = column * width // columns
            right = max(left + 1, (column + 1) * width // columns)
            column_step = max(1, (right - left) // samples)
            last = min(right, left + column_step * samples)
            plan.append([
                (
                    offset + position * stride + left * pixel_bytes,
                    offset + position * stride + last * pixel_bytes,
                    column_step * pixel_bytes,
                )
                for position in row_positions
            ])
    return plan


def block_averages(frame, plan):
    """Return the average brightness of every block of the sampling plan."""
    averages = []
    for slices in plan:
        total = 0
        count = 0
        for start, stop, step in slices:
            samples = frame[start:stop:step]
            total += sum(samples)
            count += len(samples)
        averages.append(total // count if count else 0)
    return averages


def changed_blocks(previous, current, threshold):
    """Count the blocks that changed more than the whole frame did.

    Subtracting the median difference keeps a room light, daylight, or the
    backlight itself from being reported as motion, because such a change
    shifts every block by a similar amount.
    """
    differences = [
        current[index] - previous[index] for index in range(len(current))
    ]
    if not differences:
        return 0
    shift = sorted(differences)[len(differences) // 2]
    return sum(
        1 for difference in differences if abs(difference - shift) >= threshold
    )


def required_blocks(total, area_percent):
    """Return how many blocks must change before a frame counts as motion."""
    return max(1, -(-total * area_percent // 100))


class MotionTracker:
    """Turn per-frame block differences into debounced motion events."""

    def __init__(self, pixel_threshold, area_percent, frames, cooldown_seconds):
        self.pixel_threshold = pixel_threshold
        self.area_percent = area_percent
        self.frames = frames
        self.cooldown_seconds = cooldown_seconds
        self.previous = None
        self.streak = 0
        self.last_event = None

    def reset(self):
        """Forget the reference frame after a format or device change."""
        self.previous = None
        self.streak = 0

    def update(self, averages, now):
        """Return True when the caller should report a motion event."""
        previous = self.previous
        self.previous = averages
        if previous is None or len(previous) != len(averages):
            self.streak = 0
            return False

        changed = changed_blocks(previous, averages, self.pixel_threshold)
        if changed < required_blocks(len(averages), self.area_percent):
            self.streak = 0
            return False

        self.streak += 1
        if self.streak < self.frames:
            return False
        if (self.last_event is not None
                and now - self.last_event < self.cooldown_seconds):
            return False
        self.last_event = now
        return True


class PowerButtonNotifier:
    """Report motion to the Power button handler, which owns DPMS."""

    def __init__(self, name=POWER_BUTTON_NAME, proc="/proc"):
        self.name = name
        self.proc = proc
        self.pids = []

    def command(self, pid):
        """Return the argument vector of a process, or an empty list."""
        try:
            with open(f"{self.proc}/{pid}/cmdline", "rb") as handle:
                raw = handle.read()
        except OSError:
            return []
        return [
            argument.decode("utf-8", "replace")
            for argument in raw.split(b"\0") if argument
        ]

    def matches(self, pid):
        """Return True when the process still is the Power button handler.

        SIGUSR2 terminates a process that does not expect it, so an editor or
        a log viewer that merely mentions the file name must not match.
        """
        arguments = self.command(pid)
        if not arguments:
            return False
        program = os.path.basename(arguments[0])
        if program == self.name:
            return True
        if not program.startswith("python"):
            return False
        return any(os.path.basename(argument) == self.name
                   for argument in arguments[1:])

    def find(self):
        """Return the process IDs of the running Power button handler."""
        own = os.getpid()
        try:
            entries = os.listdir(self.proc)
        except OSError as error:
            log(f"WARNING: could not read {self.proc}: {error}")
            return []
        return [
            int(entry) for entry in sorted(entries)
            if entry.isdigit() and int(entry) != own and self.matches(int(entry))
        ]

    def notify(self):
        """Send SIGUSR2 to the handler; return True when it was delivered."""
        if not self.pids or not all(self.matches(pid) for pid in self.pids):
            self.pids = self.find()
        if not self.pids:
            log("WARNING: the Power button handler is not running")
            return False

        delivered = False
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGUSR2)
                delivered = True
            except OSError as error:
                log(f"WARNING: could not signal pid {pid}: {error}")
                self.pids = []
        return delivered


def _ioc(direction, number, size):
    """Return an ioctl request number of the V4L2 command group."""
    return (direction << 30) | (size << 16) | (ord("V") << 8) | number


class V4L2Capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_char * 16),
        ("card", ctypes.c_char * 32),
        ("bus_info", ctypes.c_char * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class V4L2FmtDesc(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("description", ctypes.c_char * 32),
        ("pixelformat", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]


class V4L2PixFormat(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelformat", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("bytesperline", ctypes.c_uint32),
        ("sizeimage", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("priv", ctypes.c_uint32),
    ]


class V4L2FormatUnion(ctypes.Union):
    _fields_ = [
        ("pix", V4L2PixFormat),
        ("raw_data", ctypes.c_uint8 * 200),
    ]


class V4L2Format(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("fmt", V4L2FormatUnion),
    ]


class V4L2Fract(ctypes.Structure):
    _fields_ = [
        ("numerator", ctypes.c_uint32),
        ("denominator", ctypes.c_uint32),
    ]


class V4L2CaptureParm(ctypes.Structure):
    _fields_ = [
        ("capability", ctypes.c_uint32),
        ("capturemode", ctypes.c_uint32),
        ("timeperframe", V4L2Fract),
        ("extendedmode", ctypes.c_uint32),
        ("readbuffers", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]


class V4L2StreamParmUnion(ctypes.Union):
    _fields_ = [
        ("capture", V4L2CaptureParm),
        ("raw_data", ctypes.c_uint8 * 200),
    ]


class V4L2StreamParm(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("parm", V4L2StreamParmUnion),
    ]


class V4L2RequestBuffers(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


class V4L2TimeVal(ctypes.Structure):
    # The tablet runs a 32-bit ARM kernel, where time_t is 32 bits wide.
    _fields_ = [
        ("tv_sec", ctypes.c_uint32),
        ("tv_usec", ctypes.c_uint32),
    ]


class V4L2TimeCode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class V4L2Buffer(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", V4L2TimeVal),
        ("timecode", V4L2TimeCode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        # Only the memory-mapped member of the union is used here.
        ("offset", ctypes.c_uint32),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


VIDIOC_QUERYCAP = _ioc(_IOC_READ, 0, ctypes.sizeof(V4L2Capability))
VIDIOC_ENUM_FMT = _ioc(_IOC_READ | _IOC_WRITE, 2,
                       ctypes.sizeof(V4L2FmtDesc))
VIDIOC_S_FMT = _ioc(_IOC_READ | _IOC_WRITE, 5, ctypes.sizeof(V4L2Format))
VIDIOC_REQBUFS = _ioc(_IOC_READ | _IOC_WRITE, 8,
                      ctypes.sizeof(V4L2RequestBuffers))
VIDIOC_QUERYBUF = _ioc(_IOC_READ | _IOC_WRITE, 9, ctypes.sizeof(V4L2Buffer))
VIDIOC_QBUF = _ioc(_IOC_READ | _IOC_WRITE, 15, ctypes.sizeof(V4L2Buffer))
VIDIOC_DQBUF = _ioc(_IOC_READ | _IOC_WRITE, 17, ctypes.sizeof(V4L2Buffer))
VIDIOC_STREAMON = _ioc(_IOC_WRITE, 18, ctypes.sizeof(ctypes.c_int))
VIDIOC_STREAMOFF = _ioc(_IOC_WRITE, 19, ctypes.sizeof(ctypes.c_int))
VIDIOC_S_PARM = _ioc(_IOC_READ | _IOC_WRITE, 22, ctypes.sizeof(V4L2StreamParm))


# A driver that answers these errors will answer them again after every
# retry: the ioctl is simply not implemented for this node.
PERMANENT_ERRNOS = frozenset(
    number for number in (
        getattr(errno, name, None)
        for name in ("ENOTTY", "ENODEV", "ENOSYS", "ENXIO", "EOPNOTSUPP",
                     "ENOTSUP", "EACCES", "EPERM")
    ) if number is not None
)


class CameraError(RuntimeError):
    """The camera node cannot deliver frames for motion detection.

    `permanent` marks a driver limitation that retrying cannot resolve, as
    opposed to a busy device or a transient failure.
    """

    def __init__(self, message, permanent=False):
        super().__init__(message)
        self.permanent = permanent


def _ioctl(handle, request, argument, label):
    """Run one V4L2 ioctl and name it when the driver refuses the call."""
    while True:
        try:
            return fcntl.ioctl(handle, request, argument)
        except InterruptedError:
            continue
        except OSError as error:
            raise CameraError(
                f"{label} failed: {error.strerror}",
                permanent=error.errno in PERMANENT_ERRNOS,
            ) from error


class Camera:
    """Minimal V4L2 capture that reads the luminance plane of the sensor."""

    def __init__(self, path, width, height, frame_interval_ms):
        self.path = path
        self.requested_width = width
        self.requested_height = height
        self.frame_interval_ms = frame_interval_ms
        self.fd = None
        self.buffers = []
        self.streaming = False
        self.card = ""
        self.width = width
        self.height = height
        self.stride = width
        self.pixel_bytes = 1
        self.plane_offset = 0
        self.required_bytes = 0
        self.format_name = ""

    def open(self):
        """Configure the device and start streaming."""
        if fcntl is None or mmap is None:
            raise CameraError("V4L2 capture requires Linux")

        self.fd = os.open(self.path, os.O_RDWR)
        self._query_capability()
        self._select_format()
        self._request_frame_interval()
        self._map_buffers()
        _ioctl(self.fd, VIDIOC_STREAMON,
               ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE), "STREAMON")
        self.streaming = True

    def _query_capability(self):
        capability = V4L2Capability()
        _ioctl(self.fd, VIDIOC_QUERYCAP, capability, "QUERYCAP")
        capabilities = capability.capabilities
        if capabilities & V4L2_CAP_DEVICE_CAPS:
            capabilities = capability.device_caps
        self.card = capability.card.decode("ascii", "replace")
        if not capabilities & V4L2_CAP_VIDEO_CAPTURE:
            raise CameraError("the node is not a capture device")
        if not capabilities & V4L2_CAP_STREAMING:
            raise CameraError("the node has no streaming support")

    def _select_format(self):
        """Ask for the first format whose luminance plane can be sampled."""
        rejected = []
        permanent = True
        for name in PREFERRED_FORMATS:
            image = V4L2Format()
            image.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            image.fmt.pix.width = self.requested_width
            image.fmt.pix.height = self.requested_height
            image.fmt.pix.pixelformat = four_cc(name)
            image.fmt.pix.field = V4L2_FIELD_ANY
            try:
                _ioctl(self.fd, VIDIOC_S_FMT, image, f"S_FMT {name}")
            except CameraError as error:
                rejected.append(f"{name} ({error})")
                permanent = permanent and error.permanent
                continue

            layout = PLANE_LAYOUTS.get(image.fmt.pix.pixelformat)
            if layout is None:
                rejected.append(four_cc_name(image.fmt.pix.pixelformat))
                continue

            self.plane_offset, self.pixel_bytes = layout
            self.width = image.fmt.pix.width
            self.height = image.fmt.pix.height
            self.stride = (image.fmt.pix.bytesperline
                           or self.width * self.pixel_bytes)
            self.required_bytes = self.stride * self.height
            self.format_name = four_cc_name(image.fmt.pix.pixelformat)
            return

        raise CameraError(
            "no supported pixel format: " + "; ".join(rejected), permanent)

    def _request_frame_interval(self):
        """Ask the driver for the analysis frame rate; failure is harmless."""
        parameters = V4L2StreamParm()
        parameters.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        parameters.parm.capture.timeperframe.numerator = self.frame_interval_ms
        parameters.parm.capture.timeperframe.denominator = 1000
        try:
            _ioctl(self.fd, VIDIOC_S_PARM, parameters, "S_PARM")
        except CameraError as error:
            log(f"camera: the driver keeps its own frame rate ({error})")

    def _map_buffers(self):
        request = V4L2RequestBuffers()
        request.count = BUFFER_COUNT
        request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        request.memory = V4L2_MEMORY_MMAP
        _ioctl(self.fd, VIDIOC_REQBUFS, request, "REQBUFS")
        if request.count < 1:
            raise CameraError("the driver granted no capture buffers",
                              permanent=True)

        for index in range(request.count):
            description = V4L2Buffer()
            description.index = index
            description.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            description.memory = V4L2_MEMORY_MMAP
            _ioctl(self.fd, VIDIOC_QUERYBUF, description, "QUERYBUF")
            self.buffers.append(mmap.mmap(
                self.fd,
                description.length,
                flags=mmap.MAP_SHARED,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
                offset=description.offset,
            ))
            _ioctl(self.fd, VIDIOC_QBUF, description, "QBUF")

    def read_frame(self, timeout):
        """Return one queued frame, or None when none arrived in time."""
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return None

        description = V4L2Buffer()
        description.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        description.memory = V4L2_MEMORY_MMAP
        _ioctl(self.fd, VIDIOC_DQBUF, description, "DQBUF")
        try:
            length = description.bytesused or self.required_bytes
            frame = self.buffers[description.index][:length]
        finally:
            _ioctl(self.fd, VIDIOC_QBUF, description, "QBUF")
        return frame

    def read_latest(self, timeout):
        """Return the newest frame and drop the older buffered ones."""
        frame = self.read_frame(timeout)
        if frame is None:
            return None
        while True:
            newer = self.read_frame(0)
            if newer is None:
                return frame
            frame = newer

    def close(self):
        if self.streaming:
            try:
                _ioctl(self.fd, VIDIOC_STREAMOFF,
                       ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE), "STREAMOFF")
            except CameraError as error:
                log(f"WARNING: could not stop the stream ({error})")
            self.streaming = False
        for buffer in self.buffers:
            buffer.close()
        self.buffers = []
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def camera_candidates(device, directory="/dev"):
    """Return the capture nodes to try, in ascending node order."""
    if device and device != "auto":
        return [device]
    try:
        names = [
            name for name in os.listdir(directory)
            if name.startswith("video") and name[5:].isdigit()
        ]
    except OSError as error:
        log(f"WARNING: could not list {directory}: {error}")
        return []
    return [
        f"{directory}/{node}"
        for node in sorted(names, key=lambda node: int(node[5:]))
    ]


def open_camera(settings):
    """Open the configured camera, probing every node when set to auto.

    Returns the camera and whether every failure was a permanent driver
    limitation, so that the caller does not retry a node that will never
    deliver frames.
    """
    candidates = camera_candidates(settings["device"])
    if not candidates:
        log("camera: no video capture node is present")
        return None, True

    permanent = True
    for path in candidates:
        camera = Camera(path, settings["width"], settings["height"],
                        settings["frame_interval_ms"])
        try:
            camera.open()
        except CameraError as error:
            permanent = permanent and error.permanent
            log(f"camera: {path} [{camera.card}] is not usable ({error})")
            camera.close()
            continue
        except OSError as error:
            permanent = False
            log(f"camera: {path} cannot be opened ({error})")
            camera.close()
            continue
        log(f"camera: {path} [{camera.card}] {camera.format_name} "
            f"{camera.width}x{camera.height} stride {camera.stride}")
        return camera, False
    return None, permanent


def describe_node(path, settings):
    """Print what one capture node reports and where the capture path stops.

    This replaces v4l2-ctl, which cannot be installed without administrative
    access, and it uses no ioctl that the daemon does not use itself.
    """
    log(f"probe {path}")
    try:
        handle = os.open(path, os.O_RDWR)
    except OSError as error:
        log(f"  cannot open the node ({error})")
        return

    try:
        capability = V4L2Capability()
        _ioctl(handle, VIDIOC_QUERYCAP, capability, "QUERYCAP")
        log(f"  driver={capability.driver.decode('ascii', 'replace')} "
            f"card={capability.card.decode('ascii', 'replace')} "
            f"bus={capability.bus_info.decode('ascii', 'replace')}")
        log(f"  capabilities=0x{capability.capabilities:08x} "
            f"device_caps=0x{capability.device_caps:08x}")

        for index in range(MAX_ENUMERATED_FORMATS):
            description = V4L2FmtDesc()
            description.index = index
            description.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            try:
                _ioctl(handle, VIDIOC_ENUM_FMT, description, "ENUM_FMT")
            except CameraError:
                break
            supported = description.pixelformat in PLANE_LAYOUTS
            log(f"  format[{index}] {four_cc_name(description.pixelformat)} "
                f"{description.description.decode('ascii', 'replace')}"
                f"{'' if supported else ' (not usable for motion detection)'}")
    except CameraError as error:
        log(f"  {error}")
    finally:
        os.close(handle)

    camera = Camera(path, settings["width"], settings["height"],
                    settings["frame_interval_ms"])
    try:
        camera.open()
    except (CameraError, OSError) as error:
        log(f"  capture setup stops here: {error}")
        camera.close()
        return

    log(f"  capture works: {camera.format_name} "
        f"{camera.width}x{camera.height} stride {camera.stride}")
    frame = camera.read_latest(FRAME_TIMEOUT_SECONDS)
    if frame is None:
        log("  no frame arrived within the timeout")
    else:
        log(f"  first frame: {len(frame)} bytes, "
            f"{camera.required_bytes} needed")
    camera.close()


def probe(settings):
    """Report every capture node instead of starting the detection loop."""
    candidates = camera_candidates(settings["device"])
    if not candidates:
        log("no video capture node is present")
        return 1
    for path in candidates:
        describe_node(path, settings)
    return 0


class Stopper:
    """Turn SIGTERM and SIGINT into a flag that is checked between frames."""

    def __init__(self):
        self.requested = False

    def install(self):
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, self._handle)

    def _handle(self, signum, _frame):
        self.requested = True
        log(f"stopping on signal {signum}")

    def wait(self, seconds):
        """Sleep in short steps so that a stop request is noticed quickly."""
        deadline = time.monotonic() + seconds
        while not self.requested:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, STOP_POLL_SECONDS))


def run(settings, stopper, notifier):
    """Capture frames until stopped and report every confirmed motion event."""
    tracker = MotionTracker(
        settings["pixel_threshold"],
        settings["motion_area_percent"],
        settings["motion_frames"],
        settings["cooldown_seconds"],
    )
    interval = settings["frame_interval_ms"] / 1000.0
    camera = None
    plan = []
    failures = 0
    attempts = 0
    last_report = None

    try:
        while not stopper.requested:
            if camera is None:
                camera, permanent = open_camera(settings)
                if camera is None:
                    attempts += 1
                    if permanent:
                        log("ERROR: the camera driver does not support "
                            "streaming capture from userspace; motion "
                            "detection stops. See docs/CAMERA.md")
                        return 1
                    if attempts >= MAX_OPEN_ATTEMPTS:
                        log("ERROR: no usable camera; motion detection stops")
                        return 1
                    stopper.wait(OPEN_RETRY_SECONDS)
                    continue
                attempts = 0
                failures = 0
                plan = sample_plan(camera.width, camera.height, camera.stride,
                                   camera.pixel_bytes, camera.plane_offset)
                tracker.reset()

            frame = None
            try:
                frame = camera.read_latest(FRAME_TIMEOUT_SECONDS)
            except OSError as error:
                log(f"WARNING: capture failed ({error})")

            if frame is None or len(frame) < camera.required_bytes:
                failures += 1
                if failures >= MAX_FRAME_FAILURES:
                    log("camera: reopening after repeated capture failures")
                    camera.close()
                    camera = None
                stopper.wait(interval)
                continue

            failures = 0
            now = time.monotonic()
            if tracker.update(block_averages(frame, plan), now):
                notifier.notify()
                if last_report is None:
                    log("motion: detected")
                last_report = now
            elif (last_report is not None
                  and now - last_report >= MOTION_LOG_GAP_SECONDS):
                log(f"motion: none for {MOTION_LOG_GAP_SECONDS:.0f}s")
                last_report = None

            stopper.wait(interval)
    finally:
        if camera is not None:
            camera.close()
    return 0


def main():
    settings = camera_settings()
    if "--probe" in sys.argv[1:]:
        # Diagnostics must work even when the feature is switched off.
        return probe(settings)

    if not settings["motion_detection"]:
        log("motion detection is disabled; set [camera] "
            "motion_detection=on in config.ini to enable it")
        return 0

    try:
        os.nice(NICE_INCREMENT)
    except OSError as error:  # pragma: no cover - depends on the host limits
        log(f"WARNING: could not lower the process priority ({error})")

    stopper = Stopper()
    stopper.install()
    log(
        "started: device={device}, {width}x{height}, "
        "every {frame_interval_ms} ms, {motion_area_percent}% of blocks, "
        "threshold {pixel_threshold}, {motion_frames} frames, "
        "cooldown {cooldown_seconds}s".format(**settings)
    )
    return run(settings, stopper, PowerButtonNotifier())


if __name__ == "__main__":
    sys.exit(main())
