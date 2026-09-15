#!/bin/sh
# Check a tablet that has rebooted into the camera kernel. Read-only. Run on
# the tablet as root (the module parameters are readable by root only):
#
#   sudo sh tablet-verify-camera.sh [expected kernel build tag] [expected p20 sha256]
#
# The defaults match boot/boot-sm-t560-camera-r20.img. Pass the values that
# export-boot.sh printed when you built your own image, or "-" to skip one.
set -eu

tag=${1:-#21-postmarketOS}
p20=${2:-7f12ee7612e49611d9500f19a05e7b7ee76f1d7e330fadbd545d5ca3c859dc84}
user=${SUDO_USER:-vahac}
config=/home/$user/.config/t560-music-panel/config.ini
mlog=/home/$user/.local/state/motion-detector.log

echo '===== DEVICE ====='
grep -o 'androidboot.bootloader=[^ ]*' /proc/cmdline
grep -o 'connie=[^ ]*' /proc/cmdline | cut -c1-30
uname -a
if [ "$tag" != "-" ]; then
    uname -a | grep -q -- "$tag" || { echo "ERROR: the running kernel is not $tag"; exit 1; }
fi

echo
echo '===== CAMERA MODULE PARAMETERS ====='
disable=$(cat /sys/module/sprd_dcam/parameters/gtelwifi_camera_disable)
phy=$(cat /sys/module/sprd_sensor/parameters/gtelwifi_camera_csi_phy_id)
ptn=$(cat /sys/module/sprd_dcam/parameters/gtelwifi_camera_yuv_pattern)
echo "gtelwifi_camera_disable=$disable (expected N)"
echo "gtelwifi_camera_csi_phy_id=$phy (expected 4 = CSI PHY C)"
echo "gtelwifi_camera_yuv_pattern=$ptn (expected 2 = UYVY)"
case "$disable" in N|0) ;; *) echo "ERROR: the camera is switched off by gtelwifi_camera_disable"; exit 1 ;; esac
test "$phy" = 4 || { echo "ERROR: CSI PHY is not 4"; exit 1; }
test "$ptn" = 2 || { echo "ERROR: YUV pattern is not 2"; exit 1; }

echo
echo '===== VIDEO NODE ====='
ls -l /dev/video0
id "$user" | tr ' ' '\n' | grep -q 'video' && echo "$user is in the video group" || echo "WARNING: $user is not in the video group"

echo
echo '===== PANEL CONFIG [camera] ====='
if [ -f "$config" ]; then
    sed -n '/^[[:space:]]*\[camera\][[:space:]]*$/,/^[[:space:]]*\[/p' "$config" | grep -E '^[[:space:]]*(motion_detection|device)[[:space:]]*=' || echo "(defaults)"
else
    echo "no $config"
fi

echo
echo '===== MOTION DETECTOR ====='
pgrep -af '[t]560-motion-detector' || echo "not running (start it, or enable motion_detection and log in again)"
tail -n 5 "$mlog" 2> /dev/null || echo "no $mlog"

echo
echo '===== KERNEL LOG ====='
sofwait=$(dmesg | grep -c 'sof 1 wait' || true)
echo "per-frame 'DCAM: sof 1 wait' lines: $sofwait (must be 0, r20 demotes them)"
dmesg | grep -Ei 'camera|dcam|sr200|sensor|mclk|csi|panic|oops|call trace' | grep -v 'PHY_STATE\[[123]\]' | tail -n 40 || true

echo
echo '===== BOOT PARTITION ====='
current=$(sha256sum /dev/mmcblk0p20 | cut -d' ' -f1)
echo "p20 sha256: $current"
if [ "$p20" != "-" ]; then
    test "$current" = "$p20" || { echo "ERROR: the boot partition does not hold the expected image"; exit 1; }
fi

echo
echo 'CAMERA_KERNEL_VERIFIED'
