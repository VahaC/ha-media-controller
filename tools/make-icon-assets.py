#!/usr/bin/env python3
"""Build the card-icon assets the integration serves.

The integration ships two files per catalog icon and generates neither at
runtime:

* `icons/<id>.png` — the source artwork, served to the layout editor a panel
  hosts on the device itself, so that a person choosing an icon sees it;
* `icons/esp32/<id>-40.bin` — the same picture pre-rendered to the exact size
  an ESP32 card draws, in the exact bytes LVGL blits.

The second one is why this script exists. The ESP32 cannot scale an image at
draw time — the firmware sets `LV_COLOR_16_SWAP` and leaves
`LV_DRAW_SW_SUPPORT_SWAPPED` off, so LVGL's software renderer cannot transform
a source at all — and it has no PNG decoder to spare either. Rendering here,
once, means the device downloads a buffer it can point `lv_image_dsc_t`
straight at.

The layout is ARGB8888 in memory order B, G, R, A, which is what ESPHome's
`image` component already produces for `type: RGB` with
`transparency: alpha_channel`, behind an eight-byte header naming the size so
that a truncated or mis-routed download cannot be mistaken for a good one.

Run it from the repository root after adding a row to `ICONS` in
`custom_components/media_controller/icon_catalog.py`:

    python tools/make-icon-assets.py

Sources are looked for in `clients/t560/data/icons/` first — the artwork the
tablet already carries — and then beside the script's output, so an icon added
later needs only its own PNG dropped into `custom_components/media_controller/
icons/`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image

REPOSITORY = Path(__file__).resolve().parents[1]
INTEGRATION = REPOSITORY / "custom_components" / "media_controller"

sys.path.insert(0, str(INTEGRATION))

import icon_catalog  # noqa: E402  (needs the path above)

# Where a source picture may come from, in order. The tablet's own icon
# directory is first because it is where the artwork already lived.
SOURCE_DIRECTORIES = (
    REPOSITORY / "clients" / "t560" / "data" / "icons",
    INTEGRATION / icon_catalog.ASSET_DIRECTORY,
)


def find_source(icon: icon_catalog.CatalogIcon) -> Path | None:
    """Return the artwork to render one catalog row from."""
    for directory in SOURCE_DIRECTORIES:
        candidate = directory / icon.png_name
        if candidate.is_file():
            return candidate
    return None


def render_esp32(source: Path, size: int) -> bytes:
    """Return one pre-rendered variant: header, then ARGB8888 pixels."""
    with Image.open(source) as image:
        # Convert before resizing: a palette image resized in place resamples
        # palette indices and produces mud.
        rgba = image.convert("RGBA").resize((size, size), Image.LANCZOS)
        pixels = rgba.tobytes()  # R, G, B, A

    # LVGL's ARGB8888 is little-endian, so a pixel sits in memory as
    # B, G, R, A. That is also the order ESPHome writes for the artwork
    # compiled into the firmware, which is what makes a downloaded icon and a
    # built-in one interchangeable.
    swapped = bytearray(len(pixels))
    swapped[0::4] = pixels[2::4]
    swapped[1::4] = pixels[1::4]
    swapped[2::4] = pixels[0::4]
    swapped[3::4] = pixels[3::4]

    payload = icon_catalog.esp32_header(size) + bytes(swapped)
    expected = icon_catalog.esp32_variant_bytes(size)
    if len(payload) != expected:
        raise AssertionError(
            f"{source.name} rendered to {len(payload)} bytes, not {expected}"
        )
    return payload


def write_if_changed(path: Path, payload: bytes) -> bool:
    """Write a file only when its content actually differs."""
    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return True


def main() -> int:
    """Render every catalog icon, reporting what changed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when an asset is missing or stale",
    )
    arguments = parser.parse_args()

    asset_root = INTEGRATION / icon_catalog.ASSET_DIRECTORY
    esp32_root = asset_root / icon_catalog.ESP32_ASSET_DIRECTORY
    written = 0
    stale = 0
    missing: list[str] = []

    for icon in icon_catalog.ICONS:
        source = find_source(icon)
        if source is None:
            missing.append(icon.icon_id)
            continue

        # The source is copied rather than re-encoded: it is what the editor
        # shows, and re-encoding it every run would churn the repository.
        copy = asset_root / icon.png_name
        if source != copy:
            if arguments.check:
                if not copy.is_file() or copy.read_bytes() != source.read_bytes():
                    stale += 1
                    print(f"stale: {copy.relative_to(REPOSITORY)}")
            elif write_if_changed(copy, source.read_bytes()):
                written += 1
                print(f"wrote {copy.relative_to(REPOSITORY)}")

        for size in icon_catalog.SUPPORTED_SIZES:
            target = esp32_root / icon.esp32_name(size)
            payload = render_esp32(source, size)
            if arguments.check:
                if not target.is_file() or target.read_bytes() != payload:
                    stale += 1
                    print(f"stale: {target.relative_to(REPOSITORY)}")
            elif write_if_changed(target, payload):
                written += 1
                print(f"wrote {target.relative_to(REPOSITORY)}")

    if missing:
        print(
            "No source artwork for: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    if arguments.check:
        print(f"{stale} asset(s) out of date")
        return 1 if stale else 0
    print(f"{written} file(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
