#!/bin/sh
# Check that the SM-T560 camera patch series applies cleanly, in order, to the
# exact upstream kernel commit the APKBUILD builds from.
#
# abuild applies patches with GNU patch and fuzz 2, which can put a hunk with
# asymmetric context in the wrong place without any error. This script applies
# every patch to a pristine tree twice: with `git apply --check` and with
# `patch -p1 -F0` (no fuzz at all). Both must succeed for every patch.
#
# Usage: verify-patches.sh [work-dir]
# Needs: tar, git, GNU patch, sha512sum, and either curl or a pmbootstrap
# distfiles cache that already holds the kernel tarball (about 120 MB).
# Nothing outside work-dir (default /tmp/t560-kernel-verify) is written.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
pkg="$here/../pmaports/linux-samsung-gtelwifi"
work=${1:-/tmp/t560-kernel-verify}

commit=$(sed -n 's/^_commit="\(.*\)"$/\1/p' "$pkg/APKBUILD")
repo=$(sed -n 's/^_repository="\(.*\)"$/\1/p' "$pkg/APKBUILD")
name="linux-samsung-gtelwifi-$commit.tar.gz"
expected=$(sed -n "s/^\([0-9a-f]\{128\}\)  $name\$/\1/p" "$pkg/APKBUILD")
test -n "$commit" && test -n "$repo" && test -n "$expected"

mkdir -p "$work"
tarball="$work/$name"
cache="$HOME/.local/var/pmbootstrap/cache_distfiles/$name"
if [ ! -s "$tarball" ]; then
    if [ -s "$cache" ]; then
        echo "using the pmbootstrap distfiles cache: $cache"
        cp "$cache" "$tarball"
    else
        echo "downloading the kernel source tarball"
        curl -L -o "$tarball" "https://github.com/pmsourcedump/$repo/archive/$commit.tar.gz"
    fi
fi
echo "$expected  $tarball" | sha512sum -c -

echo "extracting a pristine tree into $work/tree"
rm -rf "$work/tree"
mkdir "$work/tree"
tar -xzf "$tarball" -C "$work/tree" --strip-components=1
cd "$work/tree"
git init -q
git config core.autocrlf false
git config user.name verify
git config user.email verify@localhost
git add -A
git commit -q -m "upstream $repo $commit"

for p in "$pkg"/00[0-9][0-9]-sm-t560-*.patch; do
    n=$(basename "$p")
    git apply --check "$p"
    patch -p1 --dry-run -F0 < "$p" > /dev/null
    patch -p1 -F0 < "$p" > /dev/null
    git add -A
    git commit -q -m "$n"
    echo "OK  $n"
done
echo "PATCH_SERIES_VERIFIED on $repo@$commit"
