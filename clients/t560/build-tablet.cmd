@echo off
setlocal

pushd "%~dp0" || (
    echo ERROR: Cannot open the project directory.
    exit /b 1
)

where docker.exe >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker Desktop is not installed or docker.exe is not in PATH.
    popd
    exit /b 1
)

echo Building and testing the T560 panel for ARMv7...
docker run --rm --platform linux/arm/v7 ^
    -v "%CD%:/src" ^
    -w /src alpine:3.20 ^
    sh -lc "set -eu; apk add --no-cache build-base gtk+3.0-dev libsoup3-dev json-glib-dev file; make clean; make; make test; file t560-panel | tee /tmp/t560-file; grep -q 'ELF 32-bit' /tmp/t560-file; grep -q 'ARM' /tmp/t560-file; grep -q 'EABI5' /tmp/t560-file; grep -q '/lib/ld-musl-armhf.so.1' /tmp/t560-file; sha256sum t560-panel src/main.c src/application.c src/application.h src/app_config.c src/app_config.h src/home_assistant_client.c src/home_assistant_client.h src/json_helpers.c src/json_helpers.h src/panel_ui.c src/panel_ui.h src/system_status.c src/system_status.h tests/test_json_helpers.c data/t560.gresource.xml data/icons/*.png > SHA256SUMS"

if errorlevel 1 (
    echo ERROR: The ARMv7 build or tests failed.
    popd
    exit /b 1
)

echo.
echo Build complete: %CD%\t560-panel
echo SHA256SUMS has been updated.
popd
pause
exit /b 0
