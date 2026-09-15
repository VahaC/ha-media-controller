@echo off
setlocal
title SM-T560 camera kernel: build and export in WSL

echo Local build only: the tablet is not accessed.
echo Requires WSL Ubuntu with pmbootstrap initialised for samsung-gtelwifi.
echo Enter the WSL sudo password if pmbootstrap asks for it.
echo The image is written to boot\boot-sm-t560-camera.img (delete an old one first).
echo.

wsl.exe -d Ubuntu --cd "%~dp0." -- bash -lc "scripts/build-kernel.sh && scripts/export-boot.sh boot/boot-sm-t560-camera.img"
set "RESULT=%errorlevel%"
echo.
echo build exit code: %RESULT%
pause
exit /b %RESULT%
