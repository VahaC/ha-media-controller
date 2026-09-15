#!/bin/sh
# Stage the SM-T560 camera kernel package into the local pmaports checkout and
# build it with pmbootstrap. Local only: the tablet is never touched.
#
# Usage: build-kernel.sh [--dry-run]
# --dry-run verifies the package files and exits without staging or building.
#
# The package directory next to this script holds only the files that differ
# from upstream pmaports (APKBUILD, kernel config, the renamed DTB patch and
# the ten camera patches). The other patches the APKBUILD lists come from the
# pmaports checkout itself, which is why `pmbootstrap init` with device
# samsung-gtelwifi must have run first.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
src="$here/../pmaports/linux-samsung-gtelwifi"
pmb=${PMBOOTSTRAP:-pmbootstrap}
command -v "$pmb" > /dev/null 2>&1 || pmb="$HOME/.local/bin/pmbootstrap"

files="APKBUILD config-samsung-gtelwifi.armv7 fix-dtb_qcom-msm-id.patch"
for p in "$src"/00[0-9][0-9]-sm-t560-*.patch; do
    files="$files $(basename "$p")"
done

verify() {
    dir=$1
    for f in $files; do
        test -f "$dir/$f" || { echo "ERROR: missing $dir/$f"; exit 1; }
    done
    pkgrel=$(sed -n 's/^pkgrel=\([0-9]*\)$/\1/p' "$dir/APKBUILD")
    test -n "$pkgrel" || { echo "ERROR: no pkgrel in $dir/APKBUILD"; exit 1; }
    (cd "$dir" && sed -n '/^sha512sums="/,/^"/p' APKBUILD |
        grep -E '  (00[0-9][0-9]-sm-t560-.*\.patch|config-samsung-gtelwifi\.armv7|fix-dtb_qcom-msm-id\.patch)$' |
        sha512sum -c --quiet -)
    echo "verified $dir: pkgrel=$pkgrel, kernel build tag #$((pkgrel + 1))-postmarketOS"
}

verify "$src"
if [ "${1:-}" = "--dry-run" ]; then
    echo "DRY_RUN_OK: nothing staged, nothing built"
    exit 0
fi

aports=$("$pmb" config aports | tail -n 1)
dst="$aports/device/archived/linux-samsung-gtelwifi"
test -d "$dst" || {
    echo "ERROR: $dst does not exist."
    echo "Run 'pmbootstrap init' with device samsung-gtelwifi first."
    exit 1
}

echo "staging the package into $dst"
for f in $files; do
    cp "$src/$f" "$dst/$f"
done
verify "$dst"

exec "$pmb" build linux-samsung-gtelwifi --force --lax
