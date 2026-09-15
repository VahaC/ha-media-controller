#!/usr/bin/env python3
"""Capture a settled frame from the SM-T560 front camera through V4L2.

Run on the tablet as the panel user, with the motion detector stopped (the
driver serves one streaming client at a time):

    pkill -f t560-motion-detector.py
    python3 tablet-capture-frame.py /tmp/frame.nv21 20

The V4L2 client is the Camera class of t560-motion-detector.py, installed by
the panel at ~/.local/bin, so this script has no dependency of its own. It
reads the requested number of frames and keeps the last one: the first frame
after stream start is cut mid-frame and the exposure needs a moment to settle.
The output is NV21 at the detector's resolution, 115200 bytes for 320x240.
Convert it on the PC with nv21-to-png.py.
"""

import hashlib
import os
import runpy
import sys
import time

DETECTOR = os.path.expanduser("~/.local/bin/t560-motion-detector.py")
DEVICE = "/dev/video0"


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "/tmp/frame.nv21"
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    if not os.path.exists(DETECTOR):
        print("ERROR: %s is missing; install the panel first" % DETECTOR, file=sys.stderr)
        return 2
    if os.system("pgrep -f '[t]560-motion-detector' > /dev/null") == 0:
        print("ERROR: the motion detector is running and holds the camera; stop it first", file=sys.stderr)
        return 2

    module = runpy.run_path(DETECTOR)
    settings = module["camera_settings"]()
    camera = module["Camera"](DEVICE, settings["width"], settings["height"], settings["frame_interval_ms"])
    try:
        camera.open()
        print("STREAM_READY format=%s size=%dx%d stride=%d" % (
            camera.format_name, camera.width, camera.height, camera.stride), flush=True)
        started = time.monotonic()
        frames = 0
        distinct = 0
        last = None
        last_digest = None
        while frames < target:
            frame = camera.read_latest(10.0 if frames == 0 else 2.0)
            if frame is None:
                break
            frames += 1
            if frames == 1:
                print("FIRST_FRAME_AFTER=%.3fs bytes=%d" % (time.monotonic() - started, len(frame)), flush=True)
            digest = hashlib.sha256(frame).hexdigest()
            if digest != last_digest:
                distinct += 1
            last, last_digest = frame, digest
            time.sleep(0.03)
        if not last:
            print("ERROR: no frame arrived", file=sys.stderr)
            return 1
        with open(output, "wb") as handle:
            handle.write(last)
        print("FRAMES read=%d distinct=%d elapsed=%.3fs" % (frames, distinct, time.monotonic() - started))
        print("FRAME_SAVED path=%s format=%s width=%d height=%d bytes=%d sha256=%s" % (
            output, camera.format_name, camera.width, camera.height, len(last), last_digest))
        return 0
    except Exception as error:  # report the V4L2 call that failed, then exit 1
        print("ERROR: capture failed: %s" % error, file=sys.stderr)
        return 1
    finally:
        camera.close()


if __name__ == "__main__":
    sys.exit(main())
