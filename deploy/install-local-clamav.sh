#!/bin/sh
# Debian/Ubuntu user-level installation; no package scripts or root access.
set -eu
umask 077
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
clamav_dir="$project_dir/.local-tools/clamav"
mkdir -p "$clamav_dir/packages" "$clamav_dir/runtime"
package_dir=$(mktemp -d "$clamav_dir/packages/install.XXXXXX")
trap 'rm -rf -- "$package_dir"' EXIT HUP INT TERM

# Native hosting images can have empty system package indexes. Keep APT's
# indexes, archives and locks writable without sudo; use the host's sources,
# signing keys and installed-package status. Skip system APT hooks, which can
# write outside this directory even during an index refresh.
mkdir -p "$package_dir/state/lists/partial" "$package_dir/cache/archives/partial" \
    "$package_dir/log" "$package_dir/apt.conf.d"
cp /var/lib/dpkg/status "$package_dir/state/status"
cat > "$package_dir/apt.conf" <<EOF
Dir::Etc::parts "$package_dir/apt.conf.d";
Dir::Etc::main "/dev/null";
Dir::State "$package_dir/state";
Dir::State::status "$package_dir/state/status";
Dir::Cache "$package_dir/cache";
Dir::Log "$package_dir/log";
APT::Sandbox::User "$(id -un)";
Acquire::Languages "none";
EOF
export APT_CONFIG="$package_dir/apt.conf"
apt-get update --error-on=any
# Resolve library names for this distribution instead of assuming Ubuntu 24.04.
# Download-only never installs system packages or runs their maintainer scripts.
apt-get install --download-only --reinstall --no-install-recommends -y clamav clamav-freshclam
for package in "$package_dir"/cache/archives/*.deb; do
    dpkg-deb -x "$package" "$clamav_dir/runtime"
done
unset APT_CONFIG
"$project_dir/deploy/clamav-local" update
