#!/usr/bin/python3

"""Render the second batch of card icons the registry groups draw.

The room icons are alpha masks and nothing else: the panel paints them
through Cairo with a colour it chooses at draw time, so the pixels carry
shape and no colour of their own. See `icon_set` in
`clients/t560/src/panel_ui.c`.

Every glyph is drawn as a bold filled silhouette at four times the output
size and scaled down, which is what gives it the same soft edges as the
artwork it sits beside. Holes (a speaker cone, a camera lens, radiator
slots) are cut back out in black. One script draws the whole batch rather
than one script per icon, because twenty-four files that all do the same
thing would be noise; the technique is the one `make-blind-icon.py` and
`make-weather-icon.py` established.

Run from `clients/t560`:

    python3 tools/make-room-icons.py

Then, from the repository root, run `python tools/make-icon-assets.py`,
which copies the PNGs into the integration and renders the variant the
ESP32 draws. Finally add a row per icon to `ICONS` in
`custom_components/media_controller/icon_catalog.py`.
"""

import math
import os

from PIL import Image, ImageDraw

SIZE = 128
SUPERSAMPLE = 4
OUTPUT_DIR = os.path.join("data", "icons")

WHITE = 255
CLEAR = 0


def s(coords, scale):
    """Scale output-pixel coordinates to the drawing surface."""
    if isinstance(coords[0], (tuple, list)):
        return [tuple(value * scale for value in point) for point in coords]
    return tuple(value * scale for value in coords)


def rr(draw, box, scale, radius, fill=WHITE):
    """Draw a filled rounded rectangle given in output pixels."""
    draw.rounded_rectangle(s(box, scale), radius=radius * scale, fill=fill)


def ell(draw, box, scale, fill=WHITE):
    """Draw a filled ellipse given in output pixels."""
    draw.ellipse(s(box, scale), fill=fill)


def bar(draw, center, scale, half_length, width, angle_deg, fill=WHITE):
    """Draw a thick bar through `center` at `angle_deg` clockwise from east."""
    angle = math.radians(angle_deg)
    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    cx, cy = center
    hx, hy = dx * half_length, dy * half_length
    ox, oy = nx * width / 2.0, ny * width / 2.0
    points = [
        (cx + hx + ox, cy + hy + oy),
        (cx + hx - ox, cy + hy - oy),
        (cx - hx - ox, cy - hy - oy),
        (cx - hx + ox, cy - hy + oy),
    ]
    draw.polygon(s(points, scale), fill=fill)


def new_surface(scale):
    """Return a blank mask and its drawing context."""
    mask = Image.new("L", (SIZE * scale, SIZE * scale), 0)
    return mask, ImageDraw.Draw(mask)


# ------------------------------------------------------------------ lights


def draw_bulb(draw, scale):
    ell(draw, (36.0, 12.0, 92.0, 68.0), scale)
    draw.rectangle(s((50.0, 62.0, 78.0, 80.0), scale), fill=WHITE)
    rr(draw, (52.0, 78.0, 76.0, 98.0), scale, 6.0)
    rr(draw, (59.0, 100.0, 69.0, 108.0), scale, 4.0)


def draw_ceiling_lamp(draw, scale):
    rr(draw, (50.0, 8.0, 78.0, 20.0), scale, 5.0)
    draw.rectangle(s((60.0, 20.0, 68.0, 48.0), scale), fill=WHITE)
    ell(draw, (22.0, 44.0, 106.0, 100.0), scale)
    draw.rectangle(s((22.0, 72.0, 106.0, 100.0), scale), fill=CLEAR)
    ell(draw, (56.0, 72.0, 72.0, 88.0), scale)


def draw_floor_lamp(draw, scale):
    draw.polygon(s([(46.0, 12.0), (82.0, 12.0), (90.0, 54.0), (38.0, 54.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((60.0, 54.0, 68.0, 104.0), scale), fill=WHITE)
    rr(draw, (44.0, 102.0, 84.0, 114.0), scale, 6.0)


def draw_wall_lamp(draw, scale):
    rr(draw, (16.0, 34.0, 30.0, 94.0), scale, 6.0)
    draw.rectangle(s((30.0, 52.0, 62.0, 62.0), scale), fill=WHITE)
    draw.rectangle(s((60.0, 38.0, 70.0, 56.0), scale), fill=WHITE)
    ell(draw, (44.0, 52.0, 96.0, 92.0), scale)
    draw.rectangle(s((44.0, 72.0, 96.0, 92.0), scale), fill=CLEAR)
    ell(draw, (60.0, 72.0, 76.0, 88.0), scale)


# ---------------------------------------------------------------- switches


def draw_plug(draw, scale):
    draw.rectangle(s((46.0, 20.0, 54.0, 46.0), scale), fill=WHITE)
    draw.rectangle(s((74.0, 20.0, 82.0, 46.0), scale), fill=WHITE)
    rr(draw, (34.0, 44.0, 94.0, 94.0), scale, 14.0)
    draw.rectangle(s((59.0, 94.0, 69.0, 114.0), scale), fill=WHITE)


def draw_tv(draw, scale):
    rr(draw, (14.0, 32.0, 114.0, 92.0), scale, 12.0)
    draw.rectangle(s((58.0, 92.0, 70.0, 100.0), scale), fill=WHITE)
    rr(draw, (42.0, 100.0, 86.0, 110.0), scale, 5.0)


def draw_speaker(draw, scale):
    rr(draw, (36.0, 14.0, 92.0, 114.0), scale, 10.0)
    ell(draw, (52.0, 28.0, 76.0, 52.0), scale, fill=CLEAR)
    ell(draw, (46.0, 64.0, 82.0, 100.0), scale, fill=CLEAR)


def draw_camera(draw, scale):
    draw.rectangle(s((42.0, 34.0, 66.0, 50.0), scale), fill=WHITE)
    rr(draw, (18.0, 48.0, 110.0, 102.0), scale, 12.0)
    ell(draw, (44.0, 58.0, 82.0, 96.0), scale, fill=CLEAR)
    ell(draw, (58.0, 72.0, 68.0, 82.0), scale)
    rr(draw, (88.0, 58.0, 100.0, 70.0), scale, 4.0, fill=CLEAR)


def draw_bell(draw, scale):
    ell(draw, (58.0, 24.0, 70.0, 36.0), scale)
    ell(draw, (32.0, 36.0, 96.0, 94.0), scale)
    draw.rectangle(s((32.0, 65.0, 96.0, 94.0), scale), fill=CLEAR)
    rr(draw, (26.0, 94.0, 102.0, 106.0), scale, 6.0)


# ----------------------------------------------------------------- climate


def draw_thermometer(draw, scale):
    rr(draw, (53.0, 10.0, 75.0, 82.0), scale, 11.0)
    ell(draw, (43.0, 72.0, 85.0, 114.0), scale)


def draw_thermostat(draw, scale):
    rr(draw, (30.0, 30.0, 98.0, 98.0), scale, 18.0)
    ell(draw, (44.0, 44.0, 84.0, 84.0), scale, fill=CLEAR)
    ell(draw, (59.0, 59.0, 69.0, 69.0), scale)
    draw.rectangle(s((61.0, 36.0, 67.0, 46.0), scale), fill=CLEAR)


def draw_heater(draw, scale):
    draw.rectangle(s((30.0, 94.0, 42.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 94.0, 98.0, 108.0), scale), fill=WHITE)
    rr(draw, (20.0, 38.0, 108.0, 96.0), scale, 10.0)
    for left in (36.0, 52.0, 68.0, 84.0):
        draw.rectangle(s((left, 48.0, left + 8.0, 86.0), scale), fill=CLEAR)


# ------------------------------------------------------------------ covers


def draw_curtain(draw, scale):
    rr(draw, (14.0, 20.0, 114.0, 30.0), scale, 5.0)
    ell(draw, (8.0, 17.0, 22.0, 33.0), scale)
    ell(draw, (106.0, 17.0, 120.0, 33.0), scale)
    draw.polygon(s([(26.0, 30.0), (54.0, 30.0), (48.0, 106.0), (18.0, 106.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(74.0, 30.0), (102.0, 30.0), (110.0, 106.0), (80.0, 106.0)],
                   scale), fill=WHITE)
    # Fold shadows cut out of each drape, which is what stops two straight
    # panels reading as a gate.
    for left in (30.0, 40.0, 82.0, 92.0):
        draw.rectangle(s((left, 38.0, left + 4.0, 98.0), scale), fill=CLEAR)


def draw_garage(draw, scale):
    rr(draw, (18.0, 26.0, 110.0, 110.0), scale, 6.0)
    draw.rectangle(s((28.0, 36.0, 100.0, 100.0), scale), fill=CLEAR)
    for top in (52.0, 69.0, 86.0):
        draw.rectangle(s((28.0, top, 100.0, top + 7.0), scale), fill=WHITE)


# ----------------------------------------------------------------- weather


def draw_sun(draw, scale):
    ell(draw, (45.0, 45.0, 83.0, 83.0), scale)
    for angle in range(0, 360, 45):
        radians = math.radians(angle)
        dx, dy = math.cos(radians), math.sin(radians)
        mid = 53.0
        half = 11.0
        cx, cy = 64.0 + dx * mid, 64.0 + dy * mid
        nx, ny = -dy, dx
        width = 9.0
        draw.polygon(
            s([(cx + dx * half + nx * width / 2.0,
                cy + dy * half + ny * width / 2.0),
               (cx + dx * half - nx * width / 2.0,
                cy + dy * half - ny * width / 2.0),
               (cx - dx * half - nx * width / 2.0,
                cy - dy * half - ny * width / 2.0),
               (cx - dx * half + nx * width / 2.0,
                cy - dy * half + ny * width / 2.0)], scale),
            fill=WHITE)


def draw_moon(draw, scale):
    ell(draw, (32.0, 24.0, 98.0, 100.0), scale)
    ell(draw, (54.0, 14.0, 120.0, 90.0), scale, fill=CLEAR)


def draw_cloud(draw, scale):
    for x, y, radius in ((42.0, 72.0, 20.0), (64.0, 60.0, 27.0),
                         (88.0, 72.0, 18.0)):
        ell(draw, (x - radius, y - radius, x + radius, y + radius), scale)
    rr(draw, (40.0, 72.0, 90.0, 102.0), scale, 12.0)


def draw_rain(draw, scale):
    for x, y, radius in ((46.0, 42.0, 13.0), (62.0, 34.0, 17.0),
                         (78.0, 42.0, 12.0)):
        ell(draw, (x - radius, y - radius, x + radius, y + radius), scale)
    rr(draw, (44.0, 42.0, 80.0, 60.0), scale, 9.0)
    for x in (48.0, 64.0, 80.0):
        draw.line(s((x, 72.0, x - 8.0, 96.0), scale), fill=WHITE, width=8)


def draw_snow(draw, scale):
    for angle in (0.0, 60.0, 120.0):
        bar(draw, (64.0, 66.0), scale, 38.0, 9.0, angle)
    ell(draw, (56.0, 58.0, 72.0, 74.0), scale)


# ----------------------------------------------------------------- sensors


def draw_motion(draw, scale):
    # A walking figure: head, torso, one arm and two legs, with filled
    # joints so the limbs read as one shape.
    ell(draw, (70.0, 24.0, 94.0, 48.0), scale)
    draw.line(s((66.0, 56.0, 60.0, 88.0), scale), fill=WHITE, width=15)
    draw.line(s((66.0, 62.0, 42.0, 74.0), scale), fill=WHITE, width=13)
    draw.line(s((60.0, 88.0, 42.0, 110.0), scale), fill=WHITE, width=13)
    draw.line(s((60.0, 88.0, 82.0, 108.0), scale), fill=WHITE, width=13)
    ell(draw, (59.0, 49.0, 73.0, 63.0), scale)
    ell(draw, (53.0, 81.0, 67.0, 95.0), scale)


def draw_door(draw, scale):
    rr(draw, (34.0, 14.0, 94.0, 114.0), scale, 6.0)
    draw.rectangle(s((42.0, 22.0, 68.0, 106.0), scale), fill=WHITE)
    ell(draw, (59.0, 58.0, 65.0, 64.0), scale, fill=CLEAR)


def draw_window(draw, scale):
    rr(draw, (22.0, 22.0, 106.0, 106.0), scale, 8.0)
    draw.rectangle(s((32.0, 32.0, 96.0, 96.0), scale), fill=CLEAR)
    draw.rectangle(s((59.0, 32.0, 69.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((32.0, 59.0, 96.0, 69.0), scale), fill=WHITE)


def draw_lock(draw, scale):
    ell(draw, (36.0, 16.0, 92.0, 80.0), scale)
    ell(draw, (50.0, 30.0, 78.0, 64.0), scale, fill=CLEAR)
    rr(draw, (30.0, 62.0, 98.0, 112.0), scale, 10.0)
    ell(draw, (57.0, 76.0, 71.0, 90.0), scale, fill=CLEAR)
    draw.rectangle(s((60.0, 86.0, 68.0, 100.0), scale), fill=CLEAR)


def draw_battery(draw, scale):
    draw.rectangle(s((102.0, 56.0, 114.0, 72.0), scale), fill=WHITE)
    rr(draw, (14.0, 42.0, 104.0, 86.0), scale, 10.0)
    draw.rectangle(s((26.0, 54.0, 42.0, 74.0), scale), fill=CLEAR)
    draw.rectangle(s((50.0, 54.0, 66.0, 74.0), scale), fill=CLEAR)


GLYPHS = {
    "bulb": draw_bulb,
    "ceiling-lamp": draw_ceiling_lamp,
    "floor-lamp": draw_floor_lamp,
    "wall-lamp": draw_wall_lamp,
    "plug": draw_plug,
    "tv": draw_tv,
    "speaker": draw_speaker,
    "camera": draw_camera,
    "bell": draw_bell,
    "thermometer": draw_thermometer,
    "thermostat": draw_thermostat,
    "heater": draw_heater,
    "curtain": draw_curtain,
    "garage": draw_garage,
    "sun": draw_sun,
    "moon": draw_moon,
    "cloud": draw_cloud,
    "rain": draw_rain,
    "snow": draw_snow,
    "motion": draw_motion,
    "door": draw_door,
    "window": draw_window,
    "lock": draw_lock,
    "battery": draw_battery,
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, glyph in GLYPHS.items():
        mask, draw = new_surface(SUPERSAMPLE)
        glyph(draw, SUPERSAMPLE)
        mask = mask.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        # Black with the shape in the alpha channel, exactly as the other
        # room icons are stored: the colour is the panel's to choose.
        icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        icon.putalpha(mask)
        path = os.path.join(OUTPUT_DIR, name + ".png")
        icon.save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
