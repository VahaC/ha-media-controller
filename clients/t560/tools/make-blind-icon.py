#!/usr/bin/python3

"""Render the blind icon a cover card draws.

The room icons are alpha masks and nothing else: the panel paints them
through Cairo with a colour it chooses at draw time, so the pixels carry
shape and no colour of their own. See `icon_set` in
`clients/t560/src/panel_ui.c`.

The glyph is a window with a roller blind in it: a frame, a headrail across
the top of it, three slats, and a bottom rail with a pull. It is drawn at
four times the output size and scaled down, which is what gives it the same
soft edges as the artwork it sits beside.

Run from `clients/t560`:

    python3 tools/make-blind-icon.py
"""

import os

from PIL import Image, ImageDraw

SIZE = 128
SUPERSAMPLE = 4
OUTPUT_PATH = os.path.join("data", "icons", "blind.png")

# Everything below is in output pixels; the drawing scales them itself.
FRAME_BOX = (10.0, 10.0, 118.0, 116.0)
FRAME_RADIUS = 13.0
FRAME_STROKE = 7.0

HEADRAIL_BOX = (24.0, 26.0, 104.0, 38.0)
HEADRAIL_RADIUS = 5.0

SLAT_LEFT = 30.0
SLAT_RIGHT = 98.0
SLAT_HEIGHT = 8.0
SLAT_RADIUS = 4.0
SLAT_TOPS = (48.0, 62.0, 76.0)

BOTTOM_RAIL_BOX = (26.0, 88.0, 102.0, 98.0)
BOTTOM_RAIL_RADIUS = 5.0

# The pull below the rail, which is what says the thing hangs and is drawn
# down rather than being a stack of shelves.
PULL_BOX = (60.0, 100.0, 68.0, 108.0)
PULL_RADIUS = 4.0


def scaled(box, scale):
    return tuple(value * scale for value in box)


def draw_mask(scale):
    """Draw the glyph as an alpha mask at `scale` times the output size."""
    mask = Image.new("L", (SIZE * scale, SIZE * scale), 0)
    draw = ImageDraw.Draw(mask)

    draw.rounded_rectangle(
        scaled(FRAME_BOX, scale),
        radius=FRAME_RADIUS * scale,
        outline=255,
        width=int(round(FRAME_STROKE * scale)),
    )
    draw.rounded_rectangle(
        scaled(HEADRAIL_BOX, scale),
        radius=HEADRAIL_RADIUS * scale,
        fill=255,
    )
    for top in SLAT_TOPS:
        draw.rounded_rectangle(
            scaled((SLAT_LEFT, top, SLAT_RIGHT, top + SLAT_HEIGHT), scale),
            radius=SLAT_RADIUS * scale,
            fill=255,
        )
    draw.rounded_rectangle(
        scaled(BOTTOM_RAIL_BOX, scale),
        radius=BOTTOM_RAIL_RADIUS * scale,
        fill=255,
    )
    draw.rounded_rectangle(
        scaled(PULL_BOX, scale),
        radius=PULL_RADIUS * scale,
        fill=255,
    )
    return mask


def main():
    mask = draw_mask(SUPERSAMPLE).resize(
        (SIZE, SIZE), Image.Resampling.LANCZOS
    )
    # Black with the shape in the alpha channel, exactly as the other room
    # icons are stored: the colour is the panel's to choose.
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.putalpha(mask)
    icon.save(OUTPUT_PATH)
    print("wrote", OUTPUT_PATH)


if __name__ == "__main__":
    main()
