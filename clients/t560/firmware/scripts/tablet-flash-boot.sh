#!/bin/sh
# Write one boot image to the boot partition of the SM-T560 and to nothing
# else. Run on the tablet as root, from a terminal, because it asks for a
# typed confirmation right before the write:
#
#   sudo sh tablet-flash-boot.sh /tmp/boot.img <sha256 of boot.img> [<sha256 the partition must have now>]
#
# What it does, in order:
#   1. refuses to run on anything but an SM-T560, or when /dev/mmcblk0p20 is
#      not exactly 16 MiB;
#   2. checks the size and SHA256 of the image file;
#   3. computes the hash the partition will have afterwards (the image padded
#      with zeros to 16 MiB) and prints the hash it has now;
#   4. waits for the confirmation token;
#   5. writes the padded image in one pass and re-reads the whole partition;
#   6. compares the hash and never reboots by itself.
#
# The same script restores a full 16 MiB backup: pass the backup file and its
# hash, the padding is then zero bytes long.
set -eu

image=${1:?usage: tablet-flash-boot.sh IMAGE SHA256 [CURRENT_P20_SHA256]}
expected=${2:?usage: tablet-flash-boot.sh IMAGE SHA256 [CURRENT_P20_SHA256]}
required_current=${3:-}
target=/dev/mmcblk0p20
size_p20=16777216
token=FLASH-SM-T560-P20

grep -q 'androidboot.bootloader=T560' /proc/cmdline || { echo "ERROR: this is not an SM-T560"; exit 1; }
grep -q 'connie=SM-T560' /proc/cmdline || { echo "ERROR: this is not an SM-T560"; exit 1; }
test -b "$target" || { echo "ERROR: $target is not a block device"; exit 1; }
test "$(cat /sys/class/block/mmcblk0p20/size)" = 32768 || { echo "ERROR: $target is not 16 MiB"; exit 1; }
test -f "$image" || { echo "ERROR: $image is not a file"; exit 1; }
size=$(wc -c < "$image")
if [ "$size" -le 0 ] || [ "$size" -gt "$size_p20" ]; then
    echo "ERROR: $image is $size bytes, it does not fit the 16 MiB partition"
    exit 1
fi
echo "$expected  $image" | sha256sum -c - || { echo "ERROR: $image does not have the expected SHA256"; exit 1; }
pad=$((size_p20 - size))
padded=$({ cat "$image"; head -c "$pad" /dev/zero; } | sha256sum | cut -d' ' -f1)
current=$(sha256sum "$target" | cut -d' ' -f1)

echo "IMAGE=$image ($size bytes, zero padding $pad bytes)"
echo "CURRENT_P20_SHA256=$current"
echo "EXPECTED_P20_SHA256_AFTER_WRITE=$padded"
if [ -n "$required_current" ] && [ "$current" != "$required_current" ]; then
    echo "ERROR: the partition does not have the hash you said it must have now; nothing was written"
    exit 1
fi
if [ "$current" = "$padded" ]; then
    echo "NOTHING_TO_DO: the partition already holds exactly this image"
    exit 0
fi

printf 'Type %s exactly to write ONLY %s: ' "$token" "$target"
read -r answer
test "$answer" = "$token" || { echo "cancelled, nothing was written"; exit 1; }

echo "WRITING_ONLY_$target"
{ cat "$image"; head -c "$pad" /dev/zero; } | dd of="$target" bs=1M conv=fsync 2> /dev/null
sync
final=$(sha256sum "$target" | cut -d' ' -f1)
echo "COMPLETE_P20_SHA256=$final"
if [ "$final" != "$padded" ]; then
    echo "ERROR: the partition hash does not match. DO NOT REBOOT. Write your backup with this script now."
    exit 1
fi
echo "FLASH_VERIFIED_NO_REBOOT_PERFORMED"
