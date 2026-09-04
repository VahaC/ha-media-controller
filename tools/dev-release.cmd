@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Cuts a dev pre-release of the integration.
rem
rem The version is read from the manifest on origin/dev and from nowhere else
rem -- not from the working tree, not from an argument. Three numbers have to
rem agree for a dev release to be usable: the git tag, the version HACS shows,
rem and the version the Home Assistant integration page shows. HACS reads the
rem tag; Home Assistant reads the manifest inside the tag. Every dev release
rem in this repository that went wrong went wrong because one of those three
rem was set by hand and drifted from the others, so this script derives all of
rem them from one source and then verifies the published result.
rem
rem The release is always marked as a GitHub pre-release. That flag, not the
rem "-dev" in the name, is what keeps it out of other users' HACS updates:
rem HACS ignores pre-releases unless the per-repository "Pre-release" switch
rem entity is turned on.
rem
rem Usage:  tools\dev-release.cmd ["release notes"]
rem         With no argument the notes are generated from the commit log.

set "REPO=VahaC/ha-media-controller"
set "MANIFEST=custom_components/media_controller/manifest.json"
set "VERFILE=%TEMP%\mc-dev-release-manifest.txt"

pushd "%~dp0.." || (
    echo ERROR: Cannot open the repository root.
    exit /b 1
)

where git.exe >nul 2>&1
if errorlevel 1 (
    echo ERROR: git is not installed or not in PATH.
    goto :fail
)

where gh.exe >nul 2>&1
if errorlevel 1 (
    echo ERROR: the GitHub CLI ^(gh^) is not installed or not in PATH.
    goto :fail
)

rem --prune-tags also drops local tags that no longer exist on the remote.
rem That is deliberate: a deleted dev tag left behind locally comes back the
rem next time someone runs "git push --tags", pointing at whatever old commit
rem it was made on.
echo Fetching origin...
git fetch --tags --prune --prune-tags origin
if errorlevel 1 (
    echo ERROR: git fetch failed.
    goto :fail
)

set "DEVSHA="
for /f "usebackq delims=" %%i in (`git rev-parse origin/dev`) do set "DEVSHA=%%i"
if not defined DEVSHA (
    echo ERROR: origin/dev could not be resolved.
    goto :fail
)

rem Out-String joins the file back into one string. Windows PowerShell 5.1
rem feeds ConvertFrom-Json one pipeline item per line otherwise, and every
rem line but the last is invalid JSON on its own.
powershell -NoProfile -ExecutionPolicy Bypass -Command "(git show origin/dev:%MANIFEST% | Out-String | ConvertFrom-Json).version" > "%VERFILE%" 2>nul
set "VER="
for /f "usebackq delims=" %%i in ("%VERFILE%") do set "VER=%%i"
del "%VERFILE%" >nul 2>&1
if not defined VER (
    echo ERROR: Could not read "version" from %MANIFEST% on origin/dev.
    goto :fail
)

rem The suffix is stripped and re-added rather than appended blindly, so the
rem manifest may carry either "1.4.0" or "1.4.0-dev" and the tag comes out the
rem same either way.
set "BASE=!VER!"
if /i "!BASE:~-4!"=="-dev" set "BASE=!BASE:~0,-4!"
set "TAG=v!BASE!-dev"
set "EXPECTED=!BASE!-dev"

echo.
echo   origin/dev  !DEVSHA!
echo   manifest    !VER!
echo   tag         !TAG!
echo.

if /i not "!VER!"=="!EXPECTED!" (
    echo WARNING: the manifest on origin/dev says "!VER!" but the release will
    echo          be tagged "!TAG!". HACS will show !BASE!-dev while the
    echo          integration page shows !VER!.
    echo.
    echo          To avoid that, set "version": "!EXPECTED!" in
    echo          %MANIFEST%, commit it to dev, and run this again.
    echo.
    set /p "ANSWER=Continue anyway? [y/N] "
    if /i not "!ANSWER!"=="y" goto :abort
    echo.
)

rem A soft check only. A red run is a reason to look, not a reason to refuse:
rem the workflows are path-filtered, so a commit that touches nothing they
rem watch legitimately has no run at all.
set "CIBAD="
for /f "usebackq delims=" %%i in (`gh run list --repo %REPO% --commit !DEVSHA! --limit 10 --json conclusion --jq ".[].conclusion" 2^>nul`) do (
    if /i not "%%i"=="success" set "CIBAD=1"
)
if defined CIBAD (
    echo WARNING: not every CI run on !DEVSHA:~0,7! finished successfully.
    set /p "ANSWER=Continue anyway? [y/N] "
    if /i not "!ANSWER!"=="y" goto :abort
    echo.
)

set "REMOTETAG="
for /f "usebackq tokens=1" %%i in (`git ls-remote --tags origin "refs/tags/!TAG!"`) do set "REMOTETAG=%%i"

set "RELEASEEXISTS="
gh release view !TAG! --repo %REPO% >nul 2>&1
if not errorlevel 1 set "RELEASEEXISTS=1"

if defined REMOTETAG goto :exists
if defined RELEASEEXISTS goto :exists
goto :create

:exists
if defined REMOTETAG (
    if /i "!REMOTETAG!"=="!DEVSHA!" (
        echo Tag !TAG! already exists on origin and points at origin/dev.
    ) else (
        echo Tag !TAG! already exists on origin but points at !REMOTETAG!,
        echo which is NOT origin/dev.
    )
)
if defined RELEASEEXISTS echo Release !TAG! already exists.
echo.
set /p "ANSWER=Delete and recreate both? [y/N] "
if /i not "!ANSWER!"=="y" goto :abort
echo.
echo Removing the existing release and tag...
gh release delete !TAG! --repo %REPO% --yes --cleanup-tag >nul 2>&1
git push origin ":refs/tags/!TAG!" >nul 2>&1
git tag -d !TAG! >nul 2>&1

:create
echo Tagging origin/dev as !TAG!...
git tag !TAG! origin/dev
if errorlevel 1 (
    echo ERROR: Could not create the tag.
    goto :fail
)

git push origin !TAG!
if errorlevel 1 (
    echo ERROR: Could not push the tag.
    git tag -d !TAG! >nul 2>&1
    goto :fail
)

rem The tag exists before the release is created, so GitHub binds the release
rem to it and never invents one of its own. A release created for a tag that
rem does not exist yet gets a tag on the DEFAULT branch, which here is main --
rem that is how a "dev release" shipped the stable code more than once.
echo Creating the pre-release...
if "%~1"=="" (
    gh release create !TAG! --repo %REPO% --prerelease --title "!TAG!" --generate-notes
) else (
    gh release create !TAG! --repo %REPO% --prerelease --title "!TAG!" --notes "%~1"
)
if errorlevel 1 (
    echo ERROR: Could not create the release. The tag !TAG! is already pushed.
    goto :fail
)

echo.
echo Verifying what was actually published...

set "TAGSHA="
for /f "usebackq tokens=1" %%i in (`git ls-remote --tags origin "refs/tags/!TAG!"`) do set "TAGSHA=%%i"
if /i not "!TAGSHA!"=="!DEVSHA!" (
    echo ERROR: !TAG! points at !TAGSHA!, not at origin/dev ^(!DEVSHA!^).
    goto :fail
)
echo   [ok] tag points at origin/dev

rem Read the manifest back through the API, from the tag, the way HACS will.
rem This is the check that would have caught every previous broken release.
powershell -NoProfile -ExecutionPolicy Bypass -Command "(gh api repos/%REPO%/contents/%MANIFEST%?ref=!TAG! -H 'Accept: application/vnd.github.raw' | Out-String | ConvertFrom-Json).version" > "%VERFILE%" 2>nul
set "PUBVER="
for /f "usebackq delims=" %%i in ("%VERFILE%") do set "PUBVER=%%i"
del "%VERFILE%" >nul 2>&1
if /i not "!PUBVER!"=="!VER!" (
    echo ERROR: the manifest inside !TAG! says "!PUBVER!", expected "!VER!".
    goto :fail
)
echo   [ok] manifest inside the tag is !PUBVER!

set "LATEST="
for /f "usebackq delims=" %%i in (`gh api repos/%REPO%/releases/latest --jq ".tag_name" 2^>nul`) do set "LATEST=%%i"
if /i "!LATEST!"=="!TAG!" (
    echo ERROR: GitHub still reports !TAG! as the latest release. The
    echo        pre-release flag did not take, and every HACS user is being
    echo        offered this build as an update.
    goto :fail
)
echo   [ok] latest release is still !LATEST!

echo.
echo Published: https://github.com/%REPO%/releases/tag/!TAG!
echo.
echo Integration: in HACS open Media Controller, choose Redownload, pick
echo !TAG! under "Need a different version?", then restart Home Assistant.
echo.
echo ESP32 panel: HACS does not carry the firmware. Point the device at this
echo tag as well, or it keeps building against main:
echo.
echo   substitutions:
echo     grid_component_source: "github://%REPO%@!TAG!"
echo     asset_base_url: "https://raw.githubusercontent.com/%REPO%/!TAG!/firmware/assets"
echo.
echo   packages:
echo     media_controller:
echo       url: https://github.com/%REPO%
echo       ref: !TAG!
echo       files:
echo         - firmware/media-controller-paired.yaml
echo       refresh: 1h
echo.
echo Run "esphome clean" before compiling; the remote package is cached.
popd
pause
exit /b 0

:abort
echo Aborted. Nothing was tagged or published.
popd
pause
exit /b 1

:fail
popd
pause
exit /b 1
