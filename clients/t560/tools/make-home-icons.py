#!/usr/bin/python3

"""Render the third batch of card icons: the full home set.

Same technique and same style as `make-room-icons.py` — bold filled alpha
masks drawn at four times the output size and scaled down — extended to one
glyph per everyday home device, so every registry group has something to
choose from. A separate file only to keep either one readable.

Run from `clients/t560`:

    python3 tools/make-home-icons.py

Then, from the repository root, run `python tools/make-icon-assets.py` and
add a row per icon to `ICONS` in
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
    draw.polygon(
        s([(cx + hx + ox, cy + hy + oy),
           (cx + hx - ox, cy + hy - oy),
           (cx - hx - ox, cy - hy - oy),
           (cx - hx + ox, cy - hy + oy)], scale),
        fill=fill)


def blade(draw, center, scale, length, width, angle_deg, fill=WHITE):
    """Draw a one-sided blade from `center` out at `angle_deg`."""
    angle = math.radians(angle_deg)
    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    cx, cy = center
    draw.polygon(
        s([(cx, cy),
           (cx + dx * length + nx * width / 2.0,
            cy + dy * length + ny * width / 2.0),
           (cx + dx * length - nx * width / 2.0,
            cy + dy * length - ny * width / 2.0)], scale),
        fill=fill)


def ring(draw, box, scale, width, fill=WHITE):
    """Draw a stroked ellipse ring given in output pixels."""
    x0, y0, x1, y1 = box
    ell(draw, box, scale, fill=fill)
    ell(draw, (x0 + width, y0 + width, x1 - width, y1 - width), scale,
        fill=CLEAR)


def ray_fan(draw, center, scale, radius_in, radius_out, width, angles,
            fill=WHITE):
    """Draw short rays around `center` at the given angles."""
    for angle in angles:
        radians = math.radians(angle)
        dx, dy = math.cos(radians), math.sin(radians)
        mid = (radius_in + radius_out) / 2.0
        bar(draw, (center[0] + dx * mid, center[1] + dy * mid), scale,
            (radius_out - radius_in) / 2.0, width, angle, fill=fill)


def cloud_puffs(draw, scale, puffs, base_box, base_radius):
    """Draw a cloud from circles and a joining base box."""
    for x, y, radius in puffs:
        ell(draw, (x - radius, y - radius, x + radius, y + radius), scale)
    rr(draw, base_box, scale, base_radius)


def new_surface(scale):
    """Return a blank mask and its drawing context."""
    mask = Image.new("L", (SIZE * scale, SIZE * scale), 0)
    return mask, ImageDraw.Draw(mask)


# ------------------------------------------------------------------ lights


def draw_chandelier(draw, scale):
    rr(draw, (54.0, 8.0, 74.0, 18.0), scale, 5.0)
    draw.rectangle(s((61.0, 18.0, 67.0, 44.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 48.0, 94.0, 56.0), scale), fill=WHITE)
    for left, top in ((40.0, 28.0), (61.0, 24.0), (82.0, 28.0)):
        draw.rectangle(s((left, top, left + 6.0, 48.0), scale), fill=WHITE)
        ell(draw, (left - 1.0, top - 8.0, left + 7.0, top), scale)
    ell(draw, (60.0, 60.0, 68.0, 72.0), scale)


def draw_pendant_lamp(draw, scale):
    draw.rectangle(s((61.0, 6.0, 67.0, 40.0), scale), fill=WHITE)
    draw.polygon(s([(44.0, 40.0), (84.0, 40.0), (96.0, 74.0), (32.0, 74.0)],
                   scale), fill=WHITE)
    ell(draw, (57.0, 74.0, 71.0, 88.0), scale)


def draw_lantern(draw, scale):
    ring(draw, (48.0, 14.0, 80.0, 46.0), scale, 7.0)
    rr(draw, (40.0, 34.0, 88.0, 100.0), scale, 10.0)
    rr(draw, (52.0, 48.0, 76.0, 88.0), scale, 6.0, fill=CLEAR)
    draw.rectangle(s((60.0, 60.0, 68.0, 86.0), scale), fill=WHITE)
    rr(draw, (36.0, 98.0, 92.0, 108.0), scale, 5.0)


def draw_flashlight(draw, scale):
    draw.polygon(s([(66.0, 40.0), (106.0, 48.0), (106.0, 80.0), (66.0, 88.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((100.0, 54.0, 106.0, 74.0), scale), fill=CLEAR)
    draw.rectangle(s((22.0, 52.0, 66.0, 76.0), scale), fill=WHITE)
    draw.rectangle(s((30.0, 52.0, 34.0, 76.0), scale), fill=CLEAR)
    draw.rectangle(s((38.0, 52.0, 42.0, 76.0), scale), fill=CLEAR)
    rr(draw, (48.0, 42.0, 60.0, 52.0), scale, 4.0)


def draw_spotlight(draw, scale):
    rr(draw, (20.0, 40.0, 32.0, 88.0), scale, 5.0)
    draw.rectangle(s((32.0, 58.0, 58.0, 66.0), scale), fill=WHITE)
    draw.polygon(s([(58.0, 48.0), (96.0, 58.0), (96.0, 78.0), (58.0, 88.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((88.0, 60.0, 96.0, 76.0), scale), fill=CLEAR)


def draw_string_light(draw, scale):
    draw.arc(s((8.0, 10.0, 120.0, 90.0), scale), start=15, end=165,
             fill=WHITE, width=7)
    for x, y in ((30.0, 62.0), (64.0, 72.0), (98.0, 62.0)):
        draw.rectangle(s((x - 2.0, y - 12.0, x + 2.0, y), scale), fill=WHITE)
        ell(draw, (x - 7.0, y, x + 7.0, y + 14.0), scale)


def draw_candle(draw, scale):
    ell(draw, (56.0, 18.0, 72.0, 36.0), scale)
    draw.rectangle(s((61.0, 36.0, 67.0, 48.0), scale), fill=WHITE)
    ell(draw, (50.0, 44.0, 78.0, 62.0), scale)
    rr(draw, (50.0, 52.0, 78.0, 110.0), scale, 8.0)


def draw_lamp_shade(draw, scale):
    ell(draw, (60.0, 10.0, 68.0, 18.0), scale)
    draw.polygon(s([(40.0, 22.0), (88.0, 22.0), (100.0, 66.0), (28.0, 66.0)],
                   scale), fill=WHITE)
    ell(draw, (57.0, 66.0, 71.0, 80.0), scale)


def draw_night_light(draw, scale):
    draw.rectangle(s((52.0, 14.0, 58.0, 30.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 14.0, 76.0, 30.0), scale), fill=WHITE)
    rr(draw, (44.0, 30.0, 84.0, 62.0), scale, 8.0)
    ell(draw, (50.0, 58.0, 78.0, 88.0), scale)


def draw_track_light(draw, scale):
    draw.rectangle(s((20.0, 24.0, 108.0, 34.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 12.0, 42.0, 24.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 12.0, 94.0, 24.0), scale), fill=WHITE)
    for left in (40.0, 70.0):
        draw.polygon(s([(left, 34.0), (left + 18.0, 34.0), (left + 14.0, 62.0),
                        (left + 4.0, 62.0)], scale), fill=WHITE)
        ell(draw, (left + 6.0, 62.0, left + 12.0, 68.0), scale)


def draw_garden_light(draw, scale):
    ell(draw, (60.0, 12.0, 68.0, 22.0), scale)
    rr(draw, (44.0, 22.0, 84.0, 34.0), scale, 6.0)
    draw.rectangle(s((58.0, 34.0, 70.0, 42.0), scale), fill=WHITE)
    rr(draw, (54.0, 42.0, 74.0, 94.0), scale, 8.0)
    draw.rectangle(s((59.0, 50.0, 69.0, 86.0), scale), fill=CLEAR)
    rr(draw, (46.0, 94.0, 82.0, 104.0), scale, 5.0)


def draw_disco_ball(draw, scale):
    draw.rectangle(s((61.0, 8.0, 67.0, 20.0), scale), fill=WHITE)
    ell(draw, (38.0, 22.0, 90.0, 76.0), scale)
    for y in (32.0, 44.0, 56.0):
        for x in (50.0, 62.0, 74.0):
            draw.rectangle(s((x, y, x + 6.0, y + 6.0), scale), fill=CLEAR)


def draw_lamp_post(draw, scale):
    rr(draw, (52.0, 100.0, 76.0, 112.0), scale, 4.0)
    draw.rectangle(s((60.0, 40.0, 68.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((60.0, 42.0, 90.0, 50.0), scale), fill=WHITE)
    draw.polygon(s([(90.0, 38.0), (104.0, 50.0), (104.0, 62.0), (90.0, 62.0)],
                   scale), fill=WHITE)
    ell(draw, (90.0, 62.0, 100.0, 72.0), scale)


# ---------------------------------------------------------------- switches


def draw_socket(draw, scale):
    rr(draw, (30.0, 30.0, 98.0, 98.0), scale, 14.0)
    ell(draw, (44.0, 52.0, 58.0, 66.0), scale, fill=CLEAR)
    ell(draw, (70.0, 52.0, 84.0, 66.0), scale, fill=CLEAR)
    draw.rectangle(s((62.0, 36.0, 66.0, 46.0), scale), fill=CLEAR)


def draw_power(draw, scale):
    ell(draw, (36.0, 28.0, 92.0, 92.0), scale)
    ell(draw, (48.0, 40.0, 80.0, 80.0), scale, fill=CLEAR)
    draw.rectangle(s((58.0, 22.0, 70.0, 44.0), scale), fill=CLEAR)
    draw.rectangle(s((59.0, 14.0, 69.0, 52.0), scale), fill=WHITE)


def draw_toggle(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    draw.polygon(s([(48.0, 44.0), (80.0, 52.0), (80.0, 84.0), (48.0, 76.0)],
                   scale), fill=CLEAR)
    draw.polygon(s([(50.0, 46.0), (78.0, 53.0), (78.0, 82.0), (50.0, 75.0)],
                   scale), fill=WHITE)


def draw_dimmer(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    draw.rectangle(s((60.0, 32.0, 68.0, 96.0), scale), fill=CLEAR)
    ell(draw, (54.0, 52.0, 74.0, 72.0), scale)


def draw_double_switch(draw, scale):
    rr(draw, (36.0, 20.0, 92.0, 108.0), scale, 10.0)
    draw.rectangle(s((44.0, 36.0, 60.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((68.0, 36.0, 84.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((46.0, 38.0, 58.0, 90.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 38.0, 82.0, 90.0), scale), fill=WHITE)


def draw_remote(draw, scale):
    rr(draw, (48.0, 14.0, 80.0, 114.0), scale, 12.0)
    ell(draw, (58.0, 24.0, 70.0, 36.0), scale, fill=CLEAR)
    for y in (44.0, 56.0, 68.0, 80.0):
        for x in (55.0, 62.0, 69.0):
            draw.rectangle(s((x, y, x + 5.0, y + 5.0), scale), fill=CLEAR)
    rr(draw, (56.0, 96.0, 72.0, 106.0), scale, 3.0, fill=CLEAR)


def draw_timer(draw, scale):
    draw.rectangle(s((58.0, 16.0, 70.0, 28.0), scale), fill=WHITE)
    draw.rectangle(s((61.0, 28.0, 67.0, 36.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 30.0, 96.0, 38.0), scale), fill=WHITE)
    ell(draw, (34.0, 34.0, 94.0, 94.0), scale)
    ell(draw, (44.0, 44.0, 84.0, 84.0), scale, fill=CLEAR)
    ell(draw, (50.0, 50.0, 78.0, 78.0), scale)
    draw.rectangle(s((62.0, 52.0, 66.0, 64.0), scale), fill=CLEAR)
    bar(draw, (64.0, 64.0), scale, 10.0, 4.0, 35.0, fill=CLEAR)


def draw_power_strip(draw, scale):
    draw.rectangle(s((4.0, 58.0, 14.0, 70.0), scale), fill=WHITE)
    rr(draw, (14.0, 48.0, 112.0, 80.0), scale, 10.0)
    for x in (24.0, 44.0, 64.0, 84.0):
        draw.rectangle(s((x, 56.0, x + 12.0, 68.0), scale), fill=CLEAR)


def draw_charger(draw, scale):
    draw.rectangle(s((52.0, 16.0, 58.0, 34.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 16.0, 76.0, 34.0), scale), fill=WHITE)
    rr(draw, (44.0, 34.0, 84.0, 78.0), scale, 10.0)
    draw.polygon(s([(66.0, 42.0), (55.0, 60.0), (62.0, 60.0), (60.0, 72.0),
                    (72.0, 53.0), (64.0, 53.0)], scale), fill=CLEAR)


def draw_button(draw, scale):
    rr(draw, (32.0, 86.0, 96.0, 104.0), scale, 4.0)
    rr(draw, (40.0, 58.0, 88.0, 100.0), scale, 10.0)
    rr(draw, (48.0, 66.0, 80.0, 92.0), scale, 7.0, fill=CLEAR)
    ell(draw, (50.0, 54.0, 78.0, 86.0), scale)


def draw_breaker(draw, scale):
    rr(draw, (36.0, 20.0, 92.0, 108.0), scale, 8.0)
    draw.rectangle(s((44.0, 28.0, 84.0, 100.0), scale), fill=CLEAR)
    draw.rectangle(s((48.0, 32.0, 80.0, 96.0), scale), fill=WHITE)
    for x in (52.0, 61.0, 70.0):
        draw.rectangle(s((x, 38.0, x + 6.0, 50.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 58.0, 68.0, 90.0), scale), fill=CLEAR)
    draw.polygon(s([(60.0, 62.0), (70.0, 58.0), (66.0, 84.0), (56.0, 88.0)],
                   scale), fill=WHITE)


# ----------------------------------------------------------------- climate


def draw_ceiling_fan(draw, scale):
    rr(draw, (56.0, 8.0, 72.0, 18.0), scale, 4.0)
    draw.rectangle(s((61.0, 18.0, 67.0, 44.0), scale), fill=WHITE)
    for angle in (90.0, 210.0, 330.0):
        blade(draw, (64.0, 62.0), scale, 40.0, 14.0, angle)
    ell(draw, (54.0, 52.0, 74.0, 72.0), scale)


def draw_air_purifier(draw, scale):
    rr(draw, (42.0, 14.0, 86.0, 114.0), scale, 10.0)
    for top in (34.0, 50.0, 66.0):
        draw.rectangle(s((50.0, top, 78.0, top + 8.0), scale), fill=CLEAR)


def draw_humidifier(draw, scale):
    ell(draw, (54.0, 14.0, 62.0, 22.0), scale)
    ell(draw, (60.0, 8.0, 68.0, 16.0), scale)
    ell(draw, (66.0, 14.0, 74.0, 22.0), scale)
    draw.rectangle(s((58.0, 32.0, 70.0, 44.0), scale), fill=WHITE)
    rr(draw, (44.0, 44.0, 84.0, 110.0), scale, 12.0)


def draw_dehumidifier(draw, scale):
    rr(draw, (36.0, 40.0, 92.0, 108.0), scale, 10.0)
    for top in (48.0, 60.0):
        draw.rectangle(s((46.0, top, 82.0, top + 6.0), scale), fill=CLEAR)
    rr(draw, (46.0, 72.0, 82.0, 100.0), scale, 6.0, fill=CLEAR)
    ell(draw, (58.0, 76.0, 70.0, 88.0), scale)
    draw.polygon(s([(58.0, 82.0), (70.0, 82.0), (64.0, 72.0)], scale))


def draw_vent(draw, scale):
    rr(draw, (24.0, 44.0, 104.0, 88.0), scale, 8.0)
    draw.rectangle(s((32.0, 52.0, 96.0, 80.0), scale), fill=CLEAR)
    for top in (55.0, 65.0, 75.0):
        draw.rectangle(s((32.0, top, 96.0, top + 6.0), scale), fill=WHITE)


def draw_stove(draw, scale):
    draw.rectangle(s((58.0, 16.0, 70.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((42.0, 100.0, 50.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((78.0, 100.0, 86.0, 110.0), scale), fill=WHITE)
    rr(draw, (36.0, 52.0, 92.0, 100.0), scale, 8.0)
    rr(draw, (46.0, 62.0, 74.0, 92.0), scale, 4.0, fill=CLEAR)
    rr(draw, (50.0, 66.0, 70.0, 80.0), scale, 2.0)


def draw_humidity(draw, scale):
    ell(draw, (36.0, 62.0, 72.0, 98.0), scale)
    draw.polygon(s([(36.0, 80.0), (72.0, 80.0), (54.0, 40.0)], scale),
                 fill=WHITE)
    ell(draw, (74.0, 82.0, 98.0, 106.0), scale)
    draw.polygon(s([(74.0, 94.0), (98.0, 94.0), (86.0, 68.0)], scale),
                 fill=WHITE)


def draw_droplet(draw, scale):
    ell(draw, (46.0, 64.0, 82.0, 100.0), scale)
    draw.polygon(s([(46.0, 82.0), (82.0, 82.0), (64.0, 36.0)], scale),
                 fill=WHITE)


def draw_leaf(draw, scale):
    draw.polygon(s([(64.0, 14.0), (88.0, 50.0), (80.0, 88.0), (64.0, 112.0),
                    (48.0, 88.0), (40.0, 50.0)], scale), fill=WHITE)
    bar(draw, (64.0, 62.0), scale, 38.0, 4.0, 90.0, fill=CLEAR)


def draw_water_heater(draw, scale):
    draw.rectangle(s((52.0, 12.0, 60.0, 28.0), scale), fill=WHITE)
    draw.rectangle(s((68.0, 12.0, 76.0, 28.0), scale), fill=WHITE)
    draw.rectangle(s((48.0, 100.0, 80.0, 110.0), scale), fill=WHITE)
    rr(draw, (44.0, 28.0, 84.0, 100.0), scale, 14.0)
    ell(draw, (58.0, 52.0, 70.0, 64.0), scale, fill=CLEAR)


def draw_heat_pump(draw, scale):
    rr(draw, (28.0, 44.0, 100.0, 104.0), scale, 8.0)
    for left in (36.0, 46.0):
        draw.rectangle(s((left, 52.0, left + 6.0, 96.0), scale), fill=CLEAR)
    ell(draw, (58.0, 52.0, 92.0, 86.0), scale)
    ell(draw, (66.0, 60.0, 84.0, 78.0), scale, fill=CLEAR)
    ell(draw, (71.0, 65.0, 79.0, 73.0), scale)


def draw_chimney(draw, scale):
    draw.rectangle(s((36.0, 74.0, 92.0, 112.0), scale), fill=WHITE)
    draw.polygon(s([(28.0, 76.0), (64.0, 46.0), (100.0, 76.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((74.0, 28.0, 88.0, 58.0), scale), fill=WHITE)
    ell(draw, (72.0, 12.0, 82.0, 22.0), scale)
    ell(draw, (80.0, 4.0, 90.0, 14.0), scale)


# ------------------------------------------------------------------ covers


def draw_awning(draw, scale):
    draw.rectangle(s((20.0, 30.0, 108.0, 40.0), scale), fill=WHITE)
    draw.rectangle(s((20.0, 40.0, 108.0, 70.0), scale), fill=WHITE)
    for x in (26.0, 46.0, 66.0, 86.0):
        ell(draw, (x, 58.0, x + 16.0, 74.0), scale, fill=CLEAR)
    draw.rectangle(s((28.0, 70.0, 36.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((92.0, 70.0, 100.0, 104.0), scale), fill=WHITE)


def draw_pergola(draw, scale):
    draw.rectangle(s((28.0, 44.0, 38.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((90.0, 44.0, 100.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((16.0, 30.0, 112.0, 40.0), scale), fill=WHITE)
    for x in (22.0, 40.0, 58.0, 76.0, 94.0):
        draw.rectangle(s((x, 18.0, x + 8.0, 30.0), scale), fill=WHITE)


def draw_fence(draw, scale):
    for x in (24.0, 60.0, 96.0):
        draw.polygon(s([(x, 28.0), (x + 8.0, 28.0), (x + 8.0, 108.0),
                        (x, 108.0)], scale), fill=WHITE)
        draw.polygon(s([(x, 28.0), (x + 4.0, 20.0), (x + 8.0, 28.0)], scale),
                     fill=WHITE)
    draw.rectangle(s((16.0, 52.0, 112.0, 60.0), scale), fill=WHITE)
    draw.rectangle(s((16.0, 76.0, 112.0, 84.0), scale), fill=WHITE)


def draw_gate(draw, scale):
    draw.rectangle(s((20.0, 36.0, 28.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((16.0, 36.0, 112.0, 44.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 44.0, 92.0, 96.0), scale), fill=WHITE)
    for x in (36.0, 48.0, 60.0, 72.0):
        draw.rectangle(s((x, 50.0, x + 4.0, 90.0), scale), fill=CLEAR)
    draw.rectangle(s((28.0, 64.0, 92.0, 70.0), scale), fill=CLEAR)
    ell(draw, (48.0, 38.0, 56.0, 46.0), scale)
    ell(draw, (72.0, 38.0, 80.0, 46.0), scale)


def draw_shutters(draw, scale):
    for left in (24.0, 70.0):
        rr(draw, (left, 36.0, left + 34.0, 104.0), scale, 4.0)
        for top in (44.0, 56.0, 68.0, 80.0, 92.0):
            draw.rectangle(s((left + 5.0, top, left + 29.0, top + 4.0),
                             scale), fill=CLEAR)


def draw_skylight(draw, scale):
    draw.polygon(s([(14.0, 84.0), (64.0, 34.0), (114.0, 84.0)], scale),
                 fill=WHITE)
    draw.polygon(s([(40.0, 78.0), (64.0, 54.0), (88.0, 78.0)], scale),
                 fill=CLEAR)
    draw.rectangle(s((60.0, 54.0, 68.0, 78.0), scale), fill=WHITE)


def draw_sun_umbrella(draw, scale):
    ell(draw, (60.0, 38.0, 68.0, 46.0), scale)
    ell(draw, (28.0, 46.0, 100.0, 90.0), scale)
    draw.rectangle(s((28.0, 68.0, 100.0, 90.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 68.0, 68.0, 112.0), scale), fill=WHITE)


def draw_greenhouse(draw, scale):
    draw.polygon(s([(34.0, 62.0), (34.0, 110.0), (94.0, 110.0), (94.0, 62.0),
                    (64.0, 34.0)], scale), fill=WHITE)
    draw.rectangle(s((42.0, 62.0, 86.0, 66.0), scale), fill=CLEAR)
    draw.rectangle(s((42.0, 76.0, 86.0, 80.0), scale), fill=CLEAR)
    draw.rectangle(s((42.0, 90.0, 86.0, 94.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 34.0, 68.0, 110.0), scale), fill=CLEAR)


def draw_shed(draw, scale):
    draw.polygon(s([(30.0, 62.0), (30.0, 110.0), (98.0, 110.0), (98.0, 62.0),
                    (64.0, 34.0)], scale), fill=WHITE)
    bar(draw, (47.0, 50.0), scale, 16.0, 4.0, 38.0, fill=CLEAR)
    bar(draw, (81.0, 50.0), scale, 16.0, 4.0, -38.0, fill=CLEAR)
    draw.rectangle(s((54.0, 78.0, 74.0, 110.0), scale), fill=CLEAR)
    bar(draw, (64.0, 94.0), scale, 14.0, 4.0, 60.0)


def draw_mailbox(draw, scale):
    draw.rectangle(s((60.0, 60.0, 68.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((52.0, 54.0, 76.0, 62.0), scale), fill=WHITE)
    rr(draw, (30.0, 34.0, 86.0, 60.0), scale, 10.0)
    draw.rectangle(s((76.0, 34.0, 80.0, 60.0), scale), fill=CLEAR)
    draw.rectangle(s((86.0, 18.0, 90.0, 52.0), scale), fill=WHITE)
    draw.polygon(s([(90.0, 18.0), (106.0, 24.0), (90.0, 30.0)], scale),
                 fill=WHITE)


# ----------------------------------------------------------------- weather


def draw_partly_cloudy(draw, scale):
    ell(draw, (34.0, 28.0, 62.0, 56.0), scale)
    ray_fan(draw, (48.0, 42.0), scale, 20.0, 28.0, 6.0,
            (180.0, 225.0, 270.0, 315.0))
    cloud_puffs(draw, scale,
                ((56.0, 76.0, 16.0), (74.0, 66.0, 21.0), (92.0, 76.0, 14.0)),
                (54.0, 76.0, 94.0, 98.0), 10.0)


def draw_thunderstorm(draw, scale):
    cloud_puffs(draw, scale,
                ((40.0, 44.0, 14.0), (58.0, 36.0, 18.0), (76.0, 44.0, 13.0)),
                (38.0, 44.0, 78.0, 62.0), 8.0)
    draw.polygon(s([(64.0, 60.0), (50.0, 86.0), (60.0, 86.0), (56.0, 108.0),
                    (74.0, 80.0), (63.0, 80.0)], scale), fill=WHITE)


def draw_fog(draw, scale):
    cloud_puffs(draw, scale,
                ((44.0, 36.0, 12.0), (60.0, 30.0, 15.0), (76.0, 36.0, 11.0)),
                (42.0, 36.0, 78.0, 52.0), 7.0)
    draw.rectangle(s((30.0, 64.0, 98.0, 70.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 78.0, 88.0, 84.0), scale), fill=WHITE)
    draw.rectangle(s((30.0, 92.0, 98.0, 98.0), scale), fill=WHITE)


def draw_hail(draw, scale):
    cloud_puffs(draw, scale,
                ((44.0, 38.0, 13.0), (62.0, 30.0, 17.0), (80.0, 38.0, 12.0)),
                (42.0, 38.0, 82.0, 56.0), 8.0)
    for x, y in ((48.0, 70.0), (64.0, 78.0), (80.0, 70.0)):
        ell(draw, (x - 5.0, y - 5.0, x + 5.0, y + 5.0), scale)


def draw_rainbow(draw, scale):
    draw.ellipse(s((30.0, 38.0, 98.0, 106.0), scale), outline=WHITE, width=7)
    draw.ellipse(s((42.0, 50.0, 86.0, 94.0), scale), outline=WHITE, width=7)
    draw.rectangle(s((15.0, 66.0, 113.0, 115.0), scale), fill=CLEAR)
    ell(draw, (16.0, 70.0, 48.0, 94.0), scale)
    ell(draw, (80.0, 70.0, 112.0, 94.0), scale)


def draw_sunrise(draw, scale):
    ell(draw, (42.0, 46.0, 86.0, 90.0), scale)
    draw.rectangle(s((42.0, 84.0, 86.0, 90.0), scale), fill=CLEAR)
    ray_fan(draw, (64.0, 73.0), scale, 30.0, 40.0, 7.0,
            (180.0, 225.0, 270.0, 315.0, 0.0))
    draw.rectangle(s((14.0, 84.0, 114.0, 92.0), scale), fill=WHITE)


def draw_starry_night(draw, scale):
    ell(draw, (28.0, 28.0, 68.0, 68.0), scale)
    ell(draw, (42.0, 20.0, 82.0, 60.0), scale, fill=CLEAR)
    for cx, cy, size in ((92.0, 40.0, 12.0), (86.0, 78.0, 8.0)):
        draw.polygon(s([(cx, cy - size), (cx + size / 4.0, cy - size / 4.0),
                        (cx + size, cy), (cx + size / 4.0, cy + size / 4.0),
                        (cx, cy + size), (cx - size / 4.0, cy + size / 4.0),
                        (cx - size, cy), (cx - size / 4.0, cy - size / 4.0)],
                       scale), fill=WHITE)


def draw_umbrella(draw, scale):
    draw.rectangle(s((61.0, 38.0, 67.0, 52.0), scale), fill=WHITE)
    ell(draw, (26.0, 52.0, 102.0, 92.0), scale)
    draw.rectangle(s((26.0, 72.0, 102.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((61.0, 72.0, 67.0, 102.0), scale), fill=WHITE)
    ell(draw, (43.0, 88.0, 71.0, 116.0), scale)
    ell(draw, (51.0, 96.0, 63.0, 108.0), scale, fill=CLEAR)


def draw_lightning(draw, scale):
    draw.polygon(s([(70.0, 12.0), (44.0, 70.0), (60.0, 70.0), (54.0, 116.0),
                    (86.0, 58.0), (68.0, 58.0)], scale), fill=WHITE)


def draw_eclipse(draw, scale):
    ell(draw, (36.0, 36.0, 92.0, 92.0), scale)
    ell(draw, (52.0, 28.0, 108.0, 84.0), scale, fill=CLEAR)
    ray_fan(draw, (64.0, 64.0), scale, 34.0, 42.0, 6.0,
            range(0, 360, 45))


def draw_overcast(draw, scale):
    cloud_puffs(draw, scale,
                ((34.0, 58.0, 14.0), (50.0, 50.0, 18.0), (66.0, 58.0, 13.0)),
                (32.0, 58.0, 68.0, 78.0), 8.0)
    cloud_puffs(draw, scale,
                ((52.0, 78.0, 17.0), (72.0, 68.0, 22.0), (92.0, 78.0, 15.0)),
                (50.0, 78.0, 94.0, 102.0), 10.0)


def draw_sleet(draw, scale):
    cloud_puffs(draw, scale,
                ((44.0, 38.0, 13.0), (62.0, 30.0, 17.0), (80.0, 38.0, 12.0)),
                (42.0, 38.0, 82.0, 56.0), 8.0)
    bar(draw, (52.0, 76.0), scale, 14.0, 7.0, 105.0)
    ell(draw, (66.0, 70.0, 74.0, 78.0), scale)
    ell(draw, (76.0, 80.0, 84.0, 88.0), scale)


# ---------------------------------------------------------------- security


def draw_smoke_detector(draw, scale):
    ell(draw, (28.0, 48.0, 100.0, 92.0), scale)
    for x, y in ((40.0, 70.0), (88.0, 70.0), (64.0, 54.0), (64.0, 86.0)):
        ell(draw, (x - 3.0, y - 3.0, x + 3.0, y + 3.0), scale, fill=CLEAR)
    ell(draw, (56.0, 62.0, 72.0, 78.0), scale, fill=CLEAR)
    ell(draw, (60.0, 66.0, 68.0, 74.0), scale)


def draw_siren(draw, scale):
    draw.polygon(s([(28.0, 44.0), (72.0, 56.0), (72.0, 72.0), (28.0, 84.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((76.0, 52.0, 88.0, 76.0), scale), fill=WHITE)
    for x, height in ((96.0, 20.0), (104.0, 30.0), (112.0, 40.0)):
        draw.rectangle(s((x - 3.0, 64.0 - height / 2.0, x + 3.0,
                          64.0 + height / 2.0), scale), fill=WHITE)


def draw_alarm_clock(draw, scale):
    ell(draw, (34.0, 26.0, 50.0, 42.0), scale)
    ell(draw, (78.0, 26.0, 94.0, 42.0), scale)
    draw.rectangle(s((60.0, 22.0, 68.0, 32.0), scale), fill=WHITE)
    draw.rectangle(s((42.0, 98.0, 48.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 98.0, 86.0, 110.0), scale), fill=WHITE)
    ell(draw, (34.0, 38.0, 94.0, 98.0), scale)
    ell(draw, (44.0, 48.0, 84.0, 88.0), scale, fill=CLEAR)
    ell(draw, (50.0, 54.0, 78.0, 82.0), scale)
    draw.rectangle(s((62.0, 56.0, 66.0, 68.0), scale), fill=CLEAR)
    bar(draw, (64.0, 68.0), scale, 9.0, 4.0, 40.0, fill=CLEAR)


def draw_shield(draw, scale):
    draw.polygon(s([(64.0, 14.0), (94.0, 28.0), (94.0, 64.0), (64.0, 114.0),
                    (34.0, 64.0), (34.0, 28.0)], scale), fill=WHITE)
    draw.polygon(s([(46.0, 64.0), (58.0, 78.0), (82.0, 48.0), (76.0, 42.0),
                    (58.0, 66.0), (52.0, 58.0)], scale), fill=CLEAR)


def draw_keypad(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    rr(draw, (48.0, 30.0, 80.0, 46.0), scale, 4.0, fill=CLEAR)
    for y in (56.0, 68.0, 80.0):
        for x in (51.0, 61.0, 71.0):
            draw.rectangle(s((x, y, x + 7.0, y + 7.0), scale), fill=CLEAR)


def draw_key(draw, scale):
    ell(draw, (24.0, 44.0, 56.0, 76.0), scale)
    ell(draw, (32.0, 52.0, 48.0, 68.0), scale, fill=CLEAR)
    draw.rectangle(s((54.0, 56.0, 104.0, 64.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 64.0, 92.0, 78.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 64.0, 102.0, 74.0), scale), fill=WHITE)


def draw_camera_dome(draw, scale):
    draw.rectangle(s((32.0, 20.0, 96.0, 30.0), scale), fill=WHITE)
    ell(draw, (38.0, 30.0, 90.0, 82.0), scale)
    draw.rectangle(s((38.0, 56.0, 90.0, 82.0), scale), fill=CLEAR)
    draw.rectangle(s((38.0, 50.0, 90.0, 58.0), scale), fill=WHITE)
    ell(draw, (57.0, 58.0, 71.0, 72.0), scale)


def draw_intercom(draw, scale):
    rr(draw, (42.0, 18.0, 86.0, 110.0), scale, 8.0)
    for y in (30.0, 40.0):
        for x in (52.0, 62.0, 72.0):
            ell(draw, (x - 3.0, y - 3.0, x + 3.0, y + 3.0), scale, fill=CLEAR)
    ell(draw, (57.0, 58.0, 71.0, 72.0), scale, fill=CLEAR)
    ell(draw, (60.0, 61.0, 68.0, 69.0), scale)
    draw.rectangle(s((56.0, 100.0, 72.0, 104.0), scale), fill=CLEAR)


def draw_leak(draw, scale):
    ell(draw, (36.0, 48.0, 70.0, 82.0), scale)
    draw.polygon(s([(36.0, 65.0), (70.0, 65.0), (53.0, 30.0)], scale),
                 fill=WHITE)
    ell(draw, (30.0, 92.0, 98.0, 108.0), scale)


def draw_panic_button(draw, scale):
    rr(draw, (34.0, 92.0, 94.0, 106.0), scale, 6.0)
    ell(draw, (44.0, 60.0, 84.0, 100.0), scale)
    ell(draw, (52.0, 68.0, 76.0, 92.0), scale, fill=CLEAR)
    ell(draw, (54.0, 50.0, 74.0, 78.0), scale)


def draw_lock_open(draw, scale):
    ell(draw, (38.0, 18.0, 90.0, 74.0), scale)
    ell(draw, (50.0, 30.0, 78.0, 62.0), scale, fill=CLEAR)
    draw.rectangle(s((70.0, 18.0, 90.0, 42.0), scale), fill=CLEAR)
    rr(draw, (30.0, 62.0, 98.0, 112.0), scale, 10.0)
    ell(draw, (57.0, 76.0, 71.0, 90.0), scale, fill=CLEAR)
    draw.rectangle(s((60.0, 86.0, 68.0, 100.0), scale), fill=CLEAR)


def draw_safe(draw, scale):
    draw.rectangle(s((40.0, 100.0, 48.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 100.0, 88.0, 110.0), scale), fill=WHITE)
    rr(draw, (28.0, 36.0, 100.0, 102.0), scale, 8.0)
    rr(draw, (36.0, 44.0, 92.0, 94.0), scale, 4.0, fill=CLEAR)
    ell(draw, (56.0, 60.0, 72.0, 76.0), scale)
    bar(draw, (64.0, 68.0), scale, 10.0, 5.0, 90.0)
    bar(draw, (64.0, 68.0), scale, 10.0, 5.0, 30.0)
    bar(draw, (64.0, 68.0), scale, 10.0, 5.0, 150.0)


def draw_video_doorbell(draw, scale):
    rr(draw, (46.0, 16.0, 82.0, 112.0), scale, 8.0)
    ell(draw, (56.0, 26.0, 72.0, 42.0), scale, fill=CLEAR)
    ell(draw, (60.0, 30.0, 68.0, 38.0), scale)
    ell(draw, (56.0, 52.0, 72.0, 68.0), scale, fill=CLEAR)
    for y in (80.0, 88.0, 96.0):
        ell(draw, (60.0, y, 68.0, y + 4.0), scale, fill=CLEAR)


def draw_window_sensor(draw, scale):
    rr(draw, (30.0, 40.0, 66.0, 88.0), scale, 6.0)
    draw.rectangle(s((74.0, 48.0, 86.0, 80.0), scale), fill=WHITE)
    ell(draw, (42.0, 52.0, 50.0, 60.0), scale, fill=CLEAR)


# ------------------------------------------------------------------- media


def draw_soundbar(draw, scale):
    rr(draw, (16.0, 54.0, 112.0, 78.0), scale, 12.0)
    ell(draw, (28.0, 58.0, 46.0, 74.0), scale, fill=CLEAR)
    ell(draw, (82.0, 58.0, 100.0, 74.0), scale, fill=CLEAR)
    ell(draw, (56.0, 62.0, 62.0, 68.0), scale, fill=CLEAR)
    ell(draw, (66.0, 62.0, 72.0, 68.0), scale, fill=CLEAR)


def draw_projector(draw, scale):
    draw.rectangle(s((60.0, 14.0, 68.0, 30.0), scale), fill=WHITE)
    draw.polygon(s([(30.0, 30.0), (98.0, 30.0), (90.0, 80.0), (38.0, 80.0)],
                   scale), fill=WHITE)
    ell(draw, (54.0, 44.0, 76.0, 66.0), scale, fill=CLEAR)
    ell(draw, (59.0, 49.0, 71.0, 61.0), scale)
    for top in (44.0, 56.0):
        draw.rectangle(s((82.0, top, 92.0, top + 5.0), scale), fill=CLEAR)


def draw_screen(draw, scale):
    rr(draw, (24.0, 28.0, 104.0, 84.0), scale, 4.0)
    draw.rectangle(s((30.0, 34.0, 98.0, 78.0), scale), fill=CLEAR)
    draw.polygon(s([(54.0, 46.0), (54.0, 70.0), (76.0, 58.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((60.0, 84.0, 68.0, 96.0), scale), fill=WHITE)
    rr(draw, (48.0, 96.0, 80.0, 104.0), scale, 4.0)


def draw_gamepad(draw, scale):
    rr(draw, (28.0, 48.0, 100.0, 88.0), scale, 16.0)
    ell(draw, (26.0, 62.0, 48.0, 98.0), scale)
    ell(draw, (80.0, 62.0, 102.0, 98.0), scale)
    draw.rectangle(s((42.0, 60.0, 50.0, 80.0), scale), fill=CLEAR)
    draw.rectangle(s((36.0, 66.0, 56.0, 74.0), scale), fill=CLEAR)
    ell(draw, (70.0, 60.0, 78.0, 68.0), scale, fill=CLEAR)
    ell(draw, (78.0, 68.0, 86.0, 76.0), scale, fill=CLEAR)


def draw_radio(draw, scale):
    bar(draw, (102.0, 32.0), scale, 24.0, 6.0, -63.0)
    rr(draw, (24.0, 52.0, 104.0, 100.0), scale, 10.0)
    rr(draw, (32.0, 60.0, 62.0, 92.0), scale, 6.0, fill=CLEAR)
    for top in (64.0, 72.0, 80.0):
        draw.rectangle(s((36.0, top, 58.0, top + 4.0), scale), fill=WHITE)
    ell(draw, (70.0, 60.0, 92.0, 82.0), scale, fill=CLEAR)
    ell(draw, (75.0, 65.0, 87.0, 77.0), scale)


def draw_microphone(draw, scale):
    rr(draw, (48.0, 14.0, 80.0, 58.0), scale, 14.0)
    for top in (26.0, 38.0):
        draw.rectangle(s((52.0, top, 76.0, top + 6.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 58.0, 68.0, 92.0), scale), fill=WHITE)
    draw.polygon(s([(50.0, 92.0), (78.0, 92.0), (86.0, 106.0), (42.0, 106.0)],
                   scale), fill=WHITE)


def draw_headphones(draw, scale):
    ell(draw, (30.0, 26.0, 98.0, 94.0), scale)
    ell(draw, (42.0, 38.0, 86.0, 82.0), scale, fill=CLEAR)
    draw.rectangle(s((30.0, 66.0, 98.0, 94.0), scale), fill=CLEAR)
    rr(draw, (22.0, 64.0, 40.0, 104.0), scale, 6.0)
    rr(draw, (88.0, 64.0, 106.0, 104.0), scale, 6.0)


def draw_laptop(draw, scale):
    rr(draw, (34.0, 28.0, 94.0, 74.0), scale, 4.0)
    draw.rectangle(s((40.0, 34.0, 88.0, 68.0), scale), fill=CLEAR)
    draw.polygon(s([(24.0, 86.0), (104.0, 86.0), (96.0, 100.0), (32.0, 100.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((58.0, 86.0, 70.0, 92.0), scale), fill=CLEAR)


def draw_tablet(draw, scale):
    rr(draw, (40.0, 24.0, 88.0, 104.0), scale, 10.0)
    rr(draw, (48.0, 34.0, 80.0, 88.0), scale, 4.0, fill=CLEAR)
    ell(draw, (60.0, 92.0, 68.0, 100.0), scale)


def draw_phone(draw, scale):
    rr(draw, (46.0, 16.0, 82.0, 112.0), scale, 12.0)
    draw.rectangle(s((58.0, 24.0, 70.0, 28.0), scale), fill=CLEAR)
    rr(draw, (52.0, 36.0, 76.0, 92.0), scale, 3.0, fill=CLEAR)
    ell(draw, (60.0, 96.0, 68.0, 104.0), scale)


def draw_printer(draw, scale):
    draw.rectangle(s((44.0, 12.0, 84.0, 40.0), scale), fill=WHITE)
    rr(draw, (28.0, 38.0, 100.0, 92.0), scale, 8.0)
    draw.rectangle(s((36.0, 58.0, 92.0, 66.0), scale), fill=CLEAR)
    draw.polygon(s([(40.0, 92.0), (88.0, 92.0), (82.0, 110.0), (46.0, 110.0)],
                   scale), fill=WHITE)


def draw_router(draw, scale):
    for x in (44.0, 64.0, 84.0):
        draw.rectangle(s((x - 3.0, 30.0, x + 3.0, 64.0), scale), fill=WHITE)
    rr(draw, (32.0, 64.0, 96.0, 100.0), scale, 8.0)
    for x in (42.0, 52.0, 62.0):
        draw.rectangle(s((x, 74.0, x + 4.0, 78.0), scale), fill=CLEAR)


# ------------------------------------------------------------------ kitchen


def draw_fridge(draw, scale):
    rr(draw, (42.0, 14.0, 86.0, 114.0), scale, 8.0)
    draw.rectangle(s((42.0, 60.0, 86.0, 64.0), scale), fill=CLEAR)
    draw.rectangle(s((48.0, 26.0, 54.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((48.0, 70.0, 54.0, 94.0), scale), fill=WHITE)


def draw_oven(draw, scale):
    rr(draw, (28.0, 36.0, 100.0, 108.0), scale, 6.0)
    draw.rectangle(s((32.0, 58.0, 96.0, 64.0), scale), fill=WHITE)
    rr(draw, (36.0, 70.0, 92.0, 100.0), scale, 4.0, fill=CLEAR)
    for x in (44.0, 55.0, 66.0):
        ell(draw, (x - 3.0, 43.0, x + 3.0, 49.0), scale, fill=CLEAR)


def draw_microwave(draw, scale):
    draw.rectangle(s((32.0, 100.0, 40.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 100.0, 96.0, 108.0), scale), fill=WHITE)
    rr(draw, (24.0, 40.0, 104.0, 100.0), scale, 6.0)
    rr(draw, (32.0, 50.0, 72.0, 92.0), scale, 3.0, fill=CLEAR)
    draw.rectangle(s((80.0, 56.0, 88.0, 64.0), scale), fill=CLEAR)
    draw.rectangle(s((80.0, 70.0, 88.0, 78.0), scale), fill=CLEAR)


def draw_kettle(draw, scale):
    ell(draw, (60.0, 32.0, 68.0, 40.0), scale)
    rr(draw, (52.0, 40.0, 76.0, 52.0), scale, 4.0)
    draw.polygon(s([(40.0, 52.0), (88.0, 52.0), (80.0, 100.0), (48.0, 100.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(40.0, 56.0), (28.0, 34.0), (36.0, 30.0), (48.0, 52.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((80.0, 56.0, 88.0, 92.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 56.0, 96.0, 64.0), scale), fill=WHITE)


def draw_coffee_mug(draw, scale):
    bar(draw, (54.0, 34.0), scale, 10.0, 5.0, 80.0)
    bar(draw, (68.0, 30.0), scale, 10.0, 5.0, 100.0)
    rr(draw, (40.0, 54.0, 80.0, 104.0), scale, 8.0)
    ell(draw, (80.0, 62.0, 104.0, 92.0), scale)
    ell(draw, (86.0, 68.0, 98.0, 86.0), scale, fill=CLEAR)


def draw_toaster(draw, scale):
    draw.rectangle(s((42.0, 104.0, 50.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((78.0, 104.0, 86.0, 110.0), scale), fill=WHITE)
    rr(draw, (34.0, 58.0, 94.0, 104.0), scale, 10.0)
    draw.rectangle(s((44.0, 54.0, 56.0, 62.0), scale), fill=CLEAR)
    draw.rectangle(s((68.0, 54.0, 80.0, 62.0), scale), fill=CLEAR)
    draw.rectangle(s((94.0, 70.0, 102.0, 78.0), scale), fill=WHITE)


def draw_cooker_hood(draw, scale):
    draw.rectangle(s((56.0, 12.0, 72.0, 44.0), scale), fill=WHITE)
    draw.polygon(s([(36.0, 44.0), (92.0, 44.0), (104.0, 72.0), (24.0, 72.0)],
                   scale), fill=WHITE)
    ell(draw, (50.0, 58.0, 56.0, 64.0), scale, fill=CLEAR)
    ell(draw, (72.0, 58.0, 78.0, 64.0), scale, fill=CLEAR)


def draw_faucet(draw, scale):
    rr(draw, (52.0, 96.0, 76.0, 108.0), scale, 5.0)
    draw.rectangle(s((60.0, 44.0, 68.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((60.0, 36.0, 92.0, 44.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 44.0, 94.0, 58.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 50.0, 52.0, 56.0), scale), fill=WHITE)


def draw_dishwasher(draw, scale):
    rr(draw, (32.0, 28.0, 96.0, 108.0), scale, 6.0)
    ell(draw, (46.0, 34.0, 52.0, 40.0), scale, fill=CLEAR)
    ell(draw, (56.0, 34.0, 62.0, 40.0), scale, fill=CLEAR)
    rr(draw, (40.0, 56.0, 88.0, 100.0), scale, 4.0, fill=CLEAR)
    draw.rectangle(s((40.0, 74.0, 88.0, 80.0), scale), fill=WHITE)


def draw_blender(draw, scale):
    draw.rectangle(s((48.0, 38.0, 80.0, 44.0), scale), fill=WHITE)
    draw.polygon(s([(46.0, 44.0), (82.0, 44.0), (74.0, 84.0), (54.0, 84.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(78.0, 46.0), (90.0, 52.0), (80.0, 60.0)], scale),
                 fill=WHITE)
    draw.polygon(s([(48.0, 84.0), (80.0, 84.0), (76.0, 110.0), (52.0, 110.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((56.0, 92.0, 62.0, 98.0), scale), fill=CLEAR)
    draw.rectangle(s((66.0, 92.0, 72.0, 98.0), scale), fill=CLEAR)


def draw_trash_can(draw, scale):
    ell(draw, (60.0, 32.0, 68.0, 42.0), scale)
    draw.rectangle(s((34.0, 42.0, 94.0, 52.0), scale), fill=WHITE)
    draw.polygon(s([(40.0, 52.0), (88.0, 52.0), (80.0, 108.0), (48.0, 108.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((52.0, 60.0, 56.0, 100.0), scale), fill=CLEAR)
    draw.rectangle(s((72.0, 60.0, 76.0, 100.0), scale), fill=CLEAR)


def draw_cooktop(draw, scale):
    rr(draw, (24.0, 44.0, 104.0, 88.0), scale, 8.0)
    for cx, cy in ((46.0, 60.0), (82.0, 60.0), (46.0, 78.0), (82.0, 78.0)):
        ell(draw, (cx - 7.0, cy - 7.0, cx + 7.0, cy + 7.0), scale, fill=CLEAR)
        ring(draw, (cx - 7.0, cy - 7.0, cx + 7.0, cy + 7.0), scale, 3.0)


# ---------------------------------------------------------------- bathroom


def draw_shower(draw, scale):
    draw.rectangle(s((24.0, 30.0, 70.0, 38.0), scale), fill=WHITE)
    draw.polygon(s([(70.0, 30.0), (100.0, 44.0), (96.0, 56.0), (70.0, 46.0)],
                   scale), fill=WHITE)
    for x in (76.0, 86.0, 96.0):
        ell(draw, (x - 2.0, 48.0, x + 2.0, 52.0), scale, fill=CLEAR)
    for x in (82.0, 92.0, 102.0):
        bar(draw, (x, 72.0), scale, 9.0, 5.0, 90.0)


def draw_bathtub(draw, scale):
    draw.rectangle(s((88.0, 40.0, 94.0, 58.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 34.0, 102.0, 40.0), scale), fill=WHITE)
    draw.rectangle(s((20.0, 58.0, 108.0, 68.0), scale), fill=WHITE)
    draw.polygon(s([(28.0, 68.0), (100.0, 68.0), (90.0, 104.0), (38.0, 104.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((32.0, 72.0, 96.0, 84.0), scale), fill=CLEAR)
    draw.rectangle(s((32.0, 78.0, 96.0, 84.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 104.0, 42.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 104.0, 94.0, 112.0), scale), fill=WHITE)


def draw_toilet(draw, scale):
    rr(draw, (32.0, 20.0, 64.0, 58.0), scale, 6.0)
    draw.rectangle(s((52.0, 64.0, 104.0, 76.0), scale), fill=WHITE)
    draw.polygon(s([(64.0, 76.0), (92.0, 76.0), (86.0, 108.0), (70.0, 108.0)],
                   scale), fill=WHITE)
    rr(draw, (62.0, 106.0, 96.0, 114.0), scale, 4.0)


def draw_washer(draw, scale):
    rr(draw, (30.0, 30.0, 98.0, 106.0), scale, 6.0)
    ell(draw, (44.0, 34.0, 50.0, 40.0), scale, fill=CLEAR)
    ell(draw, (54.0, 34.0, 60.0, 40.0), scale, fill=CLEAR)
    ell(draw, (40.0, 52.0, 88.0, 100.0), scale)
    ell(draw, (50.0, 62.0, 78.0, 90.0), scale, fill=CLEAR)
    ell(draw, (60.0, 72.0, 68.0, 80.0), scale)


def draw_iron(draw, scale):
    draw.polygon(s([(16.0, 88.0), (102.0, 88.0), (94.0, 104.0), (24.0, 104.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(40.0, 88.0), (100.0, 82.0), (78.0, 56.0), (54.0, 56.0),
                    (42.0, 74.0)], scale), fill=WHITE)
    rr(draw, (58.0, 62.0, 80.0, 78.0), scale, 5.0, fill=CLEAR)


def draw_robot_vacuum(draw, scale):
    ell(draw, (40.0, 96.0, 56.0, 110.0), scale)
    ell(draw, (72.0, 96.0, 88.0, 110.0), scale)
    ell(draw, (28.0, 62.0, 100.0, 102.0), scale)
    ell(draw, (56.0, 52.0, 72.0, 68.0), scale)
    draw.rectangle(s((60.0, 80.0, 68.0, 88.0), scale), fill=CLEAR)


def draw_hamper(draw, scale):
    draw.rectangle(s((32.0, 40.0, 96.0, 50.0), scale), fill=WHITE)
    draw.polygon(s([(36.0, 50.0), (92.0, 50.0), (84.0, 108.0), (44.0, 108.0)],
                   scale), fill=WHITE)
    for top, left, right in ((62.0, 40.0, 88.0), (76.0, 42.0, 86.0),
                             (90.0, 44.0, 84.0)):
        draw.rectangle(s((left, top, right, top + 6.0), scale), fill=CLEAR)


def draw_soap_dispenser(draw, scale):
    draw.rectangle(s((58.0, 40.0, 70.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((58.0, 30.0, 84.0, 40.0), scale), fill=WHITE)
    rr(draw, (48.0, 52.0, 80.0, 110.0), scale, 10.0)
    rr(draw, (54.0, 70.0, 74.0, 92.0), scale, 3.0, fill=CLEAR)


def draw_bath_scale(draw, scale):
    draw.rectangle(s((36.0, 106.0, 44.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((84.0, 106.0, 92.0, 112.0), scale), fill=WHITE)
    draw.polygon(s([(28.0, 86.0), (100.0, 86.0), (92.0, 106.0), (36.0, 106.0)],
                   scale), fill=WHITE)
    rr(draw, (54.0, 90.0, 74.0, 97.0), scale, 2.0, fill=CLEAR)


def draw_towel(draw, scale):
    draw.rectangle(s((24.0, 30.0, 104.0, 38.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 38.0, 88.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 70.0, 88.0, 78.0), scale), fill=CLEAR)


# ------------------------------------------------------------------ living


def draw_sofa(draw, scale):
    rr(draw, (24.0, 36.0, 104.0, 76.0), scale, 10.0)
    rr(draw, (16.0, 56.0, 32.0, 100.0), scale, 6.0)
    rr(draw, (96.0, 56.0, 112.0, 100.0), scale, 6.0)
    draw.rectangle(s((32.0, 76.0, 96.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((62.0, 76.0, 66.0, 96.0), scale), fill=CLEAR)
    draw.rectangle(s((28.0, 100.0, 36.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((92.0, 100.0, 100.0, 110.0), scale), fill=WHITE)


def draw_armchair(draw, scale):
    rr(draw, (36.0, 36.0, 92.0, 76.0), scale, 10.0)
    rr(draw, (28.0, 56.0, 44.0, 100.0), scale, 6.0)
    rr(draw, (84.0, 56.0, 100.0, 100.0), scale, 6.0)
    draw.rectangle(s((44.0, 76.0, 84.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 100.0, 48.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 100.0, 88.0, 110.0), scale), fill=WHITE)


def draw_bed(draw, scale):
    rr(draw, (20.0, 28.0, 34.0, 100.0), scale, 6.0)
    rr(draw, (82.0, 54.0, 106.0, 70.0), scale, 6.0)
    draw.rectangle(s((34.0, 70.0, 108.0, 88.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 74.0, 80.0, 78.0), scale), fill=CLEAR)
    draw.rectangle(s((40.0, 88.0, 48.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((94.0, 88.0, 102.0, 104.0), scale), fill=WHITE)


def draw_chair(draw, scale):
    draw.rectangle(s((40.0, 20.0, 48.0, 70.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 20.0, 88.0, 70.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 30.0, 88.0, 38.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 48.0, 88.0, 56.0), scale), fill=WHITE)
    draw.rectangle(s((36.0, 70.0, 92.0, 82.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 82.0, 48.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 82.0, 88.0, 110.0), scale), fill=WHITE)


def draw_table(draw, scale):
    draw.rectangle(s((20.0, 60.0, 108.0, 70.0), scale), fill=WHITE)
    draw.rectangle(s((30.0, 78.0, 38.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((90.0, 78.0, 98.0, 112.0), scale), fill=WHITE)


def draw_desk(draw, scale):
    draw.rectangle(s((18.0, 56.0, 110.0, 66.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 66.0, 34.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((94.0, 66.0, 104.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 72.0, 88.0, 90.0), scale), fill=CLEAR)
    ell(draw, (60.0, 78.0, 68.0, 86.0), scale)


def draw_wardrobe(draw, scale):
    rr(draw, (36.0, 16.0, 92.0, 112.0), scale, 6.0)
    draw.rectangle(s((62.0, 16.0, 66.0, 112.0), scale), fill=CLEAR)
    draw.rectangle(s((54.0, 52.0, 58.0, 68.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 52.0, 74.0, 68.0), scale), fill=WHITE)


def draw_shelf(draw, scale):
    for x, top, height in ((40.0, 26.0, 24.0), (50.0, 32.0, 18.0),
                           (60.0, 22.0, 28.0)):
        draw.rectangle(s((x, top, x + 8.0, top + height), scale), fill=WHITE)
    draw.polygon(s([(70.0, 24.0), (78.0, 26.0), (72.0, 50.0), (64.0, 50.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((20.0, 50.0, 108.0, 58.0), scale), fill=WHITE)
    draw.rectangle(s((20.0, 88.0, 108.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 58.0, 34.0, 88.0), scale), fill=WHITE)
    draw.rectangle(s((94.0, 58.0, 100.0, 88.0), scale), fill=WHITE)


def draw_clock(draw, scale):
    ell(draw, (32.0, 32.0, 96.0, 96.0), scale)
    ell(draw, (42.0, 42.0, 86.0, 86.0), scale, fill=CLEAR)
    ell(draw, (46.0, 46.0, 82.0, 82.0), scale)
    draw.rectangle(s((62.0, 50.0, 66.0, 64.0), scale), fill=CLEAR)
    bar(draw, (64.0, 64.0), scale, 10.0, 4.0, 30.0, fill=CLEAR)
    ell(draw, (61.0, 61.0, 67.0, 67.0), scale, fill=CLEAR)


def draw_books(draw, scale):
    draw.rectangle(s((24.0, 96.0, 104.0, 104.0), scale), fill=WHITE)
    for x, top in ((30.0, 60.0), (42.0, 52.0), (54.0, 64.0), (66.0, 48.0)):
        draw.rectangle(s((x, top, x + 10.0, 96.0), scale), fill=WHITE)
    draw.polygon(s([(78.0, 50.0), (88.0, 52.0), (80.0, 96.0), (70.0, 96.0)],
                   scale), fill=WHITE)


def draw_plant(draw, scale):
    draw.polygon(s([(48.0, 84.0), (80.0, 84.0), (74.0, 110.0), (54.0, 110.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(64.0, 28.0), (74.0, 58.0), (64.0, 84.0), (54.0, 58.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(40.0, 44.0), (58.0, 60.0), (44.0, 80.0), (32.0, 62.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(88.0, 44.0), (70.0, 60.0), (84.0, 80.0), (96.0, 62.0)],
                   scale), fill=WHITE)


def draw_crib(draw, scale):
    draw.rectangle(s((29.0, 30.0, 35.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((93.0, 30.0, 99.0, 114.0), scale), fill=WHITE)
    ell(draw, (26.0, 22.0, 38.0, 34.0), scale)
    ell(draw, (90.0, 22.0, 102.0, 34.0), scale)
    draw.rectangle(s((35.0, 44.0, 93.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((35.0, 92.0, 93.0, 100.0), scale), fill=WHITE)
    for x in (41.0, 51.0, 61.0, 71.0, 81.0):
        draw.rectangle(s((x, 52.0, x + 4.0, 92.0), scale), fill=WHITE)


# ------------------------------------------------------------------ garden


def draw_tree(draw, scale):
    draw.rectangle(s((58.0, 80.0, 70.0, 112.0), scale), fill=WHITE)
    for x, y, radius in ((48.0, 62.0, 16.0), (64.0, 50.0, 20.0),
                         (80.0, 62.0, 16.0)):
        ell(draw, (x - radius, y - radius, x + radius, y + radius), scale)


def draw_flower(draw, scale):
    draw.rectangle(s((61.0, 60.0, 67.0, 104.0), scale), fill=WHITE)
    draw.polygon(s([(61.0, 78.0), (46.0, 72.0), (48.0, 84.0)], scale),
                 fill=WHITE)
    draw.polygon(s([(67.0, 86.0), (82.0, 80.0), (80.0, 92.0)], scale),
                 fill=WHITE)
    for angle in range(0, 360, 60):
        radians = math.radians(angle)
        ell(draw, (64.0 + math.cos(radians) * 14.0 - 7.0,
                   38.0 + math.sin(radians) * 14.0 - 7.0,
                   64.0 + math.cos(radians) * 14.0 + 7.0,
                   38.0 + math.sin(radians) * 14.0 + 7.0), scale)
    ell(draw, (59.0, 33.0, 69.0, 43.0), scale, fill=CLEAR)
    ell(draw, (61.0, 35.0, 67.0, 41.0), scale)


def draw_sprinkler(draw, scale):
    draw.rectangle(s((96.0, 74.0, 108.0, 80.0), scale), fill=WHITE)
    draw.rectangle(s((36.0, 82.0, 44.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((84.0, 82.0, 92.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 72.0, 100.0, 82.0), scale), fill=WHITE)
    bar(draw, (42.0, 60.0), scale, 13.0, 4.0, 70.0)
    bar(draw, (53.0, 56.0), scale, 15.0, 4.0, 80.0)
    bar(draw, (64.0, 55.0), scale, 16.0, 4.0, 90.0)
    bar(draw, (75.0, 56.0), scale, 15.0, 4.0, 100.0)
    bar(draw, (86.0, 60.0), scale, 13.0, 4.0, 110.0)


def draw_mower(draw, scale):
    bar(draw, (44.0, 52.0), scale, 34.0, 7.0, 225.0)
    rr(draw, (30.0, 74.0, 86.0, 96.0), scale, 8.0)
    draw.rectangle(s((70.0, 58.0, 94.0, 78.0), scale), fill=WHITE)
    ell(draw, (36.0, 86.0, 60.0, 110.0), scale)
    ell(draw, (70.0, 90.0, 88.0, 108.0), scale)


def draw_grill(draw, scale):
    draw.rectangle(s((60.0, 24.0, 68.0, 36.0), scale), fill=WHITE)
    ell(draw, (36.0, 36.0, 92.0, 72.0), scale)
    draw.rectangle(s((36.0, 54.0, 92.0, 72.0), scale), fill=CLEAR)
    ell(draw, (36.0, 54.0, 92.0, 90.0), scale)
    draw.rectangle(s((36.0, 54.0, 92.0, 72.0), scale), fill=CLEAR)
    draw.rectangle(s((36.0, 70.0, 92.0, 74.0), scale), fill=WHITE)
    draw.rectangle(s((46.0, 90.0, 52.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((76.0, 90.0, 82.0, 110.0), scale), fill=WHITE)
    for x in (52.0, 62.0, 72.0):
        ell(draw, (x - 2.0, 42.0, x + 2.0, 46.0), scale, fill=CLEAR)


def draw_birdhouse(draw, scale):
    draw.rectangle(s((60.0, 108.0, 68.0, 120.0), scale), fill=WHITE)
    draw.polygon(s([(40.0, 62.0), (40.0, 110.0), (88.0, 110.0), (88.0, 62.0),
                    (64.0, 38.0)], scale), fill=WHITE)
    draw.polygon(s([(32.0, 64.0), (64.0, 34.0), (96.0, 64.0)], scale),
                 fill=WHITE)
    ell(draw, (57.0, 72.0, 71.0, 86.0), scale, fill=CLEAR)
    draw.rectangle(s((56.0, 90.0, 72.0, 94.0), scale), fill=WHITE)


def draw_planter(draw, scale):
    draw.rectangle(s((61.0, 44.0, 67.0, 64.0), scale), fill=WHITE)
    draw.polygon(s([(61.0, 50.0), (44.0, 42.0), (46.0, 54.0)], scale),
                 fill=WHITE)
    draw.polygon(s([(67.0, 50.0), (84.0, 42.0), (82.0, 54.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((36.0, 64.0, 92.0, 74.0), scale), fill=WHITE)
    draw.polygon(s([(40.0, 74.0), (88.0, 74.0), (80.0, 106.0), (48.0, 106.0)],
                   scale), fill=WHITE)


def draw_hose_reel(draw, scale):
    draw.rectangle(s((40.0, 96.0, 48.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 96.0, 80.0, 112.0), scale), fill=WHITE)
    ell(draw, (34.0, 44.0, 86.0, 96.0), scale)
    ell(draw, (46.0, 56.0, 74.0, 84.0), scale, fill=CLEAR)
    ell(draw, (58.0, 68.0, 70.0, 80.0), scale)
    draw.rectangle(s((86.0, 60.0, 100.0, 68.0), scale), fill=WHITE)
    bar(draw, (78.0, 59.0), scale, 16.0, 5.0, -45.0)
    ell(draw, (86.0, 40.0, 94.0, 48.0), scale)


# ------------------------------------------------------------------ energy


def draw_solar_panel(draw, scale):
    draw.rectangle(s((44.0, 92.0, 50.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((78.0, 92.0, 84.0, 110.0), scale), fill=WHITE)
    rr(draw, (26.0, 40.0, 102.0, 92.0), scale, 4.0)
    draw.rectangle(s((48.0, 40.0, 52.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((76.0, 40.0, 80.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((26.0, 62.0, 102.0, 66.0), scale), fill=CLEAR)


def draw_meter(draw, scale):
    rr(draw, (36.0, 28.0, 92.0, 100.0), scale, 8.0)
    ell(draw, (48.0, 40.0, 80.0, 72.0), scale)
    ell(draw, (54.0, 46.0, 74.0, 66.0), scale, fill=CLEAR)
    bar(draw, (64.0, 56.0), scale, 8.0, 3.0, 300.0)
    draw.rectangle(s((48.0, 80.0, 80.0, 88.0), scale), fill=CLEAR)


def draw_ev_charger(draw, scale):
    draw.rectangle(s((54.0, 60.0, 74.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((74.0, 70.0, 80.0, 100.0), scale), fill=WHITE)
    rr(draw, (44.0, 28.0, 84.0, 62.0), scale, 8.0)
    draw.polygon(s([(66.0, 34.0), (56.0, 48.0), (62.0, 48.0), (60.0, 58.0),
                    (70.0, 44.0), (64.0, 44.0)], scale), fill=CLEAR)


def draw_battery_charge(draw, scale):
    draw.rectangle(s((96.0, 58.0, 106.0, 74.0), scale), fill=WHITE)
    rr(draw, (14.0, 44.0, 96.0, 88.0), scale, 10.0)
    draw.polygon(s([(58.0, 50.0), (44.0, 70.0), (53.0, 70.0), (50.0, 82.0),
                    (66.0, 62.0), (57.0, 62.0)], scale), fill=CLEAR)


def draw_battery_low(draw, scale):
    draw.rectangle(s((96.0, 58.0, 106.0, 74.0), scale), fill=WHITE)
    rr(draw, (14.0, 44.0, 96.0, 88.0), scale, 10.0)
    draw.rectangle(s((24.0, 54.0, 86.0, 78.0), scale), fill=CLEAR)
    draw.rectangle(s((24.0, 54.0, 40.0, 78.0), scale), fill=WHITE)


def draw_wind_turbine(draw, scale):
    draw.rectangle(s((60.0, 58.0, 68.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((60.0, 50.0, 76.0, 58.0), scale), fill=WHITE)
    for angle in (270.0, 30.0, 150.0):
        blade(draw, (72.0, 50.0), scale, 34.0, 9.0, angle)
    ell(draw, (67.0, 45.0, 77.0, 55.0), scale)


def draw_hydro(draw, scale):
    draw.polygon(s([(66.0, 28.0), (52.0, 56.0), (60.0, 56.0), (57.0, 76.0),
                    (74.0, 50.0), (65.0, 50.0)], scale), fill=WHITE)
    draw.rectangle(s((28.0, 86.0, 100.0, 94.0), scale), fill=WHITE)
    draw.rectangle(s((38.0, 100.0, 90.0, 108.0), scale), fill=WHITE)


def draw_power_pole(draw, scale):
    draw.rectangle(s((59.0, 20.0, 69.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((35.0, 34.0, 93.0, 42.0), scale), fill=WHITE)
    draw.rectangle(s((41.0, 52.0, 87.0, 60.0), scale), fill=WHITE)
    for x in (43.0, 61.0, 79.0):
        ell(draw, (x - 3.0, 28.0, x + 3.0, 34.0), scale)


GLYPHS = {
    "chandelier": draw_chandelier,
    "pendant-lamp": draw_pendant_lamp,
    "lantern": draw_lantern,
    "flashlight": draw_flashlight,
    "spotlight": draw_spotlight,
    "string-light": draw_string_light,
    "candle": draw_candle,
    "lamp-shade": draw_lamp_shade,
    "night-light": draw_night_light,
    "track-light": draw_track_light,
    "garden-light": draw_garden_light,
    "disco-ball": draw_disco_ball,
    "lamp-post": draw_lamp_post,
    "socket": draw_socket,
    "power": draw_power,
    "toggle": draw_toggle,
    "dimmer": draw_dimmer,
    "double-switch": draw_double_switch,
    "remote": draw_remote,
    "timer": draw_timer,
    "power-strip": draw_power_strip,
    "charger": draw_charger,
    "button": draw_button,
    "breaker": draw_breaker,
    "ceiling-fan": draw_ceiling_fan,
    "air-purifier": draw_air_purifier,
    "humidifier": draw_humidifier,
    "dehumidifier": draw_dehumidifier,
    "vent": draw_vent,
    "stove": draw_stove,
    "humidity": draw_humidity,
    "droplet": draw_droplet,
    "leaf": draw_leaf,
    "water-heater": draw_water_heater,
    "heat-pump": draw_heat_pump,
    "chimney": draw_chimney,
    "awning": draw_awning,
    "pergola": draw_pergola,
    "fence": draw_fence,
    "gate": draw_gate,
    "shutters": draw_shutters,
    "skylight": draw_skylight,
    "sun-umbrella": draw_sun_umbrella,
    "greenhouse": draw_greenhouse,
    "shed": draw_shed,
    "mailbox": draw_mailbox,
    "partly-cloudy": draw_partly_cloudy,
    "thunderstorm": draw_thunderstorm,
    "fog": draw_fog,
    "hail": draw_hail,
    "rainbow": draw_rainbow,
    "sunrise": draw_sunrise,
    "starry-night": draw_starry_night,
    "umbrella": draw_umbrella,
    "lightning": draw_lightning,
    "eclipse": draw_eclipse,
    "overcast": draw_overcast,
    "sleet": draw_sleet,
    "smoke-detector": draw_smoke_detector,
    "siren": draw_siren,
    "alarm-clock": draw_alarm_clock,
    "shield": draw_shield,
    "keypad": draw_keypad,
    "key": draw_key,
    "camera-dome": draw_camera_dome,
    "intercom": draw_intercom,
    "leak": draw_leak,
    "panic-button": draw_panic_button,
    "lock-open": draw_lock_open,
    "safe": draw_safe,
    "video-doorbell": draw_video_doorbell,
    "window-sensor": draw_window_sensor,
    "soundbar": draw_soundbar,
    "projector": draw_projector,
    "screen": draw_screen,
    "gamepad": draw_gamepad,
    "radio": draw_radio,
    "microphone": draw_microphone,
    "headphones": draw_headphones,
    "laptop": draw_laptop,
    "tablet": draw_tablet,
    "phone": draw_phone,
    "printer": draw_printer,
    "router": draw_router,
    "fridge": draw_fridge,
    "oven": draw_oven,
    "microwave": draw_microwave,
    "kettle": draw_kettle,
    "coffee-mug": draw_coffee_mug,
    "toaster": draw_toaster,
    "cooker-hood": draw_cooker_hood,
    "faucet": draw_faucet,
    "dishwasher": draw_dishwasher,
    "blender": draw_blender,
    "trash-can": draw_trash_can,
    "cooktop": draw_cooktop,
    "shower": draw_shower,
    "bathtub": draw_bathtub,
    "toilet": draw_toilet,
    "washer": draw_washer,
    "iron": draw_iron,
    "robot-vacuum": draw_robot_vacuum,
    "hamper": draw_hamper,
    "soap-dispenser": draw_soap_dispenser,
    "bath-scale": draw_bath_scale,
    "towel": draw_towel,
    "sofa": draw_sofa,
    "armchair": draw_armchair,
    "bed": draw_bed,
    "chair": draw_chair,
    "table": draw_table,
    "desk": draw_desk,
    "wardrobe": draw_wardrobe,
    "shelf": draw_shelf,
    "clock": draw_clock,
    "books": draw_books,
    "plant": draw_plant,
    "crib": draw_crib,
    "tree": draw_tree,
    "flower": draw_flower,
    "sprinkler": draw_sprinkler,
    "mower": draw_mower,
    "grill": draw_grill,
    "birdhouse": draw_birdhouse,
    "planter": draw_planter,
    "hose-reel": draw_hose_reel,
    "solar-panel": draw_solar_panel,
    "meter": draw_meter,
    "ev-charger": draw_ev_charger,
    "battery-charge": draw_battery_charge,
    "battery-low": draw_battery_low,
    "wind-turbine": draw_wind_turbine,
    "hydro": draw_hydro,
    "power-pole": draw_power_pole,
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
