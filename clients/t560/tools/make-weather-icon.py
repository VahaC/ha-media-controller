#!/usr/bin/python3

"""Render the weather icon a weather block draws.

The room icons are alpha masks and nothing else: the panel paints them
through Cairo with a colour it chooses at draw time, so the pixels carry
shape and no colour of their own. See `icon_set` in
`clients/t560/src/panel_ui.c`.

The glyph is a sun behind a cloud: a circle in the upper left and a rounded
cloud over the lower right of it. It is drawn at four times the output size
and scaled down, which is what gives it the same soft edges as the artwork
it sits beside.

Run from `clients/t560`:

    python3 tools/make-weather-icon.py
"""

import os

from PIL import Image, ImageDraw

SIZE = 128
SUPERSAMPLE = 4
OUTPUT_PATH = os.path.join("data", "icons", "weather.png")

# Everything below is in output pixels; the drawing scales them itself.
SUN_CENTER = (48.0, 48.0)
SUN_RADIUS = 22.0

# Cloud puffs as circles, plus a base box to join them.
CLOUD_CIRCLES = (
    (52.0, 78.0, 18.0),
    (72.0, 68.0, 24.0),
    (94.0, 78.0, 17.0),
)
CLOUD_BOX = (52.0, 78.0, 96.0, 98.0)
CLOUD_BOX_RADIUS = 10.0


def scaled_box(box, scale):
    return tuple(value * scale for value in box)


def draw_mask(scale):
    """Draw the glyph as an alpha mask at `scale` times the output size."""
    mask = Image.new("L", (SIZE * scale, SIZE * scale), 0)
    draw = ImageDraw.Draw(mask)

    cx, cy = SUN_CENTER[0] * scale, SUN_CENTER[1] * scale
    radius = SUN_RADIUS * scale
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=255,
    )
    for x, y, radius in CLOUD_CIRCLES:
        cx, cy, radius = x * scale, y * scale, radius * scale
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=255,
        )
    draw.rounded_rectangle(
        scaled_box(CLOUD_BOX, scale),
        radius=CLOUD_BOX_RADIUS * scale,
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
