#!/usr/bin/env python3
"""Assemble the web installer from a compiled factory image.

The factory firmware is one binary flashed onto any number of boards by
`installer/index.html` through ESP Web Tools. This script takes the merged
image ESPHome produced, checks that nothing personal ended up inside it, and
lays the site out around it:

    installer/index.html                 the page (in the repository)
    installer/versions.json              which build the page installs,
                                         and which build a paired panel can
                                         install over the air
    installer/firmware/<version>/manifest.json
    installer/firmware/<version>/media-controller-factory.factory.bin
    installer/firmware/<version>/media-controller-paired.ota.bin

**Two binaries, and they are not interchangeable.** The factory image is the
merged one: bootloader, partition table and application, written from offset
zero over USB. The OTA image is the application alone, which is the only
thing an over-the-air update may write — it lands in the inactive application
slot and leaves the bootloader, the partition table and NVS exactly where
they are, which is why Wi-Fi credentials, the pairing token and the room
layout survive an update. Flashing the merged image over the air would
overwrite the partition table with itself from the wrong offset and brick
the device; publishing only the merged image, which is what this script used
to do, meant there was nothing an update could legally install at all.

`versions.json` therefore carries a digest of the OTA image and the contract
version the build speaks. Home Assistant downloads that file, checks its
SHA-256 before it offers anything to a panel, and refuses a build whose
contract it does not understand. See
`custom_components/media_controller/firmware_release.py`.

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
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

REPOSITORY = Path(__file__).resolve().parent.parent
INSTALLER = REPOSITORY / "installer"
FACTORY_YAML = REPOSITORY / "firmware" / "media-controller-factory.yaml"
PAIRED_YAML = REPOSITORY / "firmware" / "media-controller-paired.yaml"

BINARY_NAME = "media-controller-factory.factory.bin"
# The application on its own, for an over-the-air update. ESPHome writes it
# beside the merged image as `firmware.ota.bin`; it is a plain copy of the
# app partition image.
OTA_BINARY_NAME = "media-controller-paired.ota.bin"

# ESP Web Tools names the chip family exactly like this.
CHIP_FAMILY = "ESP32-S3"

# ---------------------------------------------------------------------------
# The partition table every panel in the field already has.
#
# This is checked rather than assumed, and it is checked here because getting
# it wrong cannot be fixed afterwards by any amount of code. An over-the-air
# update writes the inactive application slot and nothing else, so:
#
#   * there have to *be* two application slots. A build whose table had one
#     could never be updated over the air again, by anything;
#   * each has to be large enough for the image being published;
#   * and none of them may move. NVS holds the Wi-Fi credentials, the pairing
#     token, the room layout and the update bookkeeping. An update that
#     shifted its offset would leave every one of those unreadable on a
#     device that had no way back except a screwdriver and a cable.
#
# The values are read out of the image published as 0.5.0, which is what the
# earliest panels that can be updated this way are running. ESPHome derives
# them from the flash size and the components in the configuration, so a
# change that added a custom partition, or moved to a different flash size,
# would silently produce a different table — and this is where that stops.
PARTITION_TABLE_OFFSET = 0x8000
PARTITION_TABLE_SIZE = 0x1000
PARTITION_ENTRY_SIZE = 32
PARTITION_ENTRY_MAGIC = 0x50AA
PARTITION_TYPE_APP = 0
PARTITION_TYPE_DATA = 1

# name, type, subtype, offset, size
EXPECTED_PARTITIONS = (
    ("otadata", PARTITION_TYPE_DATA, 0x00, 0x009000, 0x002000),
    ("phy_init", PARTITION_TYPE_DATA, 0x01, 0x00B000, 0x001000),
    ("app0", PARTITION_TYPE_APP, 0x10, 0x010000, 0x7C0000),
    ("app1", PARTITION_TYPE_APP, 0x11, 0x7D0000, 0x7C0000),
    ("nvs", PARTITION_TYPE_DATA, 0x02, 0xF90000, 0x070000),
)

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


def contract_version() -> int:
    """Return the client-contract revision the factory image speaks.

    Read out of the paired firmware beside `firmware_version`, for the same
    reason: the published index, the binary and what the device tells Home
    Assistant can then never disagree. Home Assistant refuses to offer a
    build whose contract it does not understand, so a wrong number here is a
    panel that is either never offered an update or offered one it cannot
    fully read.
    """
    text = PAIRED_YAML.read_text(encoding="utf-8")
    match = re.search(r'^\s*contract_version:\s*"(\d+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"no contract_version in {PAIRED_YAML}")
    return int(match.group(1))


def read_partition_table(image: bytes) -> list[tuple[str, int, int, int, int]]:
    """Return the partition table inside a merged image.

    The table is at a fixed offset in every ESP-IDF image and each entry is
    32 bytes beginning with a two-byte magic. Reading stops at the first
    entry that does not carry it, which is how the table ends.
    """
    table: list[tuple[str, int, int, int, int]] = []
    for start in range(
        PARTITION_TABLE_OFFSET,
        PARTITION_TABLE_OFFSET + PARTITION_TABLE_SIZE,
        PARTITION_ENTRY_SIZE,
    ):
        entry = image[start : start + PARTITION_ENTRY_SIZE]
        if len(entry) < PARTITION_ENTRY_SIZE:
            break
        (magic,) = struct.unpack("<H", entry[0:2])
        if magic != PARTITION_ENTRY_MAGIC:
            break
        kind, subtype = entry[2], entry[3]
        offset, size = struct.unpack("<II", entry[4:12])
        name = entry[12:28].split(b"\x00")[0].decode("ascii", "replace")
        table.append((name, kind, subtype, offset, size))
    return table


def check_partitions(image: bytes, ota_size: int) -> list[str]:
    """Return every reason this image would break over-the-air updates."""
    problems: list[str] = []
    table = read_partition_table(image)
    if not table:
        return ["no partition table was found in the merged image"]
    if table != list(EXPECTED_PARTITIONS):
        problems.append(
            "the partition table has changed, which would strand every "
            "panel already in the field: an update writes the application "
            "slot only, so a table that moves NVS destroys the Wi-Fi "
            "credentials, the pairing and the room layout of every device "
            "that installs it.\n"
            f"  published: {_describe(EXPECTED_PARTITIONS)}\n"
            f"  built:     {_describe(table)}"
        )
        return problems

    slot = next(size for name, _t, _s, _o, size in table if name == "app0")
    if ota_size > slot:
        problems.append(
            f"the application image is {ota_size:,} bytes and the "
            f"application slot is {slot:,}"
        )
    return problems


def _describe(table) -> str:
    """Return a partition table in one readable line."""
    return ", ".join(
        f"{name}@0x{offset:X}+0x{size:X}" for name, _t, _s, offset, size in table
    )


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


def find_ota_image(build_dir: Path) -> Path:
    """Return the application-only image, for over-the-air updates."""
    candidates = sorted(build_dir.glob("**/firmware.ota.bin"))
    if not candidates:
        raise SystemExit(
            f"no firmware.ota.bin under {build_dir}; compile "
            "firmware/media-controller-factory.yaml first"
        )
    if len(candidates) > 1:
        raise SystemExit(
            "more than one firmware.ota.bin under "
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
    # Contract version 9. `api:` is what defines USE_API, USE_API is what
    # publishes the `_esphomelib._tcp` mDNS record, and that record is what
    # makes a panel appear in the ESPHome integration. A shipped image that
    # had one back would work perfectly and quietly undo the whole version.
    if re.search(r"^api:", text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must not declare the ESPHome native API: a "
            "panel flashed from this image must not appear in the ESPHome "
            "integration"
        )
    if re.search(r"^\s*-\s*platform:\s*esphome\s*$", text, re.MULTILINE):
        problems.append(
            f"{FACTORY_YAML.name} must not enable ESPHome OTA: its password "
            "would be the same on every device flashed from this image"
        )
    return problems


def write_site(version: str, image: Path, ota_image: Path) -> Path:
    """Write the manifests, both binaries and the index; return the dir."""
    target = INSTALLER / "firmware" / version
    target.mkdir(parents=True, exist_ok=True)

    (target / BINARY_NAME).write_bytes(image.read_bytes())
    ota_payload = ota_image.read_bytes()
    (target / OTA_BINARY_NAME).write_bytes(ota_payload)

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

    # One build, because a deploy replaces the whole site: an index that
    # listed last month's version would name a binary that is no longer
    # there. What is added here is everything an update needs to be decided
    # without downloading anything first — which revision of the client
    # contract this build speaks, how large the application image is, and
    # what it hashes to.
    #
    # `release_url` is deliberately absent rather than guessed. Releases here
    # are written by hand and their tags do not always match the firmware
    # version, and a link that 404s is worse than the documentation link Home
    # Assistant falls back to. Add one to this file by hand when a release
    # has notes worth reading.
    _write_json(
        INSTALLER / "versions.json",
        {
            "latest": version,
            "builds": [
                {
                    "version": version,
                    "contract_version": contract_version(),
                    "manifest": f"firmware/{version}/manifest.json",
                    "ota": {
                        "path": f"firmware/{version}/{OTA_BINARY_NAME}",
                        "size": len(ota_payload),
                        "sha256": hashlib.sha256(ota_payload).hexdigest(),
                        "md5": hashlib.md5(
                            ota_payload, usedforsecurity=False
                        ).hexdigest(),
                    },
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
    ota_path = find_ota_image(arguments.build_dir)
    ota_size = ota_path.stat().st_size

    problems = (
        check_configuration()
        + check_image(image)
        + check_partitions(image, ota_size)
    )
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    version = firmware_version()
    target = write_site(version, image_path, ota_path)
    print(
        f"{image_path} ({len(image):,} bytes) -> "
        f"{target.relative_to(REPOSITORY)} as version {version}"
    )
    print(
        f"{ota_path} ({ota_size:,} bytes) -> "
        f"{target.relative_to(REPOSITORY)} for over-the-air updates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
