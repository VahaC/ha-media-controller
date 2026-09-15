#!/bin/sh
# Restore the 16 MiB boot partition of the SM-T560 from TWRP over ADB. This is
# the rescue path for a kernel that does not boot far enough for SSH.
# Run on the PC with the tablet in TWRP and USB debugging authorised:
#
#   sh twrp-restore-boot.sh mmcblk0p20-backup.img <sha256 of the backup>
#
# It writes ONLY /dev/block/mmcblk0p20, asks for a typed confirmation before
# the write, re-reads the whole partition afterwards and never reboots.
# TWRP may call the tablet SM-T561 or omni_t561; the check below trusts only
# the bootloader string in /proc/cmdline.
set -eu

backup=${1:?usage: twrp-restore-boot.sh BACKUP.img SHA256}
expected=${2:?usage: twrp-restore-boot.sh BACKUP.img SHA256}
adb=${ADB:-adb}
target=/dev/block/mmcblk0p20
remote=/tmp/mmcblk0p20-restore.img
token=RESTORE-SM-T560-P20

test "$(wc -c < "$backup")" -eq 16777216 || { echo "ERROR: $backup is not 16777216 bytes"; exit 1; }
echo "$expected  $backup" | sha256sum -c -

state=$("$adb" get-state 2> /dev/null | tr -d '\r' || true)
case "$state" in
    device|recovery) ;;
    *) echo "ERROR: no authorised ADB device (state: '$state'); boot TWRP and allow USB debugging"; exit 1 ;;
esac
"$adb" shell 'grep -q androidboot.bootloader=T560 /proc/cmdline' || { echo "ERROR: the connected device is not an SM-T560"; exit 1; }
"$adb" shell "test -b $target" || { echo "ERROR: $target is missing in this recovery"; exit 1; }
size=$("$adb" shell "blockdev --getsize64 $target" | tr -d '\r')
test "$size" = 16777216 || { echo "ERROR: $target is $size bytes, expected 16777216"; exit 1; }
current=$("$adb" shell "sha256sum $target" | tr -d '\r' | cut -d' ' -f1)
echo "CURRENT_P20_SHA256=$current"
if [ "$current" = "$expected" ]; then
    echo "NOTHING_TO_DO: the partition already holds this backup"
    exit 0
fi

"$adb" push "$backup" "$remote"
uploaded=$("$adb" shell "sha256sum $remote" | tr -d '\r' | cut -d' ' -f1)
test "$uploaded" = "$expected" || { echo "ERROR: the upload is corrupt ($uploaded)"; exit 1; }

printf 'Type %s exactly to write ONLY %s: ' "$token" "$target"
read -r answer
test "$answer" = "$token" || { echo "cancelled, nothing was written"; exit 1; }

"$adb" shell "dd if=$remote of=$target bs=1048576 && sync"
final=$("$adb" shell "sha256sum $target" | tr -d '\r' | cut -d' ' -f1)
echo "COMPLETE_P20_SHA256=$final"
test "$final" = "$expected" || { echo "ERROR: the partition hash does not match; do not reboot, write again"; exit 1; }
"$adb" shell "rm -f $remote"
echo "RESTORE_VERIFIED_NO_REBOOT_PERFORMED (reboot from the TWRP menu)"
