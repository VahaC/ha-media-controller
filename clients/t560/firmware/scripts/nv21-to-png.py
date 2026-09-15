#!/usr/bin/env python3
"""Turn a raw NV21 frame into two PNG files and print its statistics.

    python3 nv21-to-png.py frame.nv21 [width height] [out.png] [out-luma.png]

Pure Python, no Pillow or ffmpeg needed. The statistics tell a real frame
from a broken one: a healthy picture has a wide luma range (0 to about 240)
and chroma centred near 128. A flat luma plane near 127 with the picture
hiding in the chroma plane means the capture unit was programmed for the
wrong byte order (YUYV instead of UYVY).
"""

import hashlib
import struct
import sys
import zlib


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    width = int(sys.argv[2]) if len(sys.argv) > 3 else 320
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 240
    out_rgb = sys.argv[4] if len(sys.argv) > 4 else src + ".png"
    out_luma = sys.argv[5] if len(sys.argv) > 5 else src + "-luma.png"

    data = open(src, "rb").read()
    ysize = width * height
    if len(data) != ysize * 3 // 2:
        sys.exit("ERROR: %d bytes is not an NV21 frame of %dx%d (%d expected)" % (len(data), width, height, ysize * 3 // 2))
    y = data[:ysize]
    vu = data[ysize:]
    v = vu[0::2]
    u = vu[1::2]
    print("bytes=%d sha256=%s" % (len(data), hashlib.sha256(data).hexdigest()))
    print("Y: min=%d max=%d mean=%.1f" % (min(y), max(y), sum(y) / len(y)))
    print("V: min=%d max=%d mean=%.1f  U: min=%d max=%d mean=%.1f" % (
        min(v), max(v), sum(v) / len(v), min(u), max(u), sum(u) / len(u)))

    def clamp(value):
        return 0 if value < 0 else 255 if value > 255 else int(value)

    def png(path, color, rowfn):
        raw = b"".join(b"\x00" + rowfn(r) for r in range(height))

        def chunk(tag, body):
            payload = tag + body
            return struct.pack(">I", len(body)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

        header = struct.pack(">IIBBBBB", width, height, 8, 2 if color else 0, 0, 0, 0)
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

    def rgb_row(r):
        out = bytearray()
        for c in range(width):
            luma = y[r * width + c]
            i = (r // 2) * width + (c // 2) * 2
            cv = vu[i] - 128
            cu = vu[i + 1] - 128
            out += bytes((clamp(luma + 1.402 * cv), clamp(luma - 0.344 * cu - 0.714 * cv), clamp(luma + 1.772 * cu)))
        return bytes(out)

    png(out_rgb, True, rgb_row)
    png(out_luma, False, lambda r: y[r * width:(r + 1) * width])
    print("wrote %s and %s" % (out_rgb, out_luma))


if __name__ == "__main__":
    main()
