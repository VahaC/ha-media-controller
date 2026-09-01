#!/usr/bin/python3

"""Render the T560 Music Panel launcher icon at every installed size.

The icon is a flat vector design: a portrait tablet outline containing a play
triangle and three equaliser bars, drawn in the teal accent of the panel UI on
the dark navy background of the panel UI. Geometry is defined in a 1024 pixel
reference square and rendered with supersampling, so every size stays crisp.

Run from the repository root:

    python3 tools/make-app-icon.py
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter


REFERENCE = 1024
SUPERSAMPLE = 3
OUTPUT_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
MASTER_SIZE = 1024
ICON_NAME = "t560-music-panel"
OUTPUT_ROOT = os.path.join("data", "icons", "hicolor")
MASTER_PATH = os.path.join("data", "icons", ICON_NAME + ".png")

# Background of the panel UI, darkened towards the corners.
BACKGROUND_CENTER = (13, 26, 41)
BACKGROUND_EDGE = (1, 3, 5)
# Teal accent of the panel UI, as a vertical gradient over the glyph.
GLYPH_TOP = (69, 220, 212)
GLYPH_BOTTOM = (95, 233, 226)
GLOW_COLOR = (117, 241, 233)

SQUIRCLE_RADIUS = 229.0

TABLET_BOX = (287.4, 218.5, 736.7, 812.1)
TABLET_RADIUS = 37.1
TABLET_STROKE = 18.1

TRIANGLE = ((439.8, 346.3), (439.8, 544.2), (608.9, 445.2))
TRIANGLE_RADIUS = 14.0

BAR_BASELINE = 723.9
BARS = (
    (416.8, 454.7, 630.7),
    (493.4, 531.3, 581.3),
    (571.8, 609.7, 620.0),
)


def scaled(value, scale):
    return value * scale


def radial_background(size):
    """Build the dark radial gradient at a small size and upscale it."""
    coarse = 96
    gradient = Image.new("RGB", (coarse, coarse))
    pixels = gradient.load()
    centre = (coarse - 1) / 2.0
    limit = centre * math.sqrt(2.0)
    for y in range(coarse):
        for x in range(coarse):
            distance = math.hypot(x - centre, y - centre) / limit
            # Concentrate the glow near the centre of the icon.
            weight = max(0.0, 1.0 - distance) ** 1.6
            pixels[x, y] = tuple(
                round(edge + (center - edge) * weight)
                for center, edge in zip(BACKGROUND_CENTER, BACKGROUND_EDGE)
            )
    return gradient.resize((size, size), Image.LANCZOS)


def vertical_gradient(size, top_color, bottom_color):
    column = Image.new("RGB", (1, size))
    pixels = column.load()
    for y in range(size):
        weight = y / max(1, size - 1)
        pixels[0, y] = tuple(
            round(top + (bottom - top) * weight)
            for top, bottom in zip(top_color, bottom_color)
        )
    return column.resize((size, size), Image.NEAREST)


def rounded_polygon(points, radius):
    """Inset polygon vertices so a stroked outline keeps the original size."""
    count = len(points)
    inset = []
    for index in range(count):
        current = points[index]
        previous = points[(index - 1) % count]
        following = points[(index + 1) % count]

        first = (previous[0] - current[0], previous[1] - current[1])
        second = (following[0] - current[0], following[1] - current[1])
        first_length = math.hypot(*first)
        second_length = math.hypot(*second)
        first = (first[0] / first_length, first[1] / first_length)
        second = (second[0] / second_length, second[1] / second_length)

        bisector = (first[0] + second[0], first[1] + second[1])
        bisector_length = math.hypot(*bisector)
        bisector = (bisector[0] / bisector_length, bisector[1] / bisector_length)

        half_angle = math.acos(max(-1.0, min(1.0, first[0] * bisector[0]
                                             + first[1] * bisector[1])))
        distance = radius / max(1e-6, math.sin(half_angle))
        inset.append((current[0] + bisector[0] * distance,
                      current[1] + bisector[1] * distance))
    return inset


def draw_glyph(size):
    """Draw the glyph as a white mask on a transparent square."""
    scale = size / REFERENCE
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    left, top, right, bottom = (scaled(value, scale) for value in TABLET_BOX)
    stroke = max(1, round(scaled(TABLET_STROKE, scale)))
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=scaled(TABLET_RADIUS, scale),
        outline=255,
        width=stroke,
    )

    triangle_radius = scaled(TRIANGLE_RADIUS, scale)
    triangle = [(scaled(x, scale), scaled(y, scale)) for x, y in TRIANGLE]
    inset = rounded_polygon(triangle, triangle_radius)
    draw.polygon(inset, fill=255)
    # Round the corners with explicit discs and butt-capped edges. The
    # "curve" joint of ImageDraw.line notches acute corners such as the apex.
    width = max(1, round(triangle_radius * 2))
    for index, point in enumerate(inset):
        following = inset[(index + 1) % len(inset)]
        draw.line((point, following), fill=255, width=width)
        draw.ellipse(
            (point[0] - triangle_radius, point[1] - triangle_radius,
             point[0] + triangle_radius, point[1] + triangle_radius),
            fill=255,
        )

    baseline = scaled(BAR_BASELINE, scale)
    for bar_left, bar_right, bar_top in BARS:
        bar_left = scaled(bar_left, scale)
        bar_right = scaled(bar_right, scale)
        bar_top = scaled(bar_top, scale)
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_right, baseline),
            radius=(bar_right - bar_left) / 2.0,
            fill=255,
        )
    return mask


def render_master():
    size = MASTER_SIZE * SUPERSAMPLE
    scale = size / REFERENCE

    icon = radial_background(size).convert("RGBA")

    glyph_mask = draw_glyph(size)

    # A wide soft halo and a tight bright halo, matching the neon reference.
    glow = Image.new("RGBA", (size, size), GLOW_COLOR + (0,))
    for blur, strength in ((scaled(34.0, scale), 0.55),
                           (scaled(11.0, scale), 0.75)):
        halo = glyph_mask.filter(ImageFilter.GaussianBlur(blur))
        halo = halo.point(lambda value, s=strength: round(value * s))
        glow.putalpha(halo)
        icon = Image.alpha_composite(icon, glow)

    fill = vertical_gradient(size, GLYPH_TOP, GLYPH_BOTTOM).convert("RGBA")
    fill.putalpha(glyph_mask)
    icon = Image.alpha_composite(icon, fill)

    # Clip the finished square to the rounded application-icon silhouette.
    silhouette = Image.new("L", (size, size), 0)
    ImageDraw.Draw(silhouette).rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=scaled(SQUIRCLE_RADIUS, scale),
        fill=255,
    )
    icon.putalpha(silhouette)
    return icon.resize((MASTER_SIZE, MASTER_SIZE), Image.LANCZOS)


def main():
    master = render_master()
    os.makedirs(os.path.dirname(MASTER_PATH), exist_ok=True)
    master.save(MASTER_PATH)
    print("wrote", MASTER_PATH)

    for size in OUTPUT_SIZES:
        directory = os.path.join(OUTPUT_ROOT, "%dx%d" % (size, size), "apps")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, ICON_NAME + ".png")
        master.resize((size, size), Image.LANCZOS).save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
