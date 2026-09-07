#!/usr/bin/env python3
"""Assemble the web installer from a compiled factory image.

The factory firmware is one binary flashed onto any number of boards by
`installer/index.html` through ESP Web Tools. This script takes the merged
image ESPHome produced, checks that nothing personal ended up inside it, and
lays the site out around it:

    installer/index.html                 the page (in the repository)
    installer/versions.json              which build the page installs
    installer/firmware/<version>/manifest.json
    installer/firmware/<version>/media-controller-factory.factory.bin

The version is in the path on purpose. A binary published at a fixed URL that
quietly changes under it is not something anybody can report a bug against:
"the installer" would mean a different firmware every week. Each build gets
its own directory, and `versions.json` says which one the page currently
offers.

The offsets are not guessed. `firmware.factory.bin` is the merged image
esptool itself produced from the bootloader, the partition table and the
application, so the manifest has exactly one part at offset 0 — see
"Manifest" in the ESP Web Tools documentation.

Usage:

    python tools/make-web-installer.py --build-dir <esphome build dir>

The build directory is the one `esphome compile` used, i.e. the directory
containing `.pioenvs/<name>/firmware.factory.bin`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

REPOSITORY = Path(__file__).resolve().parent.parent
INSTALLER = REPOSITORY / "installer"
FACTORY_YAML = REPOSITORY / "firmware" / "media-controller-factory.yaml"
PAIRED_YAML = REPOSITORY / "firmware" / "media-controller-paired.yaml"

BINARY_NAME = "media-controller-factory.factory.bin"

# ESP Web Tools names the chip family exactly like this.
CHIP_FAMILY = "ESP32-S3"

# A universal image is only universal while none of these is in it. Every one
# is something that would make a copy of this binary personal to somebody:
#
# * an address would tie the image to one installation, which is the whole
#   thing this replaced;
# * the placeholder credentials the continuous-integration wrappers use would
#   mean a validation config had been compiled instead of this one;
# * a bearer token or an ESPHome key would be a credential shipped to
#   everybody who downloads the file.
#
# The check is a substring search over the whole image, which is crude and
# exactly right for the question being asked: none of these strings has any
# business being in a file that is published for anybody to download.
FORBIDDEN_STRINGS = (
    b"homeassistant.local",
    b"ci-validation",
    b"local-validation",
    b"!secret",
    b"wifi_ssid",
    b"media_controller_ha_token",
    b"media_controller_api_encryption_key",
    b"media_controller_ota_password",
)

# A Home Assistant long-lived token is a JWT and always starts like this.
TOKEN_PATTERN = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")


def firmware_version() -> str:
    """Return the version the factory image reports.

    Read out of the paired firmware, which is where `firmware_version` is
    defined; the factory entrypoint inherits it. Reading the file rather than
    taking a command-line argument means the published binary, the manifest
    and what the device tells Home Assistant can never disagree.
    """
    text = PAIRED_YAML.read_text(encoding="utf-8")
    match = re.search(r'^\s*firmware_version:\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"no firmware_version in {PAIRED_YAML}")
    return match.group(1)


def find_image(build_dir: Path) -> Path:
    """Return the merged factory image ESPHome produced."""
    candidates = sorted(build_dir.glob("**/firmware.factory.bin"))
    if not candidates:
        raise SystemExit(
            f"no firmware.factory.bin under {build_dir}; "
            "compile firmware/media-controller-factory.yaml first"
        )
    if len(candidates) > 1:
        raise SystemExit(
            "more than one firmware.factory.bin under "
            f"{build_dir}: {', '.join(str(c) for c in candidates)}"
        )
    return candidates[0]


def check_image(image: bytes) -> list[str]:
    """Return every reason this image must not be published."""
    problems: list[str] = []
    for needle in FORBIDDEN_STRINGS:
        if needle in image:
            problems.append(
                f"the image contains {needle.decode()!r}, which makes it "
                "personal to one installation"
            )
    if TOKEN_PATTERN.search(image):
        problems.append("the image appears to contain a Home Assistant token")
    return problems


def check_configuration() -> list[str]:
    """Return every reason the factory entrypoint is not shippable.

    A source-level check beside the binary one: a credential can be absent
    from the compiled image and still be in the file somebody reads to
    understand what was built.
    """
    problems: list[str] = []
    text = FACTORY_YAML.read_text(encoding="utf-8")
    if not re.search(r'^\s*ha_url:\s*""\s*$', text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must set ha_url to an empty string"
        )
    # A station network makes the image somebody's own network's. The access
    # point's own `ssid:` is two levels down, under `ap:`, and is the name of
    # the recovery network rather than a credential — so the check is written
    # against indentation rather than against the word.
    if re.search(r"^  ssid:", text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must join no Wi-Fi network of its own"
        )
    if re.search(r"^\s*networks:", text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must carry no Wi-Fi networks"
        )
    if re.search(r"^\s*password:", text, re.MULTILINE):
        problems.append(f"{FACTORY_YAML.name} must carry no password")
    if re.search(r"^\s*key:", text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must carry no API encryption key: a key "
            "shared by every copy of one image is not a key"
        )
    if re.search(r"^\s*-\s*platform:\s*esphome\s*$", text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must not enable ESPHome OTA: its password "
            "would be the same on every device flashed from this image"
        )
    return problems


def write_site(version: str, image: Path) -> Path:
    """Write the manifest, the binary and the version index; return the dir."""
    target = INSTALLER / "firmware" / version
    target.mkdir(parents=True, exist_ok=True)

    (target / BINARY_NAME).write_bytes(image.read_bytes())

    manifest = {
        "name": "Media Controller panel",
        "version": version,
        "home_assistant_domain": "media_controller",
        # The panel keeps its Wi-Fi and its pairing across an install, so
        # erasing is offered rather than forced: an update should not send a
        # working panel back to a pairing screen.
        "new_install_prompt_erase": True,
        # Long enough for an ESP32-S3 to bring up the display and the rest of
        # the firmware before the installer offers the Wi-Fi step.
        "new_install_improv_wait_time": 15,
        "builds": [
            {
                "chipFamily": CHIP_FAMILY,
                # One part at offset 0: this is the merged image esptool
                # produced, not the application on its own, so there are no
                # offsets to work out here.
                "parts": [{"path": BINARY_NAME, "offset": 0}],
            }
        ],
    }
    _write_json(target / "manifest.json", manifest)

    _write_json(
        INSTALLER / "versions.json",
        {
            "latest": version,
            "builds": [
                {
                    "version": version,
                    "manifest": f"firmware/{version}/manifest.json",
                }
            ],
        },
    )
    return target


def _write_json(path: Path, payload: dict) -> None:
    path.write_bytes(
        (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-dir",
        required=True,
        type=Path,
        help="the directory esphome compile wrote into",
    )
    arguments = parser.parse_args()

    image_path = find_image(arguments.build_dir)
    image = image_path.read_bytes()

    problems = check_configuration() + check_image(image)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    version = firmware_version()
    target = write_site(version, image_path)
    print(
        f"{image_path} ({len(image):,} bytes) -> "
        f"{target.relative_to(REPOSITORY)} as version {version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
