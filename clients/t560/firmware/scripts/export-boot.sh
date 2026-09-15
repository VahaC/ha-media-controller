#!/bin/sh
# Install the freshly built kernel package into the pmbootstrap rootfs chroot,
# export boot.img, check that it really carries the expected kernel build tag
# and the camera driver, and print the numbers the flash step needs.
# Local only: the tablet is never touched.
#
# Usage: export-boot.sh [output.img]
# Default output: ../boot/boot-sm-t560-camera.img (refuses to overwrite).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
pkg="$here/../pmaports/linux-samsung-gtelwifi"
out=${1:-$here/../boot/boot-sm-t560-camera.img}
pmb=${PMBOOTSTRAP:-pmbootstrap}
command -v "$pmb" > /dev/null 2>&1 || pmb="$HOME/.local/bin/pmbootstrap"
p20=16777216

pkgver=$(sed -n 's/^pkgver=\(.*\)$/\1/p' "$pkg/APKBUILD")
pkgrel=$(sed -n 's/^pkgrel=\([0-9]*\)$/\1/p' "$pkg/APKBUILD")
package="linux-samsung-gtelwifi=$pkgver-r$pkgrel"
tag="#$((pkgrel + 1))-postmarketOS"

test ! -e "$out" || { echo "ERROR: $out already exists, refusing to overwrite"; exit 1; }

echo "installing $package into the rootfs chroot"
"$pmb" chroot -r --output=interactive -- apk add --upgrade "$package"
"$pmb" chroot -r --output=interactive -- apk info -e "$package"

export_dir=$(mktemp -d /tmp/t560-boot-export.XXXXXX)
trap 'rm -rf "$export_dir"' EXIT
"$pmb" export "$export_dir"
test -s "$export_dir/boot.img"
test -s "$export_dir/vmlinuz"

echo "checking the kernel build tag ($tag) and the camera driver in vmlinuz"
python3 - "$export_dir/vmlinuz" "$tag" <<'PY'
import re
import sys
import zlib

path, tag = sys.argv[1], sys.argv[2].encode()
data = open(path, "rb").read()
blobs = [data]
for match in re.finditer(b"\x1f\x8b\x08", data):
    try:
        blobs.append(zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data[match.start():]))
    except zlib.error:
        continue
banner = None
for blob in blobs:
    hit = re.search(rb"Linux version 3\.10\.17[^\n\x00]*", blob)
    if hit and tag in hit.group(0):
        banner = hit.group(0).decode("ascii", "replace")
        break
if banner is None:
    sys.exit("ERROR: kernel build tag %s not found in vmlinuz (stale package?)" % tag.decode())
print("KERNEL_BANNER=" + banner)
markers = [
    b"gtelwifi_camera_csi_phy_id",
    b"gtelwifi_camera_yuv_pattern",
    b"gtelwifi_camera_disable",
    b"camera-r18: DCAM capture YUV pattern",
]
missing = [m.decode() for m in markers if not any(m in b for b in blobs)]
if missing:
    sys.exit("ERROR: camera driver markers missing from vmlinuz: " + ", ".join(missing))
print("CAMERA_DRIVER_MARKERS_PRESENT")
PY

mkdir -p "$(dirname "$out")"
cp -L "$export_dir/boot.img" "$out"
size=$(stat -c %s "$out")
if [ "$size" -le 0 ] || [ "$size" -gt "$p20" ]; then
    echo "ERROR: $size bytes does not fit the 16 MiB boot partition"
    exit 1
fi

echo "PACKAGE=$package"
echo "BOOT_IMAGE=$out"
echo "BOOT_IMAGE_SIZE=$size"
echo "BOOT_IMAGE_SHA256=$(sha256sum "$out" | cut -d' ' -f1)"
echo "EXPECTED_P20_SHA256_AFTER_FLASH=$({ cat "$out"; head -c $((p20 - size)) /dev/zero; } | sha256sum | cut -d' ' -f1)"
