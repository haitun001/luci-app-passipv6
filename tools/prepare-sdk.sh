#!/bin/sh
set -eu
base=/opt/passipv6-build/sdk
archive=immortalwrt-sdk-25.12.1-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst
url=https://downloads.immortalwrt.org/releases/25.12.1/targets/x86/64
mkdir -p "$base"
cd "$base"
test -f sdk.tar.zst || curl -fsSL --retry 2 -o sdk.tar.zst "$url/$archive"
test -f sha256sums || curl -fsSL -o sha256sums "$url/sha256sums"
expected=$(awk -v name="$archive" '$2 == "*" name || $2 == name { print $1 }' sha256sums)
test -n "$expected"
printf '%s  sdk.tar.zst\n' "$expected" | sha256sum -c -
test -d "${archive%.tar.zst}" || tar --zstd -xf sdk.tar.zst
cd "${archive%.tar.zst}"
if [ ! -f feeds/luci/luci.mk ]; then
	git clone --depth 1 --branch openwrt-25.12 https://github.com/immortalwrt/luci.git feeds/luci
fi
./scripts/feeds update -i luci
./scripts/feeds install -p luci luci-base
printf 'SDK ready: %s\n' "$PWD"
