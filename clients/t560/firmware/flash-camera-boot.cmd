@echo off
setlocal
title SM-T560 camera kernel: guarded flash of the boot partition over SSH

set "TABLET_IP=%T560_TABLET_IP%"
if not defined TABLET_IP set "TABLET_IP=192.168.1.105"
set "TABLET_USER=%T560_TABLET_USER%"
if not defined TABLET_USER set "TABLET_USER=vahac"
set "IMAGE=%~1"
if "%IMAGE%"=="" set "IMAGE=%~dp0boot\boot-sm-t560-camera-r20.img"
set "SCRIPT=%~dp0scripts\tablet-flash-boot.sh"

if not exist "%IMAGE%" (
    echo ERROR: image not found: %IMAGE%
    goto :failed
)
if not exist "%SCRIPT%" (
    echo ERROR: flash script not found: %SCRIPT%
    goto :failed
)
for /f %%H in ('powershell.exe -NoProfile -Command "(Get-FileHash -LiteralPath '%IMAGE%' -Algorithm SHA256).Hash.ToLowerInvariant()"') do set "IMAGE_SHA=%%H"
for %%I in ("%IMAGE%") do set "IMAGE_SIZE=%%~zI"

echo Tablet:  %TABLET_USER%@%TABLET_IP%   (override with T560_TABLET_IP / T560_TABLET_USER)
echo Image:   %IMAGE%
echo Size:    %IMAGE_SIZE% bytes
echo SHA256:  %IMAGE_SHA%
echo.
echo This writes ONLY /dev/mmcblk0p20, the 16 MiB boot partition, and never reboots.
echo Make the backup first (README.md, step 2). Dropbear asks for the SSH password at every step.
echo.

echo Step 1 of 3: upload the flash script to /tmp.
ssh.exe -T %TABLET_USER%@%TABLET_IP% "umask 077; cat > /tmp/tablet-flash-boot.sh" < "%SCRIPT%"
if errorlevel 1 goto :failed

echo Step 2 of 3: upload the image to /tmp.
ssh.exe -T %TABLET_USER%@%TABLET_IP% "umask 077; cat > /tmp/boot-to-flash.img" < "%IMAGE%"
if errorlevel 1 goto :failed

echo Step 3 of 3: guarded write. Enter the sudo password, then type the confirmation token when asked.
ssh.exe -tt %TABLET_USER%@%TABLET_IP% "sudo sh /tmp/tablet-flash-boot.sh /tmp/boot-to-flash.img %IMAGE_SHA%; rc=$?; rm -f /tmp/boot-to-flash.img /tmp/tablet-flash-boot.sh; exit $rc"
if errorlevel 1 goto :failed

echo.
echo FLASH_VERIFIED. Reboot when you are ready:  ssh -t %TABLET_USER%@%TABLET_IP% "sudo reboot"
pause
exit /b 0

:failed
echo.
echo ERROR: the flash did not complete. Do not reboot until the boot partition is verified or restored.
pause
exit /b 1
