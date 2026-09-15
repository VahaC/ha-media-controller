#!/bin/sh
# Copy the complete 16 MiB boot partition of the SM-T560 into a file and print
# its SHA256. Every block device is only read. Run on the tablet as root:
#
#   sudo sh tablet-backup-boot.sh [/tmp/mmcblk0p20-backup.img]
#
# Then download the file from the PC through a plain SSH pipe (Dropbear has
# no SFTP) and compare the hash it printed:
#
#   ssh user@tablet "cat /tmp/mmcblk0p20-backup.img" > mmcblk0p20-backup.img
#   sha256sum mmcblk0p20-backup.img
set -eu

out=${1:-/tmp/mmcblk0p20-backup.img}
part=/dev/mmcblk0p20

grep -q 'androidboot.bootloader=T560' /proc/cmdline || { echo "ERROR: this is not an SM-T560"; exit 1; }
test -b "$part" || { echo "ERROR: $part is not a block device"; exit 1; }
test "$(cat /sys/class/block/mmcblk0p20/size)" = 32768 || { echo "ERROR: $part is not 16 MiB"; exit 1; }
test ! -e "$out" || { echo "ERROR: $out already exists"; exit 1; }
free_kb=$(df -Pk "$(dirname "$out")" | awk 'NR == 2 { print $4 }')
test "$free_kb" -ge 17000 || { echo "ERROR: only $free_kb KiB free next to $out, need 16 MiB"; exit 1; }

umask 077
dd if="$part" of="$out" bs=1M
size=$(wc -c < "$out")
test "$size" -eq 16777216 || { echo "ERROR: the backup is $size bytes, expected 16777216"; exit 1; }
if [ -n "${SUDO_USER:-}" ]; then
    chown "$SUDO_USER" "$out"
fi

echo "BACKUP=$out"
echo "BACKUP_SHA256=$(sha256sum "$out" | cut -d' ' -f1)"
echo "PARTITION_SHA256=$(sha256sum "$part" | cut -d' ' -f1)"
echo "BACKUP_OK_NO_BLOCK_DEVICE_WAS_WRITTEN"
