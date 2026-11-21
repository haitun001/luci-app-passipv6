#!/bin/sh
# Run inside Linux/WSL with the official ImmortalWrt SDK.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sdk=${PASSIPV6_SDK:?Set PASSIPV6_SDK to the extracted ImmortalWrt 25.12.1 SDK}
test -f "$sdk/include/package.mk"
test -f "$sdk/feeds/luci/luci.mk"
mkdir -p "$sdk/package/passipv6" "$project/artifacts" "$project/build"
cp "$project/Makefile" "$sdk/package/passipv6/Makefile"
cp -r "$project/root" "$project/htdocs" "$project/po" "$project/src" "$sdk/package/passipv6/"
chmod 755 "$sdk/package/passipv6/root/usr/libexec/passipv6" \
	"$sdk/package/passipv6/root/etc/init.d/passipv6" \
	"$sdk/package/passipv6/root/etc/uci-defaults/90-passipv6" \
	"$sdk/package/passipv6/root/etc/hotplug.d/net/90-passipv6" \
	"$sdk/package/passipv6/root/usr/share/passipv6/firewall.include"
cd "$sdk"
printf '%s\n' 'CONFIG_PACKAGE_luci-app-passipv6=m' 'CONFIG_LUCI_LANG_zh_Hans=y' >> .config
make defconfig > "$project/build/sdk-build.log" 2>&1
# Build the native RA helper and LuCI translations with the SDK toolchain.
make package/toolchain/compile NO_DEPS=1 V=s >> "$project/build/sdk-build.log" 2>&1
make package/libs/libjson-c/compile NO_DEPS=1 V=s >> "$project/build/sdk-build.log" 2>&1
make package/feeds/luci/luci-base/host/compile NO_DEPS=1 V=s >> "$project/build/sdk-build.log" 2>&1
make package/passipv6/compile NO_DEPS=1 V=s -j2 >> "$project/build/sdk-build.log" 2>&1 || {
	tail -n 55 "$project/build/sdk-build.log"
	exit 1
}
version=$(sed -n 's/^PKG_VERSION:=//p' "$project/Makefile")
release=$(sed -n 's/^PKG_RELEASE:=//p' "$project/Makefile")
for package in luci-app-passipv6 luci-i18n-passipv6-zh-cn; do
	find bin/packages -name "$package-$version-r$release.apk" -exec cp {} "$project/artifacts/" \;
done
cd "$project/artifacts"
sha256sum ./*.apk > SHA256SUMS
