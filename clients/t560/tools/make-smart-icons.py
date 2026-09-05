#!/usr/bin/python3

"""Render the fourth batch of card icons: the smart-home set.

150 glyphs, strictly things a smart home actually automates: lights,
switches, sensors, HVAC, covers, locks, cameras, energy, appliances, garden
and network gear. Same technique and style as the earlier batches — bold
filled alpha masks drawn at four times the output size and scaled down. A
separate file only to keep either one readable.

Run from `clients/t560`:

    python3 tools/make-smart-icons.py

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


def hexagon(draw, center, scale, radius, width, fill=WHITE):
    """Draw a stroked hexagon outline given in output pixels."""
    points = []
    for step in range(6):
        angle = math.radians(60.0 * step)
        points.append((center[0] + math.cos(angle) * radius,
                       center[1] + math.sin(angle) * radius))
    draw.polygon(s(points, scale), outline=fill, width=int(width * scale))
    inner = radius - width
    inner_points = []
    for step in range(6):
        angle = math.radians(60.0 * step)
        inner_points.append((center[0] + math.cos(angle) * inner,
                             center[1] + math.sin(angle) * inner))
    draw.polygon(s(inner_points, scale), fill=CLEAR)


def new_surface(scale):
    """Return a blank mask and its drawing context."""
    mask = Image.new("L", (SIZE * scale, SIZE * scale), 0)
    return mask, ImageDraw.Draw(mask)


# ------------------------------------------------------------------ lights


def draw_downlight(draw, scale):
    draw.rectangle(s((20.0, 16.0, 108.0, 26.0), scale), fill=WHITE)
    draw.polygon(s([(44.0, 26.0), (84.0, 26.0), (72.0, 66.0), (56.0, 66.0)],
                   scale), fill=WHITE)
    ell(draw, (58.0, 66.0, 70.0, 78.0), scale)


def draw_globe_lamp(draw, scale):
    rr(draw, (48.0, 100.0, 80.0, 110.0), scale, 4.0)
    draw.rectangle(s((60.0, 56.0, 68.0, 100.0), scale), fill=WHITE)
    ell(draw, (40.0, 14.0, 88.0, 62.0), scale)


def draw_filament(draw, scale):
    ell(draw, (38.0, 12.0, 90.0, 64.0), scale)
    draw.rectangle(s((52.0, 60.0, 76.0, 78.0), scale), fill=WHITE)
    rr(draw, (54.0, 78.0, 74.0, 96.0), scale, 5.0)
    ell(draw, (59.0, 98.0, 69.0, 106.0), scale)
    bar(draw, (58.0, 37.0), scale, 10.0, 4.0, 63.0, fill=CLEAR)
    bar(draw, (70.0, 37.0), scale, 10.0, 4.0, 117.0, fill=CLEAR)


def draw_tube_light(draw, scale):
    draw.rectangle(s((40.0, 42.0, 48.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 42.0, 88.0, 52.0), scale), fill=WHITE)
    rr(draw, (20.0, 52.0, 108.0, 72.0), scale, 10.0)
    draw.rectangle(s((14.0, 48.0, 22.0, 76.0), scale), fill=WHITE)
    draw.rectangle(s((106.0, 48.0, 114.0, 76.0), scale), fill=WHITE)


def draw_panel_light(draw, scale):
    rr(draw, (30.0, 30.0, 98.0, 98.0), scale, 6.0)
    rr(draw, (40.0, 40.0, 88.0, 88.0), scale, 4.0, fill=CLEAR)
    ell(draw, (60.0, 60.0, 68.0, 68.0), scale)


def draw_neon(draw, scale):
    draw.rectangle(s((24.0, 44.0, 32.0, 84.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 44.0, 104.0, 84.0), scale), fill=WHITE)
    bar(draw, (42.0, 63.0), scale, 14.0, 9.0, 28.0)
    bar(draw, (62.0, 63.0), scale, 14.0, 9.0, -28.0)
    bar(draw, (82.0, 63.0), scale, 14.0, 9.0, 28.0)
    ell(draw, (28.0, 55.0, 38.0, 65.0), scale)
    ell(draw, (88.0, 55.0, 98.0, 65.0), scale)


def draw_path_light(draw, scale):
    ell(draw, (28.0, 96.0, 100.0, 114.0), scale)
    draw.rectangle(s((58.0, 52.0, 70.0, 96.0), scale), fill=WHITE)
    ell(draw, (46.0, 32.0, 82.0, 62.0), scale)
    draw.rectangle(s((46.0, 47.0, 82.0, 62.0), scale), fill=CLEAR)
    draw.rectangle(s((58.0, 42.0, 70.0, 50.0), scale), fill=CLEAR)


def draw_stair_light(draw, scale):
    draw.polygon(s([(20.0, 104.0), (20.0, 80.0), (44.0, 80.0), (44.0, 60.0),
                    (68.0, 60.0), (68.0, 40.0), (108.0, 40.0), (108.0, 104.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((20.0, 88.0, 32.0, 94.0), scale), fill=CLEAR)
    draw.rectangle(s((44.0, 68.0, 56.0, 74.0), scale), fill=CLEAR)


def draw_pool_light(draw, scale):
    rr(draw, (40.0, 30.0, 88.0, 78.0), scale, 12.0)
    ell(draw, (50.0, 40.0, 78.0, 68.0), scale, fill=CLEAR)
    ell(draw, (58.0, 48.0, 70.0, 60.0), scale)
    draw.rectangle(s((30.0, 90.0, 98.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 102.0, 88.0, 108.0), scale), fill=WHITE)


def draw_cabinet_light(draw, scale):
    draw.rectangle(s((52.0, 20.0, 76.0, 32.0), scale), fill=WHITE)
    ell(draw, (44.0, 32.0, 84.0, 72.0), scale)
    for x in (54.0, 64.0, 74.0):
        bar(draw, (x, 84.0), scale, 8.0, 5.0, 90.0)


def draw_vanity_light(draw, scale):
    draw.rectangle(s((24.0, 40.0, 32.0, 80.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 40.0, 104.0, 80.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 54.0, 104.0, 64.0), scale), fill=WHITE)
    for x in (36.0, 55.0, 74.0):
        ell(draw, (x, 30.0, x + 18.0, 48.0), scale)


def draw_picture_light(draw, scale):
    draw.rectangle(s((30.0, 32.0, 98.0, 42.0), scale), fill=WHITE)
    draw.rectangle(s((44.0, 42.0, 50.0, 48.0), scale), fill=WHITE)
    draw.rectangle(s((78.0, 42.0, 84.0, 48.0), scale), fill=WHITE)
    rr(draw, (36.0, 48.0, 92.0, 104.0), scale, 4.0)
    draw.rectangle(s((44.0, 56.0, 84.0, 96.0), scale), fill=CLEAR)


def draw_grow_light(draw, scale):
    draw.rectangle(s((34.0, 60.0, 40.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 60.0, 94.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 48.0, 94.0, 56.0), scale), fill=WHITE)
    draw.rectangle(s((48.0, 56.0, 52.0, 64.0), scale), fill=WHITE)
    draw.rectangle(s((76.0, 56.0, 80.0, 64.0), scale), fill=WHITE)
    draw.rectangle(s((44.0, 64.0, 84.0, 78.0), scale), fill=WHITE)
    for x in (52.0, 64.0, 76.0):
        bar(draw, (x, 90.0), scale, 8.0, 4.0, 90.0)
    draw.rectangle(s((61.0, 98.0, 67.0, 112.0), scale), fill=WHITE)
    draw.polygon(s([(61.0, 104.0), (48.0, 98.0), (50.0, 108.0)], scale),
                 fill=WHITE)
    draw.polygon(s([(67.0, 104.0), (80.0, 98.0), (78.0, 108.0)], scale),
                 fill=WHITE)


def draw_emergency_light(draw, scale):
    draw.rectangle(s((58.0, 28.0, 70.0, 40.0), scale), fill=WHITE)
    rr(draw, (36.0, 40.0, 92.0, 68.0), scale, 8.0)
    ell(draw, (60.0, 48.0, 68.0, 56.0), scale, fill=CLEAR)
    draw.polygon(s([(40.0, 68.0), (56.0, 68.0), (52.0, 90.0), (44.0, 90.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(72.0, 68.0), (88.0, 68.0), (84.0, 90.0), (76.0, 90.0)],
                   scale), fill=WHITE)


# ---------------------------------------------------------------- switches


def draw_rotary_dimmer(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    ell(draw, (50.0, 46.0, 78.0, 74.0), scale)
    draw.rectangle(s((62.0, 48.0, 66.0, 58.0), scale), fill=CLEAR)
    for step in range(5):
        angle = math.radians(200.0 + step * 35.0)
        x = 64.0 + math.cos(angle) * 24.0
        y = 60.0 + math.sin(angle) * 24.0
        ell(draw, (x - 2.0, y - 2.0, x + 2.0, y + 2.0), scale, fill=CLEAR)


def draw_touch_panel(draw, scale):
    rr(draw, (36.0, 24.0, 92.0, 104.0), scale, 8.0)
    ell(draw, (48.0, 40.0, 80.0, 72.0), scale, fill=CLEAR)
    ell(draw, (54.0, 46.0, 74.0, 66.0), scale)
    draw.rectangle(s((52.0, 84.0, 76.0, 90.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 82.0, 68.0, 92.0), scale), fill=WHITE)


def draw_scene_switch(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    ell(draw, (52.0, 44.0, 60.0, 52.0), scale)
    ell(draw, (68.0, 44.0, 76.0, 52.0), scale)
    ell(draw, (52.0, 60.0, 60.0, 68.0), scale, fill=CLEAR)
    ell(draw, (68.0, 60.0, 76.0, 68.0), scale, fill=CLEAR)
    draw.rectangle(s((52.0, 92.0, 76.0, 97.0), scale), fill=CLEAR)


def draw_blind_switch(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    draw.polygon(s([(52.0, 48.0), (64.0, 36.0), (76.0, 48.0), (76.0, 56.0),
                    (64.0, 44.0), (52.0, 56.0)], scale), fill=CLEAR)
    draw.polygon(s([(52.0, 72.0), (64.0, 84.0), (76.0, 72.0), (76.0, 64.0),
                    (64.0, 76.0), (52.0, 64.0)], scale), fill=CLEAR)


def draw_round_thermostat(draw, scale):
    ell(draw, (36.0, 36.0, 92.0, 92.0), scale)
    ell(draw, (48.0, 48.0, 80.0, 80.0), scale, fill=CLEAR)
    rr(draw, (54.0, 58.0, 74.0, 70.0), scale, 3.0)
    for step in range(3):
        angle = math.radians(210.0 + step * 60.0)
        x = 64.0 + math.cos(angle) * 26.0
        y = 64.0 + math.sin(angle) * 26.0
        ell(draw, (x - 2.0, y - 2.0, x + 2.0, y + 2.0), scale, fill=CLEAR)


def draw_radiator_valve(draw, scale):
    draw.rectangle(s((28.0, 84.0, 70.0, 92.0), scale), fill=WHITE)
    draw.rectangle(s((56.0, 60.0, 64.0, 84.0), scale), fill=WHITE)
    draw.rectangle(s((50.0, 48.0, 70.0, 60.0), scale), fill=WHITE)
    ell(draw, (44.0, 22.0, 76.0, 54.0), scale)
    for x in (50.0, 58.0, 66.0):
        draw.rectangle(s((x, 28.0, x + 3.0, 48.0), scale), fill=CLEAR)


def draw_din_relay(draw, scale):
    rr(draw, (34.0, 28.0, 94.0, 100.0), scale, 8.0)
    for x in (42.0, 58.0, 74.0):
        draw.rectangle(s((x, 28.0, x + 8.0, 40.0), scale), fill=CLEAR)
    rr(draw, (48.0, 50.0, 80.0, 94.0), scale, 4.0, fill=CLEAR)
    ell(draw, (58.0, 56.0, 70.0, 68.0), scale)
    draw.rectangle(s((56.0, 74.0, 72.0, 88.0), scale), fill=WHITE)


def draw_smart_meter(draw, scale):
    rr(draw, (36.0, 32.0, 92.0, 96.0), scale, 8.0)
    draw.polygon(s([(66.0, 40.0), (56.0, 56.0), (62.0, 56.0), (60.0, 68.0),
                    (70.0, 54.0), (64.0, 54.0)], scale), fill=CLEAR)
    rr(draw, (48.0, 74.0, 80.0, 86.0), scale, 3.0, fill=CLEAR)


def draw_nfc_tag(draw, scale):
    rr(draw, (34.0, 34.0, 94.0, 94.0), scale, 12.0)
    draw.ellipse(s((44.0, 44.0, 84.0, 84.0), scale), outline=WHITE, width=5)
    draw.ellipse(s((52.0, 52.0, 76.0, 76.0), scale), outline=WHITE, width=5)
    ell(draw, (60.0, 60.0, 68.0, 68.0), scale)


def draw_ir_blaster(draw, scale):
    rr(draw, (44.0, 88.0, 84.0, 100.0), scale, 5.0)
    ell(draw, (46.0, 52.0, 82.0, 92.0), scale)
    draw.rectangle(s((46.0, 72.0, 82.0, 92.0), scale), fill=CLEAR)
    ray_fan(draw, (64.0, 60.0), scale, 26.0, 34.0, 5.0,
            (180.0, 225.0, 270.0, 315.0, 360.0))


def draw_dual_relay(draw, scale):
    rr(draw, (32.0, 36.0, 96.0, 92.0), scale, 8.0)
    ell(draw, (44.0, 42.0, 50.0, 48.0), scale, fill=CLEAR)
    ell(draw, (78.0, 42.0, 84.0, 48.0), scale, fill=CLEAR)
    draw.rectangle(s((40.0, 54.0, 58.0, 84.0), scale), fill=CLEAR)
    draw.rectangle(s((70.0, 54.0, 88.0, 84.0), scale), fill=CLEAR)
    draw.rectangle(s((42.0, 56.0, 56.0, 82.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 56.0, 86.0, 82.0), scale), fill=WHITE)


def draw_fan_switch(draw, scale):
    rr(draw, (40.0, 20.0, 88.0, 108.0), scale, 10.0)
    for angle in (90.0, 210.0, 330.0):
        blade(draw, (64.0, 44.0), scale, 12.0, 6.0, angle, fill=CLEAR)
    ell(draw, (61.0, 41.0, 67.0, 47.0), scale, fill=CLEAR)
    draw.rectangle(s((60.0, 62.0, 68.0, 96.0), scale), fill=CLEAR)
    ell(draw, (55.0, 70.0, 69.0, 84.0), scale)

# ----------------------------------------------------------------- sensors


def draw_temp_sensor(draw, scale):
    rr(draw, (40.0, 32.0, 88.0, 96.0), scale, 16.0)
    draw.rectangle(s((60.0, 48.0, 68.0, 76.0), scale), fill=CLEAR)
    ell(draw, (56.0, 72.0, 72.0, 88.0), scale, fill=CLEAR)


def draw_humidity_sensor(draw, scale):
    rr(draw, (38.0, 36.0, 90.0, 92.0), scale, 12.0)
    ell(draw, (54.0, 48.0, 74.0, 68.0), scale, fill=CLEAR)
    draw.polygon(s([(54.0, 58.0), (74.0, 58.0), (64.0, 40.0)], scale),
                 fill=CLEAR)
    draw.rectangle(s((48.0, 78.0, 80.0, 82.0), scale), fill=CLEAR)


def draw_pir_sensor(draw, scale):
    draw.rectangle(s((52.0, 20.0, 76.0, 32.0), scale), fill=WHITE)
    draw.polygon(s([(36.0, 32.0), (92.0, 32.0), (84.0, 72.0), (44.0, 72.0)],
                   scale), fill=WHITE)
    for x in (52.0, 61.0, 70.0):
        draw.rectangle(s((x, 40.0, x + 6.0, 64.0), scale), fill=CLEAR)
    ell(draw, (61.0, 76.0, 67.0, 82.0), scale, fill=CLEAR)


def draw_air_quality(draw, scale):
    rr(draw, (36.0, 36.0, 92.0, 92.0), scale, 10.0)
    draw.polygon(s([(64.0, 44.0), (78.0, 60.0), (64.0, 78.0), (50.0, 60.0)],
                   scale), fill=CLEAR)
    draw.rectangle(s((46.0, 80.0, 82.0, 84.0), scale), fill=CLEAR)


def draw_co2_monitor(draw, scale):
    rr(draw, (36.0, 32.0, 92.0, 96.0), scale, 10.0)
    for x, y, radius in ((48.0, 54.0, 10.0), (62.0, 48.0, 13.0),
                         (76.0, 54.0, 9.0)):
        ell(draw, (x - radius, y - radius, x + radius, y + radius), scale,
            fill=CLEAR)
    draw.rectangle(s((46.0, 54.0, 78.0, 66.0), scale), fill=CLEAR)
    for x, top, height in ((52.0, 56.0, 8.0), (60.0, 52.0, 12.0),
                           (68.0, 58.0, 6.0)):
        draw.rectangle(s((x, top, x + 5.0, top + height), scale), fill=WHITE)
    draw.rectangle(s((48.0, 78.0, 80.0, 84.0), scale), fill=CLEAR)


def draw_sound_sensor(draw, scale):
    rr(draw, (36.0, 36.0, 92.0, 92.0), scale, 10.0)
    rr(draw, (46.0, 46.0, 82.0, 82.0), scale, 6.0, fill=CLEAR)
    for x, top, height in ((52.0, 62.0, 14.0), (60.0, 56.0, 20.0),
                           (68.0, 60.0, 16.0)):
        draw.rectangle(s((x, top, x + 5.0, top + height), scale), fill=WHITE)


def draw_soil_sensor(draw, scale):
    ell(draw, (24.0, 88.0, 104.0, 110.0), scale)
    draw.rectangle(s((52.0, 64.0, 58.0, 92.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 64.0, 76.0, 92.0), scale), fill=WHITE)
    rr(draw, (44.0, 32.0, 84.0, 64.0), scale, 8.0)
    ell(draw, (60.0, 42.0, 68.0, 50.0), scale, fill=CLEAR)


def draw_rain_gauge(draw, scale):
    ell(draw, (54.0, 16.0, 62.0, 24.0), scale)
    ell(draw, (66.0, 10.0, 74.0, 18.0), scale)
    draw.polygon(s([(44.0, 36.0), (84.0, 36.0), (74.0, 60.0), (54.0, 60.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((58.0, 60.0, 70.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((66.0, 70.0, 70.0, 73.0), scale), fill=CLEAR)
    draw.rectangle(s((66.0, 80.0, 70.0, 83.0), scale), fill=CLEAR)
    rr(draw, (50.0, 100.0, 78.0, 108.0), scale, 3.0)


def draw_anemometer(draw, scale):
    rr(draw, (51.0, 104.0, 77.0, 112.0), scale, 3.0)
    draw.rectangle(s((61.0, 56.0, 67.0, 104.0), scale), fill=WHITE)
    bar(draw, (64.0, 60.0), scale, 26.0, 4.0, 0.0)
    for step in range(3):
        angle = math.radians(30.0 + step * 120.0)
        x = 64.0 + math.cos(angle) * 26.0
        y = 60.0 + math.sin(angle) * 26.0
        ell(draw, (x - 6.0, y - 6.0, x + 6.0, y + 6.0), scale)
    draw.polygon(s([(64.0, 44.0), (40.0, 36.0), (40.0, 52.0)], scale),
                 fill=WHITE)


def draw_weather_station(draw, scale):
    draw.rectangle(s((60.0, 40.0, 68.0, 112.0), scale), fill=WHITE)
    for step in range(3):
        angle = math.radians(90.0 + step * 120.0)
        x = 64.0 + math.cos(angle) * 18.0
        y = 44.0 + math.sin(angle) * 18.0
        ell(draw, (x - 5.0, y - 5.0, x + 5.0, y + 5.0), scale)
    draw.polygon(s([(60.0, 58.0), (36.0, 52.0), (36.0, 64.0)], scale),
                 fill=WHITE)
    for top in (70.0, 80.0, 90.0):
        ell(draw, (46.0, top, 82.0, top + 8.0), scale)
    rr(draw, (72.0, 84.0, 100.0, 108.0), scale, 6.0)


def draw_flood_sensor(draw, scale):
    ell(draw, (36.0, 60.0, 92.0, 98.0), scale)
    ell(draw, (56.0, 66.0, 72.0, 82.0), scale, fill=CLEAR)
    draw.polygon(s([(56.0, 74.0), (72.0, 74.0), (64.0, 60.0)], scale),
                 fill=CLEAR)
    draw.rectangle(s((28.0, 104.0, 100.0, 110.0), scale), fill=WHITE)


def draw_gas_sensor(draw, scale):
    rr(draw, (38.0, 36.0, 90.0, 92.0), scale, 12.0)
    ell(draw, (56.0, 48.0, 72.0, 64.0), scale, fill=CLEAR)
    draw.polygon(s([(56.0, 56.0), (72.0, 56.0), (64.0, 38.0)], scale),
                 fill=CLEAR)
    draw.rectangle(s((48.0, 78.0, 80.0, 82.0), scale), fill=CLEAR)


def draw_vibration_sensor(draw, scale):
    draw.rectangle(s((50.0, 84.0, 56.0, 94.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 84.0, 78.0, 94.0), scale), fill=WHITE)
    rr(draw, (44.0, 48.0, 84.0, 84.0), scale, 10.0)
    for y in (56.0, 66.0, 76.0):
        draw.rectangle(s((20.0, y, 36.0, y + 4.0), scale), fill=WHITE)
        draw.rectangle(s((92.0, y, 108.0, y + 4.0), scale), fill=WHITE)


def draw_radar_sensor(draw, scale):
    rr(draw, (34.0, 34.0, 94.0, 94.0), scale, 10.0)
    draw.ellipse(s((44.0, 44.0, 84.0, 84.0), scale), outline=WHITE, width=5)
    draw.ellipse(s((52.0, 52.0, 76.0, 76.0), scale), outline=WHITE, width=5)
    ell(draw, (60.0, 60.0, 68.0, 68.0), scale)
    for x, y in ((40.0, 40.0), (88.0, 40.0), (40.0, 88.0), (88.0, 88.0)):
        ell(draw, (x - 2.0, y - 2.0, x + 2.0, y + 2.0), scale, fill=CLEAR)


def draw_beam_sensor(draw, scale):
    ell(draw, (21.0, 36.0, 35.0, 50.0), scale)
    ell(draw, (93.0, 36.0, 107.0, 50.0), scale)
    draw.rectangle(s((24.0, 44.0, 32.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 44.0, 104.0, 104.0), scale), fill=WHITE)
    for y in (58.0, 70.0, 82.0):
        draw.rectangle(s((40.0, y, 58.0, y + 4.0), scale), fill=WHITE)
        draw.rectangle(s((70.0, y, 88.0, y + 4.0), scale), fill=WHITE)
    rr(draw, (18.0, 104.0, 38.0, 110.0), scale, 2.0)
    rr(draw, (90.0, 104.0, 110.0, 110.0), scale, 2.0)


def draw_power_clamp(draw, scale):
    draw.rectangle(s((60.0, 8.0, 68.0, 120.0), scale), fill=WHITE)
    ell(draw, (40.0, 24.0, 88.0, 72.0), scale)
    ell(draw, (52.0, 36.0, 76.0, 60.0), scale, fill=CLEAR)
    draw.rectangle(s((60.0, 18.0, 68.0, 36.0), scale), fill=CLEAR)
    rr(draw, (80.0, 56.0, 104.0, 84.0), scale, 6.0)


def draw_water_meter(draw, scale):
    ell(draw, (36.0, 32.0, 92.0, 88.0), scale)
    ell(draw, (46.0, 42.0, 82.0, 78.0), scale, fill=CLEAR)
    ell(draw, (50.0, 46.0, 78.0, 74.0), scale)
    ell(draw, (58.0, 52.0, 70.0, 64.0), scale, fill=CLEAR)
    draw.polygon(s([(58.0, 58.0), (70.0, 58.0), (64.0, 48.0)], scale),
                 fill=CLEAR)
    bar(draw, (64.0, 60.0), scale, 9.0, 3.0, 125.0, fill=CLEAR)


def draw_gas_meter(draw, scale):
    ell(draw, (36.0, 32.0, 92.0, 88.0), scale)
    ell(draw, (46.0, 42.0, 82.0, 78.0), scale, fill=CLEAR)
    ell(draw, (50.0, 46.0, 78.0, 74.0), scale)
    ell(draw, (57.0, 52.0, 69.0, 64.0), scale, fill=CLEAR)
    draw.polygon(s([(57.0, 58.0), (69.0, 58.0), (63.0, 46.0)], scale),
                 fill=CLEAR)
    bar(draw, (64.0, 60.0), scale, 9.0, 3.0, 55.0, fill=CLEAR)


def draw_barometer(draw, scale):
    ell(draw, (56.0, 12.0, 72.0, 28.0), scale)
    ell(draw, (60.0, 16.0, 68.0, 24.0), scale, fill=CLEAR)
    ell(draw, (32.0, 28.0, 96.0, 92.0), scale)
    ell(draw, (42.0, 38.0, 86.0, 82.0), scale, fill=CLEAR)
    ell(draw, (46.0, 42.0, 82.0, 78.0), scale)
    bar(draw, (64.0, 60.0), scale, 11.0, 4.0, 300.0, fill=CLEAR)
    for x, y in ((64.0, 46.0), (78.0, 60.0), (64.0, 74.0), (50.0, 60.0)):
        ell(draw, (x - 2.0, y - 2.0, x + 2.0, y + 2.0), scale, fill=CLEAR)


def draw_bed_sensor(draw, scale):
    draw.rectangle(s((20.0, 52.0, 28.0, 76.0), scale), fill=WHITE)
    ell(draw, (30.0, 52.0, 48.0, 70.0), scale)
    ell(draw, (52.0, 60.0, 96.0, 88.0), scale)
    draw.rectangle(s((52.0, 74.0, 96.0, 88.0), scale), fill=CLEAR)
    draw.rectangle(s((20.0, 76.0, 108.0, 88.0), scale), fill=WHITE)

# ----------------------------------------------------------------- climate


def draw_split_ac(draw, scale):
    rr(draw, (16.0, 40.0, 112.0, 72.0), scale, 14.0)
    ell(draw, (30.0, 50.0, 38.0, 58.0), scale, fill=CLEAR)
    draw.rectangle(s((56.0, 52.0, 84.0, 58.0), scale), fill=CLEAR)
    draw.rectangle(s((24.0, 72.0, 104.0, 80.0), scale), fill=WHITE)


def draw_cassette_ac(draw, scale):
    rr(draw, (28.0, 28.0, 100.0, 100.0), scale, 8.0)
    rr(draw, (40.0, 40.0, 88.0, 88.0), scale, 4.0, fill=CLEAR)
    rr(draw, (48.0, 48.0, 80.0, 80.0), scale, 4.0)
    draw.rectangle(s((52.0, 58.0, 76.0, 62.0), scale), fill=CLEAR)
    draw.rectangle(s((52.0, 68.0, 76.0, 72.0), scale), fill=CLEAR)


def draw_portable_ac(draw, scale):
    ell(draw, (48.0, 104.0, 58.0, 112.0), scale)
    ell(draw, (70.0, 104.0, 80.0, 112.0), scale)
    rr(draw, (42.0, 24.0, 86.0, 104.0), scale, 10.0)
    draw.rectangle(s((50.0, 34.0, 78.0, 40.0), scale), fill=CLEAR)
    draw.rectangle(s((50.0, 46.0, 78.0, 52.0), scale), fill=CLEAR)
    ell(draw, (58.0, 60.0, 70.0, 72.0), scale, fill=CLEAR)
    draw.rectangle(s((86.0, 60.0, 104.0, 66.0), scale), fill=WHITE)
    draw.rectangle(s((98.0, 66.0, 104.0, 96.0), scale), fill=WHITE)


def draw_wall_convector(draw, scale):
    draw.rectangle(s((30.0, 96.0, 38.0, 106.0), scale), fill=WHITE)
    draw.rectangle(s((90.0, 96.0, 98.0, 106.0), scale), fill=WHITE)
    rr(draw, (20.0, 62.0, 108.0, 96.0), scale, 8.0)
    draw.rectangle(s((28.0, 66.0, 100.0, 72.0), scale), fill=CLEAR)
    draw.rectangle(s((28.0, 82.0, 100.0, 86.0), scale), fill=CLEAR)


def draw_towel_dryer(draw, scale):
    draw.rectangle(s((36.0, 24.0, 44.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((84.0, 24.0, 92.0, 108.0), scale), fill=WHITE)
    for top in (40.0, 60.0, 80.0):
        draw.rectangle(s((36.0, top, 92.0, top + 6.0), scale), fill=WHITE)
    draw.rectangle(s((50.0, 46.0, 78.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((50.0, 68.0, 78.0, 74.0), scale), fill=CLEAR)
    ell(draw, (86.0, 100.0, 94.0, 108.0), scale)


def draw_floor_heating(draw, scale):
    draw.rectangle(s((16.0, 96.0, 112.0, 106.0), scale), fill=WHITE)
    for x in (34.0, 60.0, 86.0):
        for top in (56.0, 68.0, 80.0):
            draw.rectangle(s((x, top, x + 10.0, top + 6.0), scale),
                           fill=WHITE)


def draw_ventilation_unit(draw, scale):
    bar(draw, (64.0, 64.0), scale, 44.0, 14.0, 30.0)
    bar(draw, (64.0, 64.0), scale, 44.0, 14.0, -30.0)
    rr(draw, (40.0, 40.0, 88.0, 88.0), scale, 8.0)
    ell(draw, (52.0, 52.0, 76.0, 76.0), scale)
    ell(draw, (58.0, 58.0, 70.0, 70.0), scale, fill=CLEAR)


def draw_air_damper(draw, scale):
    draw.rectangle(s((96.0, 40.0, 104.0, 54.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 54.0, 104.0, 78.0), scale), fill=WHITE)
    bar(draw, (64.0, 66.0), scale, 30.0, 10.0, 35.0, fill=CLEAR)


def draw_air_filter(draw, scale):
    draw.rectangle(s((56.0, 92.0, 72.0, 102.0), scale), fill=WHITE)
    rr(draw, (30.0, 36.0, 98.0, 92.0), scale, 6.0)
    for x in (46.0, 62.0, 78.0):
        draw.rectangle(s((x, 40.0, x + 3.0, 88.0), scale), fill=CLEAR)
    for y in (52.0, 66.0, 80.0):
        draw.rectangle(s((34.0, y, 94.0, y + 3.0), scale), fill=CLEAR)


def draw_pellet_stove(draw, scale):
    draw.rectangle(s((44.0, 20.0, 84.0, 28.0), scale), fill=WHITE)
    draw.rectangle(s((46.0, 108.0, 54.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((74.0, 108.0, 82.0, 114.0), scale), fill=WHITE)
    rr(draw, (40.0, 28.0, 88.0, 108.0), scale, 10.0)
    rr(draw, (50.0, 60.0, 78.0, 92.0), scale, 4.0, fill=CLEAR)
    ell(draw, (58.0, 74.0, 70.0, 86.0), scale)
    draw.polygon(s([(58.0, 80.0), (70.0, 80.0), (64.0, 68.0)], scale))


def draw_patio_heater(draw, scale):
    ell(draw, (46.0, 106.0, 82.0, 116.0), scale)
    draw.rectangle(s((60.0, 78.0, 68.0, 106.0), scale), fill=WHITE)
    draw.polygon(s([(32.0, 60.0), (96.0, 60.0), (88.0, 78.0), (40.0, 78.0)],
                   scale), fill=WHITE)
    ell(draw, (40.0, 36.0, 88.0, 60.0), scale)
    draw.rectangle(s((52.0, 44.0, 76.0, 48.0), scale), fill=CLEAR)


def draw_hot_tub(draw, scale):
    for x in (50.0, 68.0):
        bar(draw, (x, 50.0), scale, 8.0, 4.0, 90.0)
    draw.rectangle(s((18.0, 64.0, 110.0, 74.0), scale), fill=WHITE)
    draw.polygon(s([(24.0, 74.0), (104.0, 74.0), (96.0, 108.0), (32.0, 108.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((30.0, 78.0, 98.0, 86.0), scale), fill=CLEAR)
    draw.rectangle(s((30.0, 81.0, 98.0, 86.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 88.0, 112.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 96.0, 112.0, 104.0), scale), fill=WHITE)


def draw_tower_fan(draw, scale):
    ell(draw, (40.0, 106.0, 88.0, 116.0), scale)
    rr(draw, (48.0, 16.0, 80.0, 112.0), scale, 12.0)
    draw.rectangle(s((58.0, 32.0, 70.0, 96.0), scale), fill=CLEAR)
    ell(draw, (60.0, 22.0, 68.0, 30.0), scale, fill=CLEAR)


def draw_mini_fan(draw, scale):
    draw.rectangle(s((60.0, 80.0, 68.0, 94.0), scale), fill=WHITE)
    ell(draw, (46.0, 94.0, 82.0, 106.0), scale)
    ell(draw, (36.0, 24.0, 92.0, 80.0), scale)
    ell(draw, (46.0, 34.0, 82.0, 70.0), scale, fill=CLEAR)
    for angle in (90.0, 210.0, 330.0):
        blade(draw, (64.0, 52.0), scale, 16.0, 8.0, angle)
    ell(draw, (59.0, 47.0, 69.0, 57.0), scale)


def draw_oil_radiator(draw, scale):
    draw.rectangle(s((24.0, 36.0, 108.0, 46.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 90.0, 108.0, 98.0), scale), fill=WHITE)
    for x in (28.0, 42.0, 56.0, 70.0, 84.0):
        rr(draw, (x, 44.0, x + 12.0, 92.0), scale, 6.0)
    draw.rectangle(s((32.0, 98.0, 40.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 98.0, 96.0, 110.0), scale), fill=WHITE)
    ell(draw, (92.0, 38.0, 100.0, 46.0), scale, fill=CLEAR)


def draw_radiant_panel(draw, scale):
    draw.rectangle(s((40.0, 16.0, 48.0, 30.0), scale), fill=WHITE)
    draw.rectangle(s((80.0, 16.0, 88.0, 30.0), scale), fill=WHITE)
    rr(draw, (28.0, 30.0, 100.0, 66.0), scale, 4.0)
    for x in (44.0, 64.0, 84.0):
        bar(draw, (x, 80.0), scale, 10.0, 5.0, 90.0)


# ------------------------------------------------------------------ covers


def draw_roller_blind(draw, scale):
    draw.rectangle(s((24.0, 24.0, 32.0, 48.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 24.0, 104.0, 48.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 32.0, 104.0, 44.0), scale), fill=WHITE)
    draw.rectangle(s((32.0, 44.0, 96.0, 92.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 92.0, 100.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 100.0, 92.0, 114.0), scale), fill=WHITE)
    ell(draw, (85.0, 114.0, 95.0, 122.0), scale)


def draw_roman_shade(draw, scale):
    draw.rectangle(s((28.0, 24.0, 100.0, 34.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 34.0, 94.0, 96.0), scale), fill=WHITE)
    for top in (48.0, 62.0, 76.0):
        draw.rectangle(s((34.0, top, 94.0, top + 4.0), scale), fill=CLEAR)
    draw.rectangle(s((30.0, 96.0, 98.0, 104.0), scale), fill=WHITE)


def draw_vertical_blind(draw, scale):
    draw.rectangle(s((24.0, 24.0, 104.0, 36.0), scale), fill=WHITE)
    for x in (30.0, 44.0, 58.0, 72.0, 86.0):
        draw.rectangle(s((x, 36.0, x + 9.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 96.0, 100.0, 102.0), scale), fill=WHITE)
    draw.rectangle(s((100.0, 36.0, 104.0, 70.0), scale), fill=WHITE)
    ell(draw, (98.0, 70.0, 106.0, 78.0), scale)


def draw_blackout_curtain(draw, scale):
    draw.rectangle(s((16.0, 22.0, 112.0, 30.0), scale), fill=WHITE)
    ell(draw, (10.0, 19.0, 22.0, 33.0), scale)
    ell(draw, (106.0, 19.0, 118.0, 33.0), scale)
    draw.polygon(s([(26.0, 30.0), (102.0, 30.0), (96.0, 106.0), (32.0, 106.0)],
                   scale), fill=WHITE)
    ell(draw, (48.0, 50.0, 80.0, 82.0), scale, fill=CLEAR)
    ell(draw, (58.0, 42.0, 90.0, 74.0), scale)
    ell(draw, (88.0, 58.0, 94.0, 64.0), scale, fill=CLEAR)
    ell(draw, (40.0, 84.0, 46.0, 90.0), scale, fill=CLEAR)


def draw_roof_window(draw, scale):
    draw.polygon(s([(22.0, 86.0), (56.0, 34.0), (106.0, 50.0), (72.0, 102.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(36.0, 80.0), (60.0, 46.0), (94.0, 58.0), (70.0, 94.0)],
                   scale), fill=CLEAR)
    bar(draw, (65.0, 70.0), scale, 12.0, 4.0, 0.0)


def draw_barrier_gate(draw, scale):
    rr(draw, (18.0, 104.0, 46.0, 112.0), scale, 3.0)
    rr(draw, (24.0, 48.0, 40.0, 104.0), scale, 6.0)
    ell(draw, (26.0, 32.0, 38.0, 48.0), scale)
    bar(draw, (33.0, 26.0), scale, 8.0, 4.0, 90.0)
    bar(draw, (33.0, 26.0), scale, 8.0, 4.0, 150.0)
    draw.rectangle(s((40.0, 52.0, 108.0, 62.0), scale), fill=WHITE)
    for x in (56.0, 74.0, 92.0):
        bar(draw, (x, 57.0), scale, 8.0, 5.0, 60.0, fill=CLEAR)


def draw_swing_gate(draw, scale):
    ell(draw, (17.0, 36.0, 31.0, 50.0), scale)
    ell(draw, (97.0, 36.0, 111.0, 50.0), scale)
    draw.rectangle(s((20.0, 44.0, 28.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((100.0, 44.0, 108.0, 104.0), scale), fill=WHITE)
    draw.polygon(s([(28.0, 50.0), (60.0, 58.0), (60.0, 94.0), (28.0, 86.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(100.0, 50.0), (68.0, 58.0), (68.0, 94.0), (100.0, 86.0)],
                   scale), fill=WHITE)


def draw_roller_shutter(draw, scale):
    rr(draw, (28.0, 24.0, 100.0, 48.0), scale, 6.0)
    draw.rectangle(s((32.0, 48.0, 40.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 48.0, 96.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 48.0, 88.0, 100.0), scale), fill=WHITE)
    for top in (58.0, 67.0, 76.0, 85.0):
        draw.rectangle(s((40.0, top, 88.0, top + 3.0), scale), fill=CLEAR)
    draw.rectangle(s((36.0, 100.0, 92.0, 108.0), scale), fill=WHITE)


def draw_fly_screen(draw, scale):
    draw.rectangle(s((90.0, 96.0, 100.0, 106.0), scale), fill=WHITE)
    rr(draw, (30.0, 36.0, 98.0, 104.0), scale, 6.0)
    for x in (42.0, 54.0, 66.0, 78.0):
        draw.rectangle(s((x, 42.0, x + 2.0, 98.0), scale), fill=CLEAR)
    for y in (48.0, 60.0, 72.0, 84.0, 96.0):
        draw.rectangle(s((36.0, y, 92.0, y + 2.0), scale), fill=CLEAR)


def draw_honeycomb_shade(draw, scale):
    draw.rectangle(s((36.0, 28.0, 92.0, 36.0), scale), fill=WHITE)
    draw.rectangle(s((36.0, 96.0, 92.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((52.0, 36.0, 55.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((73.0, 36.0, 76.0, 96.0), scale), fill=WHITE)
    for cy in (50.0, 66.0, 82.0):
        hexagon(draw, (64.0, cy), scale, 13.0, 4.0)

# ------------------------------------------------------------------- locks


def draw_deadbolt(draw, scale):
    ell(draw, (42.0, 36.0, 86.0, 80.0), scale)
    draw.rectangle(s((84.0, 54.0, 108.0, 62.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 56.0, 44.0, 64.0), scale), fill=WHITE)
    ell(draw, (56.0, 50.0, 68.0, 62.0), scale, fill=CLEAR)
    draw.rectangle(s((60.0, 60.0, 64.0, 70.0), scale), fill=CLEAR)


def draw_door_handle(draw, scale):
    rr(draw, (44.0, 28.0, 68.0, 100.0), scale, 8.0)
    draw.rectangle(s((56.0, 56.0, 96.0, 64.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 64.0, 96.0, 78.0), scale), fill=WHITE)
    ell(draw, (52.0, 80.0, 60.0, 88.0), scale, fill=CLEAR)


def draw_door_knob(draw, scale):
    ell(draw, (48.0, 52.0, 80.0, 84.0), scale)
    draw.rectangle(s((60.0, 44.0, 68.0, 52.0), scale), fill=WHITE)
    ell(draw, (46.0, 14.0, 82.0, 50.0), scale)
    ell(draw, (58.0, 62.0, 70.0, 74.0), scale, fill=CLEAR)
    draw.rectangle(s((61.0, 72.0, 67.0, 80.0), scale), fill=CLEAR)


def draw_door_chain(draw, scale):
    rr(draw, (24.0, 52.0, 44.0, 76.0), scale, 4.0)
    ell(draw, (30.0, 58.0, 36.0, 64.0), scale, fill=CLEAR)
    ell(draw, (30.0, 66.0, 36.0, 72.0), scale, fill=CLEAR)
    ring(draw, (48.0, 56.0, 62.0, 70.0), scale, 4.0)
    ring(draw, (62.0, 60.0, 76.0, 74.0), scale, 4.0)
    draw.rectangle(s((76.0, 60.0, 104.0, 66.0), scale), fill=WHITE)


def draw_door_viewer(draw, scale):
    ell(draw, (44.0, 44.0, 84.0, 84.0), scale)
    ell(draw, (54.0, 54.0, 74.0, 74.0), scale, fill=CLEAR)
    ell(draw, (56.0, 56.0, 72.0, 72.0), scale)
    ell(draw, (60.0, 60.0, 68.0, 68.0), scale, fill=CLEAR)


def draw_card_reader(draw, scale):
    draw.rectangle(s((86.0, 18.0, 106.0, 56.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 28.0, 106.0, 34.0), scale), fill=CLEAR)
    rr(draw, (44.0, 28.0, 84.0, 100.0), scale, 8.0)
    draw.rectangle(s((52.0, 40.0, 76.0, 46.0), scale), fill=CLEAR)
    ell(draw, (58.0, 54.0, 70.0, 66.0), scale, fill=CLEAR)


def draw_gate_opener(draw, scale):
    draw.rectangle(s((28.0, 56.0, 36.0, 108.0), scale), fill=WHITE)
    rr(draw, (44.0, 60.0, 76.0, 92.0), scale, 8.0)
    bar(draw, (76.0, 70.0), scale, 18.0, 7.0, 0.0)
    bar(draw, (100.0, 62.0), scale, 14.0, 7.0, -30.0)
    ell(draw, (76.0, 66.0, 84.0, 74.0), scale)
    draw.rectangle(s((104.0, 56.0, 112.0, 96.0), scale), fill=WHITE)
    bar(draw, (60.0, 52.0), scale, 10.0, 3.0, 90.0)


def draw_door_hinge(draw, scale):
    draw.rectangle(s((28.0, 40.0, 58.0, 88.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 40.0, 100.0, 88.0), scale), fill=WHITE)
    draw.rectangle(s((58.0, 44.0, 70.0, 84.0), scale), fill=WHITE)
    draw.rectangle(s((58.0, 56.0, 70.0, 60.0), scale), fill=CLEAR)
    draw.rectangle(s((58.0, 72.0, 70.0, 76.0), scale), fill=CLEAR)
    ell(draw, (36.0, 48.0, 42.0, 54.0), scale, fill=CLEAR)
    ell(draw, (36.0, 72.0, 42.0, 78.0), scale, fill=CLEAR)
    ell(draw, (86.0, 48.0, 92.0, 54.0), scale, fill=CLEAR)
    ell(draw, (86.0, 72.0, 92.0, 78.0), scale, fill=CLEAR)


def draw_door_stop(draw, scale):
    draw.rectangle(s((74.0, 36.0, 82.0, 96.0), scale), fill=WHITE)
    draw.polygon(s([(30.0, 96.0), (74.0, 96.0), (74.0, 82.0), (44.0, 82.0)],
                   scale), fill=WHITE)
    ell(draw, (66.0, 82.0, 78.0, 94.0), scale)


def draw_mail_slot(draw, scale):
    rr(draw, (28.0, 44.0, 100.0, 84.0), scale, 8.0)
    draw.rectangle(s((36.0, 58.0, 92.0, 70.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 58.0, 68.0, 70.0), scale), fill=WHITE)
    ell(draw, (34.0, 50.0, 40.0, 56.0), scale, fill=CLEAR)
    ell(draw, (88.0, 50.0, 94.0, 56.0), scale, fill=CLEAR)


# ---------------------------------------------------------------- security


def draw_bullet_camera(draw, scale):
    bar(draw, (57.0, 92.0), scale, 16.0, 5.0, 90.0)
    ell(draw, (45.0, 100.0, 69.0, 110.0), scale)
    draw.rectangle(s((30.0, 52.0, 84.0, 76.0), scale), fill=WHITE)
    draw.rectangle(s((76.0, 44.0, 106.0, 84.0), scale), fill=WHITE)
    ell(draw, (90.0, 54.0, 102.0, 74.0), scale, fill=CLEAR)
    ell(draw, (93.0, 57.0, 99.0, 71.0), scale)


def draw_ptz_camera(draw, scale):
    rr(draw, (48.0, 16.0, 80.0, 28.0), scale, 4.0)
    draw.rectangle(s((60.0, 28.0, 68.0, 46.0), scale), fill=WHITE)
    ell(draw, (44.0, 46.0, 84.0, 86.0), scale)
    ell(draw, (56.0, 60.0, 72.0, 76.0), scale, fill=CLEAR)


def draw_floodlight_cam(draw, scale):
    draw.rectangle(s((60.0, 88.0, 68.0, 104.0), scale), fill=WHITE)
    rr(draw, (48.0, 102.0, 80.0, 110.0), scale, 4.0)
    rr(draw, (52.0, 52.0, 76.0, 80.0), scale, 6.0)
    ell(draw, (58.0, 58.0, 70.0, 70.0), scale, fill=CLEAR)
    draw.polygon(s([(52.0, 52.0), (30.0, 36.0), (36.0, 30.0), (58.0, 46.0)],
                   scale), fill=WHITE)
    draw.polygon(s([(76.0, 52.0), (98.0, 36.0), (92.0, 30.0), (70.0, 46.0)],
                   scale), fill=WHITE)


def draw_trail_camera(draw, scale):
    bar(draw, (82.0, 26.0), scale, 12.0, 4.0, 90.0)
    rr(draw, (40.0, 36.0, 88.0, 96.0), scale, 8.0)
    ell(draw, (50.0, 48.0, 78.0, 76.0), scale)
    ell(draw, (56.0, 54.0, 72.0, 70.0), scale, fill=CLEAR)
    draw.rectangle(s((80.0, 44.0, 88.0, 52.0), scale), fill=CLEAR)
    rr(draw, (48.0, 82.0, 80.0, 92.0), scale, 4.0, fill=CLEAR)


def draw_baby_monitor(draw, scale):
    bar(draw, (78.0, 20.0), scale, 10.0, 3.0, 90.0)
    rr(draw, (44.0, 28.0, 84.0, 100.0), scale, 8.0)
    rr(draw, (52.0, 38.0, 76.0, 64.0), scale, 3.0, fill=CLEAR)
    for x in (56.0, 64.0, 72.0):
        ell(draw, (x - 2.0, 74.0, x + 2.0, 78.0), scale, fill=CLEAR)
    draw.rectangle(s((52.0, 86.0, 60.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((68.0, 86.0, 76.0, 92.0), scale), fill=CLEAR)


def draw_alarm_panel(draw, scale):
    rr(draw, (32.0, 36.0, 96.0, 92.0), scale, 8.0)
    draw.rectangle(s((44.0, 44.0, 84.0, 50.0), scale), fill=CLEAR)
    draw.polygon(s([(64.0, 54.0), (76.0, 60.0), (76.0, 70.0), (64.0, 82.0),
                    (52.0, 70.0), (52.0, 60.0)], scale), fill=CLEAR)
    draw.rectangle(s((48.0, 78.0, 60.0, 86.0), scale), fill=CLEAR)
    draw.rectangle(s((68.0, 78.0, 80.0, 86.0), scale), fill=CLEAR)


def draw_key_fob(draw, scale):
    ell(draw, (78.0, 18.0, 102.0, 42.0), scale)
    ell(draw, (84.0, 24.0, 96.0, 36.0), scale, fill=CLEAR)
    rr(draw, (36.0, 44.0, 84.0, 108.0), scale, 14.0)
    ell(draw, (50.0, 58.0, 62.0, 70.0), scale, fill=CLEAR)
    ell(draw, (50.0, 76.0, 62.0, 88.0), scale, fill=CLEAR)
    ell(draw, (62.0, 92.0, 70.0, 100.0), scale, fill=CLEAR)


def draw_window_alarm(draw, scale):
    rr(draw, (34.0, 30.0, 78.0, 74.0), scale, 4.0)
    draw.rectangle(s((54.0, 30.0, 58.0, 74.0), scale), fill=WHITE)
    draw.rectangle(s((34.0, 50.0, 78.0, 54.0), scale), fill=WHITE)
    rr(draw, (66.0, 60.0, 94.0, 88.0), scale, 6.0)
    bar(draw, (102.0, 64.0), scale, 9.0, 4.0, 90.0)
    bar(draw, (102.0, 78.0), scale, 9.0, 4.0, 90.0)


def draw_siren_strobe(draw, scale):
    ell(draw, (52.0, 28.0, 76.0, 52.0), scale)
    bar(draw, (42.0, 32.0), scale, 9.0, 4.0, 200.0)
    bar(draw, (86.0, 32.0), scale, 9.0, 4.0, 340.0)
    rr(draw, (36.0, 52.0, 92.0, 104.0), scale, 8.0)
    draw.rectangle(s((44.0, 64.0, 84.0, 70.0), scale), fill=CLEAR)
    draw.rectangle(s((44.0, 76.0, 84.0, 82.0), scale), fill=CLEAR)
    ell(draw, (60.0, 88.0, 68.0, 96.0), scale, fill=CLEAR)


def draw_panic_pendant(draw, scale):
    bar(draw, (47.0, 38.0), scale, 29.0, 4.0, 55.0)
    bar(draw, (81.0, 38.0), scale, 29.0, 4.0, 125.0)
    ell(draw, (48.0, 62.0, 80.0, 94.0), scale)
    ell(draw, (58.0, 70.0, 70.0, 82.0), scale, fill=CLEAR)

# ------------------------------------------------------------------ energy


def draw_solar_inverter(draw, scale):
    draw.rectangle(s((48.0, 100.0, 56.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 100.0, 80.0, 110.0), scale), fill=WHITE)
    rr(draw, (36.0, 32.0, 92.0, 100.0), scale, 8.0)
    rr(draw, (46.0, 42.0, 82.0, 62.0), scale, 3.0, fill=CLEAR)
    ell(draw, (86.0, 48.0, 92.0, 54.0), scale, fill=CLEAR)
    for x in (48.0, 58.0, 68.0):
        draw.rectangle(s((x, 70.0, x + 4.0, 92.0), scale), fill=CLEAR)


def draw_breaker_panel(draw, scale):
    rr(draw, (38.0, 14.0, 90.0, 114.0), scale, 6.0)
    draw.rectangle(s((46.0, 22.0, 82.0, 106.0), scale), fill=CLEAR)
    draw.rectangle(s((50.0, 26.0, 78.0, 102.0), scale), fill=WHITE)
    for y in (36.0, 52.0, 68.0, 84.0):
        draw.rectangle(s((54.0, y, 60.0, y + 10.0), scale), fill=CLEAR)
        draw.rectangle(s((68.0, y, 74.0, y + 10.0), scale), fill=CLEAR)


def draw_generator(draw, scale):
    ell(draw, (30.0, 104.0, 46.0, 118.0), scale)
    ell(draw, (82.0, 104.0, 98.0, 118.0), scale)
    draw.rectangle(s((24.0, 44.0, 32.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 44.0, 104.0, 104.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 44.0, 104.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 96.0, 104.0, 104.0), scale), fill=WHITE)
    rr(draw, (40.0, 58.0, 88.0, 90.0), scale, 6.0)
    ell(draw, (58.0, 50.0, 70.0, 58.0), scale)
    draw.rectangle(s((72.0, 66.0, 82.0, 76.0), scale), fill=CLEAR)
    bar(draw, (100.0, 50.0), scale, 14.0, 4.0, 0.0)


def draw_ups(draw, scale):
    rr(draw, (42.0, 24.0, 86.0, 108.0), scale, 8.0)
    rr(draw, (50.0, 34.0, 78.0, 92.0), scale, 4.0, fill=CLEAR)
    draw.rectangle(s((54.0, 38.0, 60.0, 44.0), scale), fill=WHITE)
    draw.rectangle(s((64.0, 38.0, 70.0, 44.0), scale), fill=WHITE)
    for top in (64.0, 72.0, 80.0):
        draw.rectangle(s((54.0, top, 74.0, top + 4.0), scale), fill=WHITE)


def draw_home_battery(draw, scale):
    draw.rectangle(s((32.0, 40.0, 40.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 40.0, 96.0, 52.0), scale), fill=WHITE)
    rr(draw, (40.0, 28.0, 88.0, 100.0), scale, 10.0)
    rr(draw, (50.0, 60.0, 78.0, 80.0), scale, 4.0, fill=CLEAR)
    draw.rectangle(s((50.0, 60.0, 64.0, 80.0), scale), fill=WHITE)
    ell(draw, (60.0, 36.0, 68.0, 44.0), scale, fill=CLEAR)


def draw_electric_car(draw, scale):
    ell(draw, (34.0, 80.0, 54.0, 100.0), scale)
    ell(draw, (74.0, 80.0, 94.0, 100.0), scale)
    ell(draw, (39.0, 85.0, 49.0, 95.0), scale, fill=CLEAR)
    ell(draw, (79.0, 85.0, 89.0, 95.0), scale, fill=CLEAR)
    draw.polygon(s([(16.0, 80.0), (24.0, 62.0), (44.0, 58.0), (56.0, 40.0),
                    (84.0, 40.0), (96.0, 58.0), (112.0, 66.0), (112.0, 84.0)],
                   scale), fill=WHITE)
    ell(draw, (22.0, 66.0, 28.0, 72.0), scale, fill=CLEAR)
    bar(draw, (16.0, 82.0), scale, 12.0, 3.0, 135.0)
    draw.rectangle(s((4.0, 88.0, 12.0, 98.0), scale), fill=WHITE)


def draw_charging_cable(draw, scale):
    draw.rectangle(s((12.0, 50.0, 20.0, 56.0), scale), fill=WHITE)
    draw.rectangle(s((12.0, 62.0, 20.0, 68.0), scale), fill=WHITE)
    rr(draw, (20.0, 44.0, 44.0, 74.0), scale, 6.0)
    ell(draw, (40.0, 54.0, 48.0, 62.0), scale)
    bar(draw, (64.0, 66.0), scale, 20.0, 6.0, 20.0)
    bar(draw, (88.0, 74.0), scale, 18.0, 6.0, -30.0)
    ell(draw, (80.0, 60.0, 88.0, 68.0), scale)
    rr(draw, (96.0, 60.0, 114.0, 86.0), scale, 6.0)


def draw_e_bike(draw, scale):
    ring(draw, (24.0, 72.0, 56.0, 104.0), scale, 6.0)
    ring(draw, (76.0, 66.0, 108.0, 98.0), scale, 6.0)
    ell(draw, (34.0, 82.0, 42.0, 90.0), scale)
    ell(draw, (86.0, 76.0, 94.0, 84.0), scale)
    bar(draw, (64.0, 72.0), scale, 24.0, 5.0, -20.0)
    bar(draw, (52.0, 80.0), scale, 20.0, 5.0, 60.0)
    draw.rectangle(s((48.0, 52.0, 62.0, 58.0), scale), fill=WHITE)
    draw.rectangle(s((53.0, 58.0, 57.0, 70.0), scale), fill=WHITE)
    bar(draw, (84.0, 44.0), scale, 12.0, 4.0, 0.0)
    draw.rectangle(s((80.0, 48.0, 84.0, 64.0), scale), fill=WHITE)
    draw.rectangle(s((56.0, 66.0, 74.0, 78.0), scale), fill=WHITE)


def draw_e_scooter(draw, scale):
    ell(draw, (30.0, 88.0, 50.0, 108.0), scale)
    ell(draw, (82.0, 88.0, 102.0, 108.0), scale)
    ell(draw, (35.0, 93.0, 45.0, 103.0), scale, fill=CLEAR)
    ell(draw, (87.0, 93.0, 97.0, 103.0), scale, fill=CLEAR)
    draw.rectangle(s((40.0, 84.0, 90.0, 92.0), scale), fill=WHITE)
    draw.rectangle(s((52.0, 76.0, 72.0, 84.0), scale), fill=WHITE)
    bar(draw, (86.0, 56.0), scale, 26.0, 6.0, 78.0)
    draw.rectangle(s((70.0, 26.0, 102.0, 32.0), scale), fill=WHITE)
    ell(draw, (80.0, 54.0, 88.0, 62.0), scale)


def draw_pool_pump(draw, scale):
    draw.rectangle(s((28.0, 92.0, 100.0, 102.0), scale), fill=WHITE)
    ell(draw, (28.0, 58.0, 60.0, 90.0), scale)
    draw.rectangle(s((38.0, 34.0, 48.0, 58.0), scale), fill=WHITE)
    draw.rectangle(s((56.0, 62.0, 96.0, 90.0), scale), fill=WHITE)
    ell(draw, (64.0, 54.0, 84.0, 66.0), scale)
    draw.rectangle(s((88.0, 70.0, 112.0, 78.0), scale), fill=WHITE)


def draw_pressure_tank(draw, scale):
    draw.rectangle(s((32.0, 92.0, 40.0, 106.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 92.0, 80.0, 106.0), scale), fill=WHITE)
    rr(draw, (20.0, 56.0, 88.0, 92.0), scale, 18.0)
    draw.rectangle(s((80.0, 44.0, 88.0, 56.0), scale), fill=WHITE)
    ell(draw, (72.0, 28.0, 96.0, 52.0), scale)
    ell(draw, (78.0, 34.0, 90.0, 46.0), scale, fill=CLEAR)
    bar(draw, (84.0, 40.0), scale, 5.0, 2.0, 300.0, fill=CLEAR)
    rr(draw, (52.0, 32.0, 76.0, 52.0), scale, 4.0)


def draw_sump_pump(draw, scale):
    draw.rectangle(s((60.0, 20.0, 68.0, 40.0), scale), fill=WHITE)
    draw.rectangle(s((60.0, 40.0, 68.0, 72.0), scale), fill=WHITE)
    draw.polygon(s([(36.0, 72.0), (92.0, 72.0), (84.0, 108.0), (44.0, 108.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((44.0, 76.0, 84.0, 96.0), scale), fill=CLEAR)
    draw.rectangle(s((44.0, 84.0, 84.0, 96.0), scale), fill=WHITE)
    ell(draw, (72.0, 78.0, 84.0, 90.0), scale)


# -------------------------------------------------------------- appliances


def draw_pet_feeder(draw, scale):
    draw.rectangle(s((42.0, 16.0, 86.0, 24.0), scale), fill=WHITE)
    ell(draw, (60.0, 32.0, 68.0, 40.0), scale, fill=CLEAR)
    draw.polygon(s([(44.0, 24.0), (84.0, 24.0), (78.0, 62.0), (50.0, 62.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((58.0, 62.0, 70.0, 78.0), scale), fill=WHITE)
    ell(draw, (40.0, 78.0, 88.0, 102.0), scale)
    ell(draw, (48.0, 82.0, 80.0, 96.0), scale, fill=CLEAR)
    ell(draw, (54.0, 84.0, 60.0, 90.0), scale)
    ell(draw, (64.0, 87.0, 70.0, 93.0), scale)


def draw_pet_fountain(draw, scale):
    ell(draw, (32.0, 84.0, 96.0, 110.0), scale)
    draw.rectangle(s((60.0, 66.0, 68.0, 84.0), scale), fill=WHITE)
    ell(draw, (48.0, 56.0, 80.0, 72.0), scale)
    bar(draw, (61.0, 46.0), scale, 10.0, 4.0, 90.0)
    bar(draw, (67.0, 46.0), scale, 10.0, 4.0, 90.0)
    ell(draw, (58.0, 30.0, 70.0, 40.0), scale)


def draw_litter_box(draw, scale):
    draw.rectangle(s((28.0, 100.0, 100.0, 108.0), scale), fill=WHITE)
    draw.polygon(s([(32.0, 60.0), (32.0, 100.0), (96.0, 100.0), (96.0, 60.0),
                    (64.0, 36.0)], scale), fill=WHITE)
    draw.rectangle(s((52.0, 72.0, 76.0, 100.0), scale), fill=CLEAR)
    ell(draw, (52.0, 64.0, 76.0, 88.0), scale, fill=CLEAR)


def draw_mower_dock(draw, scale):
    draw.rectangle(s((30.0, 44.0, 38.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((90.0, 44.0, 98.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((24.0, 34.0, 104.0, 44.0), scale), fill=WHITE)
    ell(draw, (60.0, 20.0, 68.0, 30.0), scale)
    draw.rectangle(s((28.0, 100.0, 100.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((52.0, 100.0, 60.0, 104.0), scale), fill=CLEAR)
    draw.rectangle(s((68.0, 100.0, 76.0, 104.0), scale), fill=CLEAR)


def draw_vacuum_dock(draw, scale):
    ell(draw, (60.0, 26.0, 68.0, 34.0), scale, fill=CLEAR)
    rr(draw, (44.0, 20.0, 84.0, 100.0), scale, 10.0)
    rr(draw, (50.0, 58.0, 78.0, 92.0), scale, 6.0, fill=CLEAR)
    ell(draw, (53.0, 70.0, 75.0, 90.0), scale)
    draw.polygon(s([(50.0, 94.0), (78.0, 94.0), (86.0, 108.0), (42.0, 108.0)],
                   scale), fill=WHITE)


def draw_window_robot(draw, scale):
    bar(draw, (98.0, 42.0), scale, 16.0, 3.0, -30.0)
    rr(draw, (38.0, 38.0, 90.0, 90.0), scale, 12.0)
    ell(draw, (48.0, 48.0, 62.0, 62.0), scale, fill=CLEAR)
    ell(draw, (64.0, 64.0, 78.0, 78.0), scale, fill=CLEAR)
    ell(draw, (60.0, 60.0, 68.0, 68.0), scale)


def draw_smoker(draw, scale):
    draw.rectangle(s((48.0, 104.0, 54.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((74.0, 104.0, 80.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((36.0, 64.0, 44.0, 72.0), scale), fill=WHITE)
    draw.rectangle(s((84.0, 64.0, 92.0, 72.0), scale), fill=WHITE)
    ell(draw, (44.0, 28.0, 84.0, 56.0), scale)
    rr(draw, (44.0, 48.0, 84.0, 104.0), scale, 8.0)
    ell(draw, (48.0, 34.0, 54.0, 40.0), scale, fill=CLEAR)
    ell(draw, (60.0, 62.0, 68.0, 70.0), scale, fill=CLEAR)


def draw_pizza_oven(draw, scale):
    draw.rectangle(s((60.0, 20.0, 70.0, 48.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 96.0, 100.0, 108.0), scale), fill=WHITE)
    ell(draw, (32.0, 44.0, 96.0, 100.0), scale)
    draw.rectangle(s((52.0, 72.0, 76.0, 100.0), scale), fill=CLEAR)
    ell(draw, (52.0, 64.0, 76.0, 88.0), scale, fill=CLEAR)
    ell(draw, (60.0, 84.0, 68.0, 92.0), scale)


def draw_outdoor_fridge(draw, scale):
    draw.rectangle(s((48.0, 108.0, 56.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 108.0, 80.0, 114.0), scale), fill=WHITE)
    rr(draw, (40.0, 24.0, 88.0, 108.0), scale, 8.0)
    rr(draw, (48.0, 34.0, 80.0, 92.0), scale, 4.0, fill=CLEAR)
    draw.rectangle(s((48.0, 52.0, 80.0, 56.0), scale), fill=WHITE)
    draw.rectangle(s((48.0, 68.0, 80.0, 72.0), scale), fill=WHITE)
    draw.rectangle(s((54.0, 40.0, 60.0, 50.0), scale), fill=WHITE)
    draw.rectangle(s((64.0, 58.0, 70.0, 66.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 44.0, 94.0, 72.0), scale), fill=WHITE)


def draw_ice_maker(draw, scale):
    draw.rectangle(s((40.0, 22.0, 88.0, 32.0), scale), fill=WHITE)
    draw.rectangle(s((48.0, 104.0, 56.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 104.0, 80.0, 110.0), scale), fill=WHITE)
    rr(draw, (36.0, 32.0, 92.0, 104.0), scale, 8.0)
    rr(draw, (46.0, 52.0, 82.0, 92.0), scale, 4.0, fill=CLEAR)
    draw.rectangle(s((58.0, 56.0, 70.0, 66.0), scale), fill=WHITE)
    draw.rectangle(s((52.0, 72.0, 60.0, 80.0), scale), fill=WHITE)
    draw.rectangle(s((64.0, 72.0, 72.0, 80.0), scale), fill=WHITE)
    draw.rectangle(s((46.0, 86.0, 82.0, 92.0), scale), fill=WHITE)


def draw_wine_cooler(draw, scale):
    draw.rectangle(s((50.0, 112.0, 58.0, 118.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 112.0, 78.0, 118.0), scale), fill=WHITE)
    rr(draw, (42.0, 16.0, 86.0, 112.0), scale, 8.0)
    rr(draw, (50.0, 26.0, 78.0, 96.0), scale, 4.0, fill=CLEAR)
    for top in (36.0, 54.0, 72.0):
        draw.rectangle(s((54.0, top + 8.0, 66.0, top + 16.0), scale),
                       fill=WHITE)
        draw.rectangle(s((57.0, top, 63.0, top + 8.0), scale), fill=WHITE)
    draw.rectangle(s((86.0, 36.0, 92.0, 66.0), scale), fill=WHITE)


def draw_sous_vide(draw, scale):
    draw.polygon(s([(36.0, 64.0), (92.0, 64.0), (84.0, 108.0), (44.0, 108.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((42.0, 68.0, 86.0, 80.0), scale), fill=CLEAR)
    draw.rectangle(s((42.0, 72.0, 86.0, 80.0), scale), fill=WHITE)
    draw.rectangle(s((58.0, 24.0, 74.0, 68.0), scale), fill=WHITE)
    draw.rectangle(s((52.0, 40.0, 82.0, 48.0), scale), fill=WHITE)
    ell(draw, (62.0, 30.0, 70.0, 38.0), scale, fill=CLEAR)


def draw_air_fryer(draw, scale):
    draw.rectangle(s((48.0, 104.0, 56.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 104.0, 80.0, 110.0), scale), fill=WHITE)
    rr(draw, (40.0, 28.0, 88.0, 104.0), scale, 10.0)
    ell(draw, (54.0, 36.0, 60.0, 42.0), scale, fill=CLEAR)
    ell(draw, (66.0, 36.0, 72.0, 42.0), scale, fill=CLEAR)
    draw.rectangle(s((48.0, 58.0, 80.0, 92.0), scale), fill=CLEAR)
    draw.rectangle(s((56.0, 66.0, 72.0, 78.0), scale), fill=WHITE)


def draw_stand_mixer(draw, scale):
    draw.rectangle(s((32.0, 96.0, 84.0, 106.0), scale), fill=WHITE)
    draw.rectangle(s((32.0, 48.0, 46.0, 96.0), scale), fill=WHITE)
    draw.rectangle(s((32.0, 32.0, 92.0, 50.0), scale), fill=WHITE)
    ell(draw, (52.0, 72.0, 84.0, 100.0), scale)
    ell(draw, (58.0, 76.0, 78.0, 94.0), scale, fill=CLEAR)
    bar(draw, (68.0, 66.0), scale, 12.0, 4.0, 90.0)
    ell(draw, (78.0, 36.0, 86.0, 44.0), scale, fill=CLEAR)

# ------------------------------------------------------------------ garden


def draw_drip_irrigation(draw, scale):
    draw.rectangle(s((16.0, 104.0, 112.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((16.0, 80.0, 112.0, 88.0), scale), fill=WHITE)
    for x in (38.0, 62.0, 86.0):
        draw.rectangle(s((x, 88.0, x + 4.0, 104.0), scale), fill=WHITE)
        ell(draw, (x - 4.0, 92.0, x + 4.0, 100.0), scale)


def draw_irrigation_valve(draw, scale):
    draw.rectangle(s((24.0, 78.0, 104.0, 86.0), scale), fill=WHITE)
    rr(draw, (40.0, 60.0, 88.0, 104.0), scale, 10.0)
    rr(draw, (48.0, 68.0, 80.0, 88.0), scale, 4.0, fill=CLEAR)
    draw.rectangle(s((58.0, 30.0, 70.0, 60.0), scale), fill=WHITE)
    draw.rectangle(s((54.0, 24.0, 74.0, 30.0), scale), fill=WHITE)
    bar(draw, (82.0, 44.0), scale, 12.0, 4.0, 30.0)
    bar(draw, (46.0, 44.0), scale, 12.0, 4.0, 150.0)


def draw_rain_barrel(draw, scale):
    draw.rectangle(s((46.0, 104.0, 54.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((74.0, 104.0, 82.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((36.0, 28.0, 92.0, 38.0), scale), fill=WHITE)
    rr(draw, (40.0, 38.0, 88.0, 104.0), scale, 10.0)
    draw.rectangle(s((40.0, 56.0, 88.0, 60.0), scale), fill=CLEAR)
    draw.rectangle(s((40.0, 76.0, 88.0, 80.0), scale), fill=CLEAR)
    draw.rectangle(s((56.0, 88.0, 64.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 50.0, 96.0, 90.0), scale), fill=WHITE)


def draw_compost_bin(draw, scale):
    ell(draw, (56.0, 14.0, 64.0, 22.0), scale)
    ell(draw, (64.0, 8.0, 72.0, 16.0), scale)
    draw.polygon(s([(60.0, 28.0), (52.0, 22.0), (54.0, 32.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((30.0, 38.0, 98.0, 50.0), scale), fill=WHITE)
    draw.rectangle(s((32.0, 50.0, 38.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((90.0, 50.0, 96.0, 100.0), scale), fill=WHITE)
    for top in (56.0, 68.0, 80.0):
        draw.rectangle(s((38.0, top, 90.0, top + 6.0), scale), fill=WHITE)


def draw_gazebo(draw, scale):
    ell(draw, (60.0, 12.0, 68.0, 22.0), scale)
    draw.polygon(s([(24.0, 52.0), (64.0, 22.0), (104.0, 52.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((20.0, 52.0, 108.0, 60.0), scale), fill=WHITE)
    draw.rectangle(s((30.0, 60.0, 38.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((90.0, 60.0, 98.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((38.0, 84.0, 90.0, 90.0), scale), fill=WHITE)
    for x in (48.0, 60.0, 72.0):
        draw.rectangle(s((x, 90.0, x + 4.0, 108.0), scale), fill=WHITE)


def draw_fire_pit(draw, scale):
    for x, y in ((52.0, 44.0), (64.0, 38.0), (76.0, 44.0)):
        ell(draw, (x - 3.0, y - 3.0, x + 3.0, y + 3.0), scale)
    bar(draw, (54.0, 66.0), scale, 20.0, 7.0, 25.0)
    bar(draw, (74.0, 66.0), scale, 20.0, 7.0, 155.0)
    bar(draw, (64.0, 72.0), scale, 22.0, 7.0, 90.0)
    ell(draw, (32.0, 64.0, 96.0, 100.0), scale)
    ell(draw, (40.0, 68.0, 88.0, 92.0), scale, fill=CLEAR)
    ell(draw, (44.0, 100.0, 84.0, 110.0), scale)


def draw_hammock(draw, scale):
    draw.rectangle(s((20.0, 44.0, 28.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((100.0, 44.0, 108.0, 108.0), scale), fill=WHITE)
    bar(draw, (37.0, 57.0), scale, 15.0, 4.0, 38.0)
    bar(draw, (91.0, 57.0), scale, 15.0, 4.0, 142.0)
    draw.polygon(s([(48.0, 66.0), (80.0, 66.0), (74.0, 88.0), (54.0, 88.0)],
                   scale), fill=WHITE)
    draw.rectangle(s((56.0, 62.0, 72.0, 70.0), scale), fill=WHITE)


def draw_porch_swing(draw, scale):
    draw.rectangle(s((28.0, 36.0, 36.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((92.0, 36.0, 100.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((22.0, 28.0, 106.0, 38.0), scale), fill=WHITE)
    draw.rectangle(s((46.0, 38.0, 50.0, 66.0), scale), fill=WHITE)
    draw.rectangle(s((78.0, 38.0, 82.0, 66.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 66.0, 88.0, 78.0), scale), fill=WHITE)
    draw.rectangle(s((40.0, 50.0, 88.0, 62.0), scale), fill=WHITE)


def draw_trampoline(draw, scale):
    draw.rectangle(s((34.0, 92.0, 40.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((61.0, 92.0, 67.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((88.0, 92.0, 94.0, 110.0), scale), fill=WHITE)
    draw.rectangle(s((28.0, 30.0, 34.0, 72.0), scale), fill=WHITE)
    draw.rectangle(s((94.0, 30.0, 100.0, 72.0), scale), fill=WHITE)
    ell(draw, (20.0, 72.0, 108.0, 92.0), scale)
    ell(draw, (28.0, 75.0, 100.0, 89.0), scale, fill=CLEAR)
    ell(draw, (32.0, 76.0, 96.0, 88.0), scale)


def draw_dog_house(draw, scale):
    ell(draw, (16.0, 100.0, 38.0, 112.0), scale)
    draw.rectangle(s((36.0, 66.0, 92.0, 108.0), scale), fill=WHITE)
    draw.polygon(s([(30.0, 68.0), (64.0, 40.0), (98.0, 68.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((54.0, 80.0, 74.0, 108.0), scale), fill=CLEAR)
    ell(draw, (54.0, 72.0, 74.0, 92.0), scale, fill=CLEAR)


def draw_chicken_coop(draw, scale):
    draw.rectangle(s((70.0, 88.0, 76.0, 108.0), scale), fill=WHITE)
    draw.rectangle(s((96.0, 88.0, 102.0, 108.0), scale), fill=WHITE)
    rr(draw, (28.0, 40.0, 64.0, 84.0), scale, 4.0)
    draw.polygon(s([(24.0, 42.0), (46.0, 22.0), (68.0, 42.0)], scale),
                 fill=WHITE)
    draw.rectangle(s((40.0, 56.0, 54.0, 84.0), scale), fill=CLEAR)
    draw.rectangle(s((64.0, 56.0, 108.0, 62.0), scale), fill=WHITE)
    draw.rectangle(s((64.0, 94.0, 108.0, 100.0), scale), fill=WHITE)
    for x in (72.0, 84.0, 96.0):
        draw.rectangle(s((x, 62.0, x + 3.0, 94.0), scale), fill=WHITE)
    draw.polygon(s([(64.0, 100.0), (84.0, 100.0), (64.0, 84.0)], scale),
                 fill=WHITE)


def draw_beehive(draw, scale):
    draw.rectangle(s((44.0, 100.0, 52.0, 112.0), scale), fill=WHITE)
    draw.rectangle(s((76.0, 100.0, 84.0, 112.0), scale), fill=WHITE)
    draw.polygon(s([(34.0, 66.0), (64.0, 42.0), (94.0, 66.0)], scale),
                 fill=WHITE)
    rr(draw, (40.0, 64.0, 88.0, 78.0), scale, 4.0)
    rr(draw, (40.0, 78.0, 88.0, 92.0), scale, 4.0)
    rr(draw, (40.0, 92.0, 88.0, 106.0), scale, 4.0)
    draw.rectangle(s((58.0, 94.0, 70.0, 106.0), scale), fill=CLEAR)
    for x, y in ((30.0, 60.0), (98.0, 70.0), (90.0, 40.0)):
        ell(draw, (x - 3.0, y - 3.0, x + 3.0, y + 3.0), scale)


# ----------------------------------------------------------------- network


def draw_smart_hub(draw, scale):
    ell(draw, (36.0, 92.0, 92.0, 104.0), scale)
    draw.rectangle(s((40.0, 52.0, 88.0, 92.0), scale), fill=WHITE)
    ell(draw, (40.0, 44.0, 88.0, 60.0), scale)
    draw.polygon(s([(54.0, 62.0), (54.0, 78.0), (74.0, 78.0), (74.0, 62.0),
                    (64.0, 54.0)], scale), fill=CLEAR)


def draw_light_bridge(draw, scale):
    rr(draw, (34.0, 52.0, 94.0, 84.0), scale, 8.0)
    ell(draw, (42.0, 60.0, 48.0, 66.0), scale, fill=CLEAR)
    ell(draw, (52.0, 60.0, 58.0, 66.0), scale, fill=CLEAR)
    ell(draw, (62.0, 58.0, 76.0, 72.0), scale, fill=CLEAR)
    draw.polygon(s([(62.0, 65.0), (76.0, 65.0), (69.0, 54.0)], scale),
                 fill=CLEAR)
    draw.rectangle(s((84.0, 60.0, 90.0, 76.0), scale), fill=CLEAR)


def draw_ceiling_ap(draw, scale):
    draw.rectangle(s((56.0, 20.0, 72.0, 30.0), scale), fill=WHITE)
    ell(draw, (44.0, 30.0, 84.0, 62.0), scale)
    draw.rectangle(s((44.0, 46.0, 84.0, 62.0), scale), fill=CLEAR)
    ell(draw, (60.0, 48.0, 68.0, 56.0), scale, fill=CLEAR)
    for x in (52.0, 64.0, 76.0):
        bar(draw, (x, 76.0), scale, 9.0, 4.0, 90.0)


def draw_mesh_node(draw, scale):
    ell(draw, (44.0, 100.0, 84.0, 110.0), scale)
    draw.rectangle(s((48.0, 40.0, 80.0, 100.0), scale), fill=WHITE)
    ell(draw, (48.0, 32.0, 80.0, 48.0), scale)
    bar(draw, (36.0, 56.0), scale, 7.0, 4.0, 0.0)
    bar(draw, (36.0, 70.0), scale, 7.0, 4.0, 0.0)
    bar(draw, (92.0, 56.0), scale, 7.0, 4.0, 0.0)
    bar(draw, (92.0, 70.0), scale, 7.0, 4.0, 0.0)
    ell(draw, (60.0, 60.0, 68.0, 68.0), scale, fill=CLEAR)


def draw_wifi_extender(draw, scale):
    rr(draw, (46.0, 36.0, 82.0, 92.0), scale, 8.0)
    draw.rectangle(s((52.0, 12.0, 58.0, 36.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 12.0, 76.0, 36.0), scale), fill=WHITE)
    ell(draw, (60.0, 50.0, 68.0, 58.0), scale, fill=CLEAR)


def draw_network_switch(draw, scale):
    draw.rectangle(s((14.0, 56.0, 20.0, 76.0), scale), fill=WHITE)
    draw.rectangle(s((108.0, 56.0, 114.0, 76.0), scale), fill=WHITE)
    rr(draw, (20.0, 52.0, 108.0, 80.0), scale, 8.0)
    for y in (58.0, 68.0):
        for x in (30.0, 44.0, 58.0, 72.0):
            draw.rectangle(s((x, y, x + 8.0, y + 6.0), scale), fill=CLEAR)
    ell(draw, (94.0, 60.0, 102.0, 68.0), scale, fill=CLEAR)


def draw_server_rack(draw, scale):
    draw.rectangle(s((48.0, 106.0, 56.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((72.0, 106.0, 80.0, 114.0), scale), fill=WHITE)
    rr(draw, (40.0, 16.0, 88.0, 106.0), scale, 6.0)
    for y in (40.0, 64.0, 88.0):
        draw.rectangle(s((44.0, y, 84.0, y + 4.0), scale), fill=CLEAR)
    for y in (52.0, 76.0, 100.0):
        ell(draw, (48.0, y - 3.0, 54.0, y + 3.0), scale, fill=CLEAR)
        draw.rectangle(s((60.0, y - 2.0, 78.0, y + 2.0), scale), fill=CLEAR)


def draw_nas(draw, scale):
    rr(draw, (34.0, 44.0, 94.0, 96.0), scale, 8.0)
    draw.rectangle(s((42.0, 54.0, 60.0, 88.0), scale), fill=CLEAR)
    draw.rectangle(s((64.0, 54.0, 82.0, 88.0), scale), fill=CLEAR)
    ell(draw, (46.0, 58.0, 52.0, 64.0), scale)
    ell(draw, (68.0, 58.0, 74.0, 64.0), scale)
    ell(draw, (86.0, 48.0, 90.0, 52.0), scale, fill=CLEAR)


def draw_modem(draw, scale):
    draw.rectangle(s((36.0, 92.0, 44.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((84.0, 92.0, 92.0, 100.0), scale), fill=WHITE)
    rr(draw, (28.0, 60.0, 100.0, 92.0), scale, 8.0)
    draw.rectangle(s((34.0, 48.0, 46.0, 60.0), scale), fill=WHITE)
    bar(draw, (90.0, 44.0), scale, 16.0, 4.0, 90.0)
    for x in (56.0, 66.0, 76.0):
        ell(draw, (x - 2.0, 68.0, x + 2.0, 72.0), scale, fill=CLEAR)


def draw_rj45_plug(draw, scale):
    draw.rectangle(s((92.0, 62.0, 112.0, 72.0), scale), fill=WHITE)
    draw.polygon(s([(76.0, 56.0), (92.0, 60.0), (92.0, 74.0), (76.0, 78.0)],
                   scale), fill=WHITE)
    rr(draw, (36.0, 52.0, 76.0, 84.0), scale, 10.0)
    draw.polygon(s([(44.0, 52.0), (68.0, 52.0), (60.0, 40.0)], scale),
                 fill=WHITE)
    for x in (42.0, 46.0, 50.0, 54.0, 58.0, 62.0, 66.0, 70.0):
        draw.rectangle(s((x, 52.0, x + 2.0, 58.0), scale), fill=CLEAR)


# -------------------------------------------------------------------- misc


def draw_voice_puck(draw, scale):
    ell(draw, (36.0, 60.0, 92.0, 100.0), scale)
    ell(draw, (46.0, 52.0, 82.0, 88.0), scale, fill=CLEAR)
    ell(draw, (54.0, 60.0, 74.0, 80.0), scale)
    for x in (56.0, 64.0, 72.0):
        ell(draw, (x - 2.0, 66.0, x + 2.0, 70.0), scale, fill=CLEAR)


def draw_voice_display(draw, scale):
    draw.rectangle(s((58.0, 78.0, 70.0, 92.0), scale), fill=WHITE)
    ell(draw, (44.0, 92.0, 84.0, 104.0), scale)
    rr(draw, (34.0, 32.0, 94.0, 78.0), scale, 6.0)
    rr(draw, (42.0, 40.0, 86.0, 66.0), scale, 3.0, fill=CLEAR)
    ell(draw, (60.0, 34.0, 66.0, 40.0), scale, fill=CLEAR)


def draw_voice_speaker(draw, scale):
    draw.rectangle(s((60.0, 104.0, 66.0, 114.0), scale), fill=WHITE)
    draw.rectangle(s((44.0, 40.0, 84.0, 104.0), scale), fill=WHITE)
    ell(draw, (44.0, 32.0, 84.0, 48.0), scale)
    for y in (58.0, 68.0, 78.0):
        for x in (54.0, 62.0, 70.0):
            ell(draw, (x - 2.0, y - 2.0, x + 2.0, y + 2.0), scale, fill=CLEAR)
    ell(draw, (40.0, 100.0, 88.0, 110.0), scale)


def draw_smart_dial(draw, scale):
    ell(draw, (40.0, 92.0, 88.0, 104.0), scale)
    draw.rectangle(s((42.0, 60.0, 86.0, 92.0), scale), fill=WHITE)
    ell(draw, (42.0, 48.0, 86.0, 72.0), scale)
    draw.rectangle(s((42.0, 66.0, 86.0, 74.0), scale), fill=CLEAR)
    bar(draw, (64.0, 55.0), scale, 8.0, 3.0, 270.0, fill=CLEAR)


def draw_curtain_motor(draw, scale):
    draw.rectangle(s((28.0, 40.0, 34.0, 52.0), scale), fill=WHITE)
    draw.rectangle(s((66.0, 40.0, 72.0, 52.0), scale), fill=WHITE)
    bar(draw, (99.0, 36.0), scale, 8.0, 3.0, 90.0)
    draw.rectangle(s((20.0, 52.0, 88.0, 64.0), scale), fill=WHITE)
    rr(draw, (88.0, 44.0, 110.0, 76.0), scale, 6.0)
    draw.rectangle(s((96.0, 76.0, 100.0, 104.0), scale), fill=WHITE)
    ell(draw, (93.0, 104.0, 103.0, 112.0), scale)


def draw_blind_motor(draw, scale):
    bar(draw, (46.0, 44.0), scale, 8.0, 3.0, 90.0)
    draw.rectangle(s((40.0, 52.0, 88.0, 78.0), scale), fill=WHITE)
    ell(draw, (40.0, 52.0, 52.0, 78.0), scale)
    draw.rectangle(s((88.0, 58.0, 108.0, 70.0), scale), fill=WHITE)
    draw.rectangle(s((104.0, 50.0, 110.0, 96.0), scale), fill=WHITE)
    ell(draw, (52.0, 60.0, 60.0, 68.0), scale, fill=CLEAR)


def draw_window_motor(draw, scale):
    draw.rectangle(s((30.0, 30.0, 42.0, 100.0), scale), fill=WHITE)
    draw.rectangle(s((30.0, 88.0, 100.0, 100.0), scale), fill=WHITE)
    rr(draw, (56.0, 36.0, 92.0, 62.0), scale, 6.0)
    draw.rectangle(s((70.0, 62.0, 76.0, 68.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 72.0, 76.0, 78.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 82.0, 76.0, 88.0), scale), fill=WHITE)


def draw_garage_opener(draw, scale):
    draw.rectangle(s((24.0, 30.0, 30.0, 40.0), scale), fill=WHITE)
    draw.rectangle(s((98.0, 30.0, 104.0, 40.0), scale), fill=WHITE)
    bar(draw, (96.0, 42.0), scale, 8.0, 3.0, 90.0)
    draw.rectangle(s((16.0, 40.0, 112.0, 50.0), scale), fill=WHITE)
    draw.rectangle(s((56.0, 50.0, 72.0, 60.0), scale), fill=WHITE)
    rr(draw, (76.0, 50.0, 104.0, 78.0), scale, 6.0)
    ell(draw, (86.0, 58.0, 94.0, 66.0), scale, fill=CLEAR)
    draw.rectangle(s((62.0, 60.0, 66.0, 84.0), scale), fill=WHITE)
    ell(draw, (58.0, 84.0, 70.0, 94.0), scale)


def draw_french_fridge(draw, scale):
    draw.rectangle(s((46.0, 108.0, 82.0, 114.0), scale), fill=WHITE)
    rr(draw, (38.0, 14.0, 90.0, 108.0), scale, 7.0)
    draw.rectangle(s((62.0, 14.0, 66.0, 90.0), scale), fill=CLEAR)
    rr(draw, (70.0, 40.0, 84.0, 66.0), scale, 3.0, fill=CLEAR)
    draw.rectangle(s((54.0, 30.0, 58.0, 56.0), scale), fill=WHITE)
    draw.rectangle(s((70.0, 30.0, 74.0, 36.0), scale), fill=WHITE)
    draw.rectangle(s((38.0, 90.0, 90.0, 94.0), scale), fill=CLEAR)


def draw_induction_hob(draw, scale):
    rr(draw, (24.0, 48.0, 104.0, 84.0), scale, 8.0)
    draw.ellipse(s((30.0, 54.0, 54.0, 78.0), scale), outline=WHITE, width=4)
    draw.ellipse(s((74.0, 54.0, 98.0, 78.0), scale), outline=WHITE, width=4)
    draw.rectangle(s((24.0, 88.0, 104.0, 98.0), scale), fill=WHITE)
    draw.rectangle(s((44.0, 90.0, 84.0, 94.0), scale), fill=CLEAR)
    draw.rectangle(s((60.0, 88.0, 68.0, 96.0), scale), fill=WHITE)

GLYPHS = {
    "downlight": draw_downlight,
    "globe-lamp": draw_globe_lamp,
    "filament": draw_filament,
    "tube-light": draw_tube_light,
    "panel-light": draw_panel_light,
    "neon": draw_neon,
    "path-light": draw_path_light,
    "stair-light": draw_stair_light,
    "pool-light": draw_pool_light,
    "cabinet-light": draw_cabinet_light,
    "vanity-light": draw_vanity_light,
    "picture-light": draw_picture_light,
    "grow-light": draw_grow_light,
    "emergency-light": draw_emergency_light,
    "rotary-dimmer": draw_rotary_dimmer,
    "touch-panel": draw_touch_panel,
    "scene-switch": draw_scene_switch,
    "blind-switch": draw_blind_switch,
    "round-thermostat": draw_round_thermostat,
    "radiator-valve": draw_radiator_valve,
    "din-relay": draw_din_relay,
    "smart-meter": draw_smart_meter,
    "nfc-tag": draw_nfc_tag,
    "ir-blaster": draw_ir_blaster,
    "dual-relay": draw_dual_relay,
    "fan-switch": draw_fan_switch,
    "temp-sensor": draw_temp_sensor,
    "humidity-sensor": draw_humidity_sensor,
    "pir-sensor": draw_pir_sensor,
    "air-quality": draw_air_quality,
    "co2-monitor": draw_co2_monitor,
    "sound-sensor": draw_sound_sensor,
    "soil-sensor": draw_soil_sensor,
    "rain-gauge": draw_rain_gauge,
    "anemometer": draw_anemometer,
    "weather-station": draw_weather_station,
    "flood-sensor": draw_flood_sensor,
    "gas-sensor": draw_gas_sensor,
    "vibration-sensor": draw_vibration_sensor,
    "radar-sensor": draw_radar_sensor,
    "beam-sensor": draw_beam_sensor,
    "power-clamp": draw_power_clamp,
    "water-meter": draw_water_meter,
    "gas-meter": draw_gas_meter,
    "barometer": draw_barometer,
    "bed-sensor": draw_bed_sensor,
    "split-ac": draw_split_ac,
    "cassette-ac": draw_cassette_ac,
    "portable-ac": draw_portable_ac,
    "wall-convector": draw_wall_convector,
    "towel-dryer": draw_towel_dryer,
    "floor-heating": draw_floor_heating,
    "ventilation-unit": draw_ventilation_unit,
    "air-damper": draw_air_damper,
    "air-filter": draw_air_filter,
    "pellet-stove": draw_pellet_stove,
    "patio-heater": draw_patio_heater,
    "hot-tub": draw_hot_tub,
    "tower-fan": draw_tower_fan,
    "mini-fan": draw_mini_fan,
    "oil-radiator": draw_oil_radiator,
    "radiant-panel": draw_radiant_panel,
    "roller-blind": draw_roller_blind,
    "roman-shade": draw_roman_shade,
    "vertical-blind": draw_vertical_blind,
    "blackout-curtain": draw_blackout_curtain,
    "roof-window": draw_roof_window,
    "barrier-gate": draw_barrier_gate,
    "swing-gate": draw_swing_gate,
    "roller-shutter": draw_roller_shutter,
    "fly-screen": draw_fly_screen,
    "honeycomb-shade": draw_honeycomb_shade,
    "deadbolt": draw_deadbolt,
    "door-handle": draw_door_handle,
    "door-knob": draw_door_knob,
    "door-chain": draw_door_chain,
    "door-viewer": draw_door_viewer,
    "card-reader": draw_card_reader,
    "gate-opener": draw_gate_opener,
    "door-hinge": draw_door_hinge,
    "door-stop": draw_door_stop,
    "mail-slot": draw_mail_slot,
    "bullet-camera": draw_bullet_camera,
    "ptz-camera": draw_ptz_camera,
    "floodlight-cam": draw_floodlight_cam,
    "trail-camera": draw_trail_camera,
    "baby-monitor": draw_baby_monitor,
    "alarm-panel": draw_alarm_panel,
    "key-fob": draw_key_fob,
    "window-alarm": draw_window_alarm,
    "siren-strobe": draw_siren_strobe,
    "panic-pendant": draw_panic_pendant,
    "solar-inverter": draw_solar_inverter,
    "breaker-panel": draw_breaker_panel,
    "generator": draw_generator,
    "ups": draw_ups,
    "home-battery": draw_home_battery,
    "electric-car": draw_electric_car,
    "charging-cable": draw_charging_cable,
    "e-bike": draw_e_bike,
    "e-scooter": draw_e_scooter,
    "pool-pump": draw_pool_pump,
    "pressure-tank": draw_pressure_tank,
    "sump-pump": draw_sump_pump,
    "pet-feeder": draw_pet_feeder,
    "pet-fountain": draw_pet_fountain,
    "litter-box": draw_litter_box,
    "mower-dock": draw_mower_dock,
    "vacuum-dock": draw_vacuum_dock,
    "window-robot": draw_window_robot,
    "smoker": draw_smoker,
    "pizza-oven": draw_pizza_oven,
    "outdoor-fridge": draw_outdoor_fridge,
    "ice-maker": draw_ice_maker,
    "wine-cooler": draw_wine_cooler,
    "sous-vide": draw_sous_vide,
    "air-fryer": draw_air_fryer,
    "stand-mixer": draw_stand_mixer,
    "drip-irrigation": draw_drip_irrigation,
    "irrigation-valve": draw_irrigation_valve,
    "rain-barrel": draw_rain_barrel,
    "compost-bin": draw_compost_bin,
    "gazebo": draw_gazebo,
    "fire-pit": draw_fire_pit,
    "hammock": draw_hammock,
    "porch-swing": draw_porch_swing,
    "trampoline": draw_trampoline,
    "dog-house": draw_dog_house,
    "chicken-coop": draw_chicken_coop,
    "beehive": draw_beehive,
    "smart-hub": draw_smart_hub,
    "light-bridge": draw_light_bridge,
    "ceiling-ap": draw_ceiling_ap,
    "mesh-node": draw_mesh_node,
    "wifi-extender": draw_wifi_extender,
    "network-switch": draw_network_switch,
    "server-rack": draw_server_rack,
    "nas": draw_nas,
    "modem": draw_modem,
    "rj45-plug": draw_rj45_plug,
    "voice-puck": draw_voice_puck,
    "voice-display": draw_voice_display,
    "voice-speaker": draw_voice_speaker,
    "smart-dial": draw_smart_dial,
    "curtain-motor": draw_curtain_motor,
    "blind-motor": draw_blind_motor,
    "window-motor": draw_window_motor,
    "garage-opener": draw_garage_opener,
    "french-fridge": draw_french_fridge,
    "induction-hob": draw_induction_hob,
}

# __ROWS__


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
