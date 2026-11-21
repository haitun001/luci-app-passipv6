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
	luci_commit=ed7692cb08a953e2e503287e0337c8b548cf4ba5
	curl -fsSL --retry 2 -o "$base/luci.tar.gz" "https://codeload.github.com/immortalwrt/luci/tar.gz/$luci_commit"
	tar -xzf "$base/luci.tar.gz" -C "$base"
	mkdir -p feeds
	mv "$base/luci-$luci_commit" feeds/luci
fi
./scripts/feeds update -i luci
./scripts/feeds install -p luci luci-base
if [ ! -f package/libs/libjson-c/Makefile ]; then
	base_commit=a3378d1a2c15beb2faf4b0bce9c00f07143efa29
	curl -fsSL --retry 2 -o "$base/base.tar.gz" "https://codeload.github.com/immortalwrt/immortalwrt/tar.gz/$base_commit"
	tar -xzf "$base/base.tar.gz" -C "$base" "immortalwrt-$base_commit/package/libs/libjson-c"
	mkdir -p package/libs
	cp -r "$base/immortalwrt-$base_commit/package/libs/libjson-c" package/libs/
fi
printf 'SDK ready: %s\n' "$PWD"
