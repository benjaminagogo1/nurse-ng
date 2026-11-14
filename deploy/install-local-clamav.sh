#!/bin/sh
# Ubuntu/Debian user-level installation; no package scripts or root access.
set -eu
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
clamav_dir="$project_dir/.local-tools/clamav"
mkdir -p "$clamav_dir/packages" "$clamav_dir/runtime"
package_dir=$(mktemp -d "$clamav_dir/packages/install.XXXXXX")
trap 'rm -rf -- "$package_dir"' EXIT HUP INT TERM
cd "$package_dir"
apt-get download clamav clamav-freshclam libclamav12 libmspack0t64
for package in ./*.deb; do
    dpkg-deb -x "$package" "$clamav_dir/runtime"
done
"$project_dir/deploy/clamav-local" update
