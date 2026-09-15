#!/bin/sh
# Live motion-detection check. Run on the tablet as the panel user, no sudo,
# nothing is changed:
#
#   sh test-motion-detection.sh [seconds]
#
# It records the log positions, waits while you wave at the front camera,
# then prints the new lines of the detector log and the power-button log.
mlog=$HOME/.local/state/motion-detector.log
plog=$HOME/.local/state/power-button.log
wait_seconds=${1:-15}

echo '===== KERNEL ====='
uname -a
echo '===== DETECTOR PROCESS ====='
pgrep -af '[t]560-motion-detector' || { echo 'ERROR: the motion detector is not running'; tail -n 20 "$mlog" 2> /dev/null; exit 1; }
echo '===== DETECTOR LOG (last 10) ====='
tail -n 10 "$mlog" 2> /dev/null || echo "no $mlog"
m_before=$(wc -l < "$mlog" 2> /dev/null || echo 0)
p_before=$(wc -l < "$plog" 2> /dev/null || echo 0)
echo
echo "===== WAVE YOUR HAND IN FRONT OF THE FRONT CAMERA NOW ($wait_seconds s) ====="
sleep "$wait_seconds"
echo '===== NEW DETECTOR LOG LINES ====='
tail -n +"$((m_before + 1))" "$mlog" 2> /dev/null
echo '===== NEW POWER-BUTTON LOG LINES ====='
tail -n +"$((p_before + 1))" "$plog" 2> /dev/null
if tail -n +"$((m_before + 1))" "$mlog" 2> /dev/null | grep -q 'motion: detected'; then
    echo 'MOTION_DETECTED_OK'
    exit 0
fi
if tail -n +"$((p_before + 1))" "$plog" 2> /dev/null | grep -qi 'motion'; then
    echo 'MOTION_SEEN_BY_POWER_HANDLER_OK'
    exit 0
fi
echo 'NO_MOTION_EVENT_IN_WINDOW (the detector logs only the first event of a burst; check the lines above)'
exit 1
