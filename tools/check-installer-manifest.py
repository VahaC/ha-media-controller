#!/usr/bin/env python3
"""Check that the published installer site is internally complete.

ESP Web Tools fails at flash time when a manifest names a file that is not
there, and the failure a person sees is a download error in a dialog rather
than anything that says which file. The whole site is small enough to check
outright, so it is checked here instead: every manifest the index offers,
every part every manifest names, and the shape of both documents.

Run after tools/make-web-installer.py, and before anything is deployed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parent.parent
INSTALLER = REPOSITORY / "installer"

# The chip families ESP Web Tools understands. A typo here is otherwise a
# device that is offered and then refused with "not supported".
CHIP_FAMILIES = {
    "ESP32",
    "ESP32-C2",
    "ESP32-C3",
    "ESP32-C5",
    "ESP32-C6",
    "ESP32-H2",
    "ESP32-P4",
    "ESP32-S2",
    "ESP32-S3",
    "ESP8266",
}


def _load(path: Path, problems: list[str]) -> dict | None:
    """Return a JSON document, recording why it could not be read."""
    if not path.is_file():
        problems.append(f"{path.relative_to(REPOSITORY)} is missing")
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        problems.append(f"{path.relative_to(REPOSITORY)} is not JSON: {error}")
        return None
    if not isinstance(document, dict):
        problems.append(
            f"{path.relative_to(REPOSITORY)} is not a JSON object"
        )
        return None
    return document


def check_manifest(path: Path, problems: list[str]) -> None:
    """Check one ESP Web Tools manifest and the binaries it names."""
    document = _load(path, problems)
    if document is None:
        return
    where = path.relative_to(REPOSITORY)

    for field in ("name", "version", "builds"):
        if not document.get(field):
            problems.append(f"{where} has no {field}")

    builds = document.get("builds")
    if not isinstance(builds, list) or not builds:
        problems.append(f"{where} lists no builds")
        return

    for index, build in enumerate(builds):
        family = build.get("chipFamily")
        if family not in CHIP_FAMILIES:
            problems.append(f"{where} build {index} names chip {family!r}")
        parts = build.get("parts")
        if not isinstance(parts, list) or not parts:
            problems.append(f"{where} build {index} names no parts")
            continue
        for part in parts:
            name = part.get("path")
            if not name:
                problems.append(f"{where} build {index} has a part with no path")
                continue
            if not isinstance(part.get("offset"), int):
                problems.append(f"{where} names {name} with no integer offset")
            if str(name).startswith(("http://", "https://")):
                # An absolute URL is allowed by the format and deliberately
                # not used here: the site has to be self-contained, so that a
                # release cannot be broken by something outside it.
                problems.append(f"{where} names {name} outside the site")
                continue
            binary = path.parent / str(name)
            if not binary.is_file():
                problems.append(f"{where} names {name}, which was not built")
            elif binary.stat().st_size == 0:
                problems.append(f"{where} names {name}, which is empty")


def check_ota(build: dict, problems: list[str]) -> None:
    """Check the over-the-air half of one entry in the version index.

    This is the half Home Assistant reads, and it fails differently from a
    missing flash binary: nothing goes wrong at release time, and a panel on
    a wall is simply never offered an update, or is offered one whose digest
    will not match. Both are found here instead.
    """
    version = build.get("version")
    where = f"installer/versions.json build {version!r}"

    contract = build.get("contract_version")
    if not isinstance(contract, int) or isinstance(contract, bool) or contract < 1:
        problems.append(f"{where} names no usable contract_version")

    ota = build.get("ota")
    if not isinstance(ota, dict):
        problems.append(
            f"{where} carries no ota block, so no panel can be updated to it"
        )
        return

    path = ota.get("path")
    if not path or str(path).startswith(("http://", "https://")):
        problems.append(f"{where} names no over-the-air image inside the site")
        return

    binary = INSTALLER / str(path)
    if not binary.is_file():
        problems.append(f"{where} names {path}, which was not built")
        return

    payload = binary.read_bytes()
    if ota.get("size") != len(payload):
        problems.append(
            f"{where} says {ota.get('size')} bytes and {path} is {len(payload)}"
        )
    for algorithm in ("sha256", "md5"):
        expected = ota.get(algorithm)
        actual = hashlib.new(
            algorithm, payload, usedforsecurity=False
        ).hexdigest()
        if expected != actual:
            problems.append(
                f"{where} names a {algorithm} of {expected!r} and {path} "
                f"hashes to {actual!r}"
            )


def main() -> int:
    problems: list[str] = []

    if not (INSTALLER / "index.html").is_file():
        problems.append("installer/index.html is missing")

    versions = _load(INSTALLER / "versions.json", problems)
    if versions is not None:
        builds = versions.get("builds")
        if not isinstance(builds, list) or not builds:
            problems.append("installer/versions.json offers no build")
        else:
            for build in builds:
                relative = build.get("manifest")
                if not relative:
                    problems.append(
                        "installer/versions.json has a build with no manifest"
                    )
                    continue
                check_manifest(INSTALLER / str(relative), problems)
                check_ota(build, problems)
        if versions.get("latest") not in {
            build.get("version") for build in (builds or []) if isinstance(build, dict)
        }:
            problems.append(
                "installer/versions.json names a latest version it does not offer"
            )

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("the installer site is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
