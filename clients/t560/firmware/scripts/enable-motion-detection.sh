#!/bin/sh
# Switch motion_detection to "on" in the [camera] section of the panel
# configuration. Run on the tablet as the panel user, no sudo:
#
#   sh enable-motion-detection.sh
#
# A timestamped copy of config.ini is kept next to it and nothing else in the
# file changes. The detector is started by the Openbox autostart, so the
# change takes effect at the next login or reboot; to start it right away:
#
#   nohup python3 ~/.local/bin/t560-motion-detector.py >> ~/.local/state/motion-detector.log 2>&1 &
set -e

config=$HOME/.config/t560-music-panel/config.ini
test -f "$config" || { echo "ERROR: $config is missing; install and pair the panel first"; exit 1; }
test -w "$config" || { echo "ERROR: $config is not writable"; exit 1; }
grep -q '^[[:space:]]*\[camera\][[:space:]]*$' "$config" || { echo "ERROR: $config has no [camera] section"; exit 1; }

echo '===== BEFORE ====='
sed -n '/^[[:space:]]*\[camera\][[:space:]]*$/,/^[[:space:]]*\[/p' "$config"

if grep -q '^[[:space:]]*motion_detection[[:space:]]*=[[:space:]]*on[[:space:]]*$' "$config"; then
    echo 'MOTION_DETECTION_ALREADY_ON'
else
    backup="$config.bak-$(date +%Y%m%d-%H%M%S)"
    cp -p "$config" "$backup"
    chmod 0600 "$backup"
    echo "CONFIG_BACKUP=$backup"
    tmp="$config.tmp.$$"
    awk '
        /^[[:space:]]*\[/ { in_camera = ($0 ~ /^[[:space:]]*\[camera\][[:space:]]*$/) }
        in_camera && /^[[:space:]]*motion_detection[[:space:]]*=/ { print "motion_detection=on"; changed = 1; next }
        { print }
        END { if (!changed) exit 63 }
    ' "$config" > "$tmp" || { rm -f "$tmp"; echo 'ERROR: no motion_detection key in the [camera] section'; exit 1; }
    chmod 0600 "$tmp"
    mv "$tmp" "$config"
    echo 'MOTION_DETECTION_SET_ON'
fi

echo '===== AFTER ====='
sed -n '/^[[:space:]]*\[camera\][[:space:]]*$/,/^[[:space:]]*\[/p' "$config"
grep -q '^[[:space:]]*motion_detection[[:space:]]*=[[:space:]]*on[[:space:]]*$' "$config" || { echo 'ERROR: verification failed'; exit 1; }
echo 'MOTION_DETECTION_CONFIG_ENABLED'
