#!/usr/bin/python3

"""Render the skin previews the two layout editors show.

Every panel offers more than one layout, and the name of one says nothing
about what it looks like. The editor each panel serves therefore shows a
picture beside the list. The pictures are **static** and generated here: the
alternative — drawing a live preview — would mean a second implementation of
every layout, in JavaScript, kept in step with the real one by hand.

Each image is a schematic of the layout it names, drawn from the same numbers
the client draws with: the palettes in `clients/t560/src/panel_ui.c` and the
widget geometry in `firmware/media-controller-ui.yaml`. It is a diagram of the
arrangement, not a screenshot of a running device, which is what makes it
reproducible from this file alone.

Which skins exist is the client's own vocabulary, and the list lives on the
client profile in `custom_components/media_controller/profiles.py`. The names
below are that list; a skin added there needs a drawing here, and a name with
no image simply gets no preview rather than a broken one.

Weight matters. The ESP32 previews are linked into flash beside the editor, so
each image is small, downsampled from a supersampled render, and quantised to
a palette rather than saved as truecolour.

Run from the repository root:

    python3 tools/make-skin-previews.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

# Supersampling factor. Everything is drawn at this multiple of the output
# size and reduced with a Lanczos filter, so a 2 px arc stroke on a 144 px
# preview is still a clean line rather than an aliased staircase.
SUPERSAMPLE = 4

# How many colours a saved preview keeps. The images are flat shapes over a
# gradient, so a small palette costs nothing visible and roughly halves the
# file; the previews are linked into ESP32 flash beside the editor.
PALETTE_COLORS = 48

# The T560 screen is a fixed 800x1219 portrait panel. The preview keeps that
# proportion, so the arrangement in the picture is the arrangement on the
# tablet.
T560_SIZE = (128, 195)
T560_OUTPUT = os.path.join("clients", "t560", "data", "skins")

# The ESP32-S3 screen is a fixed 480x480 square.
ESP32_SIZE = (144, 144)
ESP32_OUTPUT = os.path.join("components", "media_controller_grid", "previews")


# --------------------------------------------------------------- primitives


def hex_color(value: int) -> tuple[int, int, int]:
    """Return one 0xRRGGBB constant as a PIL colour."""
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def mix(first: int, second: int, amount: float) -> tuple[int, int, int]:
    """Blend two 0xRRGGBB constants, `amount` of the second."""
    a = hex_color(first)
    b = hex_color(second)
    return tuple(int(round(a[i] + (b[i] - a[i]) * amount)) for i in range(3))


def vertical_gradient(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    start: int,
    end: int,
) -> None:
    """Fill a box with a top-to-bottom gradient, one scanline at a time."""
    left, top, right, bottom = box
    height = max(1.0, bottom - top)
    for offset in range(int(height) + 1):
        y = top + offset
        draw.rectangle(
            (left, y, right, y + 1), fill=mix(start, end, offset / height)
        )


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    radius: float,
    fill: int | None = None,
    outline: int | None = None,
    width: float = 1.0,
) -> None:
    """Draw a rounded rectangle from 0xRRGGBB constants."""
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=None if fill is None else hex_color(fill),
        outline=None if outline is None else hex_color(outline),
        width=max(1, int(round(width))),
    )


def circle(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    radius: float,
    fill: int | None = None,
    outline: int | None = None,
    width: float = 1.0,
) -> None:
    """Draw a circle from a centre and a radius."""
    x, y = center
    draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=None if fill is None else hex_color(fill),
        outline=None if outline is None else hex_color(outline),
        width=max(1, int(round(width))),
    )


def arc(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    radius: float,
    start: float,
    end: float,
    color: int,
    width: float,
) -> None:
    """Draw an arc the way LVGL states one: a centre, a radius and degrees."""
    x, y = center
    draw.arc(
        (x - radius, y - radius, x + radius, y + radius),
        start=start,
        end=end,
        fill=hex_color(color),
        width=max(1, int(round(width))),
    )


def transport_row(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    spacing: float,
    radius: float,
    accent: int,
    ghost: int,
) -> None:
    """Draw the previous / play / next row every layout ends with."""
    circle(draw, (center_x - spacing, y), radius * 0.72, fill=ghost)
    circle(draw, (center_x, y), radius, fill=accent)
    circle(draw, (center_x + spacing, y), radius * 0.72, fill=ghost)


def render(size: tuple[int, int], paint) -> Image.Image:
    """Draw one preview supersampled and reduce it to its output size."""
    width, height = size
    large = Image.new(
        "RGB", (width * SUPERSAMPLE, height * SUPERSAMPLE), hex_color(0x000000)
    )
    paint(ImageDraw.Draw(large), float(SUPERSAMPLE))
    return large.resize(size, Image.LANCZOS)


def save(image: Image.Image, directory: str, name: str) -> None:
    """Quantise and write one preview, reporting what it cost."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name + ".png")
    quantised = image.quantize(
        colors=PALETTE_COLORS, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG
    )
    quantised.save(path, format="PNG", optimize=True)
    print(f"{path}: {os.path.getsize(path)} bytes")


# ------------------------------------------------------------- T560 skins
#
# The palettes are PANEL_PALETTES in clients/t560/src/panel_ui.c and the
# proportions are the 800x1219 screen the panel is laid out for.


def t560_modern(draw: ImageDraw.ImageDraw, s: float) -> None:
    """The default skin: dark navy, teal accent, album art over a card."""
    width = 128.0 * s
    height = 195.0 * s

    vertical_gradient(draw, (0, 0, width, height), 0x102039, 0x050A12)
    # The header, and the navigation bar the room page shares with it.
    draw.rectangle((0, 0, width, 14 * s), fill=hex_color(0x0C1420))
    draw.rectangle((0, height - 20 * s, width, height), fill=hex_color(0x0C1420))

    # Album art, square and centred, over the player card.
    rounded(draw, (20 * s, 26 * s, 108 * s, 114 * s), 6 * s, fill=0x1D3550)
    rounded(
        draw,
        (20 * s, 26 * s, 108 * s, 114 * s),
        6 * s,
        outline=0x3B5678,
        width=1 * s,
    )

    # Title and artist.
    rounded(draw, (28 * s, 122 * s, 100 * s, 128 * s), 3 * s, fill=0xF1F6FD)
    rounded(draw, (40 * s, 132 * s, 88 * s, 136 * s), 2 * s, fill=0x8FA9C7)

    # Progress line, filled in the accent.
    draw.rectangle(
        (20 * s, 143 * s, 108 * s, 145 * s), fill=hex_color(0x1C293B)
    )
    draw.rectangle((20 * s, 143 * s, 78 * s, 145 * s), fill=hex_color(0x42D8CF))

    transport_row(draw, 64 * s, 158 * s, 24 * s, 9 * s, 0x42D8CF, 0x213856)

    # The navigation bar: four pages, the current one lit.
    for index in range(4):
        left = (10 + index * 28) * s
        rounded(
            draw,
            (left, height - 15 * s, left + 22 * s, height - 6 * s),
            3 * s,
            fill=0x42D8CF if index == 0 else 0x213856,
        )


def t560_cassette(draw: ImageDraw.ImageDraw, s: float) -> None:
    """The second skin: the faceplate of a three-head cassette deck."""
    width = 128.0 * s
    height = 195.0 * s

    vertical_gradient(draw, (0, 0, width, height), 0x2B2E33, 0x141619)
    draw.rectangle((0, 0, width, 14 * s), fill=hex_color(0x15171A))
    draw.rectangle((0, height - 20 * s, width, height), fill=hex_color(0x15171A))

    # The well, and the cassette shell loaded into it.
    rounded(draw, (14 * s, 24 * s, 114 * s, 96 * s), 4 * s, fill=0x0A0806)
    rounded(draw, (20 * s, 30 * s, 108 * s, 90 * s), 3 * s, fill=0x3A3F46)
    rounded(
        draw,
        (20 * s, 30 * s, 108 * s, 90 * s),
        3 * s,
        outline=0x555C66,
        width=1 * s,
    )
    # The two hubs, one full and one nearly empty, and the tape between them.
    draw.rectangle((38 * s, 56 * s, 90 * s, 64 * s), fill=hex_color(0x1F2228))
    for x, pack in ((44 * s, 13 * s), (84 * s, 7 * s)):
        circle(draw, (x, 60 * s), pack, fill=0x241A0D)
        circle(draw, (x, 60 * s), 5 * s, fill=0xD8C0A0)
        circle(draw, (x, 60 * s), 2 * s, fill=0x0A0806)

    # The engraved legends and the amber VU meter.
    rounded(draw, (24 * s, 100 * s, 104 * s, 105 * s), 2 * s, fill=0xA9B1BB)
    for index in range(10):
        left = (24 + index * 8) * s
        lit = index < 6
        rounded(
            draw,
            (left, 110 * s, left + 5 * s, 118 * s),
            1 * s,
            fill=0xFFAE3D if lit else 0x2A2E34,
        )

    # Transport, drawn as the deck's square mechanical keys.
    for index in range(4):
        left = (18 + index * 25) * s
        rounded(
            draw,
            (left, 130 * s, left + 20 * s, 148 * s),
            2 * s,
            fill=0x7D5722 if index == 1 else 0x3A3F46,
        )

    for index in range(4):
        left = (10 + index * 28) * s
        rounded(
            draw,
            (left, height - 15 * s, left + 22 * s, height - 6 * s),
            3 * s,
            fill=0xFFAE3D if index == 0 else 0x3A3F46,
        )


# ------------------------------------------------------------ ESP32 skins
#
# The three home layouts of firmware/media-controller-ui.yaml, at the
# proportions of the 480x480 screen. Sizes below are the widget sizes in that
# file scaled by 144/480, so an arc that is 400 px across there is 120 px
# across here.


def esp32_classic(draw: ImageDraw.ImageDraw, s: float) -> None:
    """page_player: album art full bleed under a wide progress arc."""
    side = 144.0 * s

    # The album art fills the screen and is dimmed by image_recolor.
    vertical_gradient(draw, (0, 0, side, side), 0x243048, 0x0A0A14)
    rounded(draw, (18 * s, 14 * s, 126 * s, 122 * s), 8 * s, fill=0x151A2B)

    # progress_arc: 400 px across, centred at y=-30, sweeping 150 to 30.
    center = (72 * s, 63 * s)
    arc(draw, center, 60 * s, 150, 390, 0x1A1A35, 1.5 * s)
    arc(draw, center, 60 * s, 150, 300, 0x00CFFF, 1.5 * s)

    # The Queue pill above the decoration card.
    rounded(draw, (51 * s, 9 * s, 93 * s, 20 * s), 5 * s, fill=0x2A2A44)

    # btn_decoration: 320x190, and the title and artist on it.
    rounded(draw, (24 * s, 45 * s, 120 * s, 102 * s), 8 * s, fill=0x14162A)
    rounded(draw, (40 * s, 55 * s, 104 * s, 62 * s), 3 * s, fill=0xFFFFFF)
    rounded(draw, (50 * s, 68 * s, 94 * s, 73 * s), 2 * s, fill=0x5588CC)
    draw.rectangle((40 * s, 84 * s, 104 * s, 87 * s), fill=hex_color(0x2A2A44))
    draw.rectangle((40 * s, 84 * s, 82 * s, 87 * s), fill=hex_color(0x00CFFF))

    transport_row(draw, 72 * s, 116 * s, 26 * s, 10 * s, 0x00CFFF, 0x2A2A44)


def esp32_minimal_ring(draw: ImageDraw.ImageDraw, s: float) -> None:
    """page_player_minimal: a circular album art disc inside a 270 arc."""
    side = 144.0 * s

    draw.rectangle((0, 0, side, side), fill=hex_color(0x05060C))

    # progress_arc_m: 300 px across, centred at y=-78, sweeping 135 to 45.
    center = (72 * s, 48.6 * s)
    arc(draw, center, 45 * s, 135, 405, 0x1A1A35, 1.5 * s)
    arc(draw, center, 45 * s, 135, 320, 0x00CFFF, 1.5 * s)

    # art_clip_m: a 244 px disc, clipped by its container.
    circle(draw, center, 36.6 * s, fill=0x0D0F16)
    circle(draw, center, 36.6 * s, fill=0x22304C)
    circle(draw, center, 22 * s, fill=0x101828)
    circle(draw, center, 6 * s, fill=0x05060C)

    # progress_dot_m, the knob a non-adjustable arc does not draw itself.
    angle = math.radians(320)
    circle(
        draw,
        (center[0] + 45 * s * math.cos(angle), center[1] + 45 * s * math.sin(angle)),
        3 * s,
        fill=0x00CFFF,
    )

    rounded(draw, (44 * s, 96 * s, 100 * s, 102 * s), 3 * s, fill=0xFFFFFF)
    rounded(draw, (54 * s, 106 * s, 90 * s, 110 * s), 2 * s, fill=0x5588CC)

    transport_row(draw, 72 * s, 125 * s, 30 * s, 10 * s, 0x00CFFF, 0x141830)


def esp32_cover_card(draw: ImageDraw.ImageDraw, s: float) -> None:
    """page_player_cover: a rounded cover square over a linear progress bar."""
    side = 144.0 * s

    draw.rectangle((0, 0, side, side), fill=hex_color(0x05060C))

    # The two ghost buttons in the top corners.
    rounded(draw, (3 * s, 2 * s, 16 * s, 15 * s), 3 * s, fill=0x141830)
    rounded(draw, (128 * s, 2 * s, 141 * s, 15 * s), 3 * s, fill=0x141830)

    # art_clip_c: the same 244 px source as the ring, clipped square.
    rounded(draw, (35 * s, 12 * s, 109 * s, 86 * s), 7 * s, fill=0x22304C)
    rounded(draw, (46 * s, 28 * s, 98 * s, 70 * s), 4 * s, fill=0x101828)

    rounded(draw, (36 * s, 94 * s, 108 * s, 101 * s), 3 * s, fill=0xFFFFFF)
    rounded(draw, (48 * s, 105 * s, 96 * s, 110 * s), 2 * s, fill=0x5588CC)

    # progress_bar_c, with the elapsed and remaining times beside it.
    rounded(draw, (28 * s, 117 * s, 116 * s, 121 * s), 2 * s, fill=0x141830)
    rounded(draw, (28 * s, 117 * s, 84 * s, 121 * s), 2 * s, fill=0x00CFFF)

    # slider_volume_c.
    rounded(draw, (28 * s, 130 * s, 116 * s, 135 * s), 2 * s, fill=0x141830)
    rounded(draw, (28 * s, 130 * s, 70 * s, 135 * s), 2 * s, fill=0x00CFFF)
    circle(draw, (70 * s, 132.5 * s), 4 * s, fill=0x00CFFF)


# The name each drawing answers to. These are the contract's own spellings,
# which is what the client reports on /api/skins and what the file is served
# as; see the skin table in docs/CONTRACT.md.
T560_SKINS = {"modern": t560_modern, "cassette": t560_cassette}
ESP32_SKINS = {
    "classic": esp32_classic,
    "minimal_ring": esp32_minimal_ring,
    "cover_card": esp32_cover_card,
}


def main() -> None:
    for name, paint in T560_SKINS.items():
        save(render(T560_SIZE, paint), T560_OUTPUT, name)
    for name, paint in ESP32_SKINS.items():
        save(render(ESP32_SIZE, paint), ESP32_OUTPUT, name)


if __name__ == "__main__":
    main()
