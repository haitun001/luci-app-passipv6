#!/bin/sh
set -eu
umask 077

VERSION='@VERSION@'
REVISION='@REVISION@'
BASE="https://github.com/haitun001/luci-app-passipv6/releases/download/$VERSION"

fail() { printf 'PassIPV6: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail 'Run this installer as root.'
for tool in apk ubus jsonfilter ucode nft fw4 ip uci sha256sum mktemp; do
	command -v "$tool" >/dev/null 2>&1 || fail "Required command is missing: $tool"
done
board=$(ubus call system board)
distribution=$(printf '%s' "$board" | jsonfilter -e '@.release.distribution')
release=$(printf '%s' "$board" | jsonfilter -e '@.release.version')
target=$(printf '%s' "$board" | jsonfilter -e '@.release.target')
[ "$distribution" = ImmortalWrt ] || fail 'This installer supports ImmortalWrt only.'
[ "$target" = x86/64 ] || fail 'This release is validated for x86/64 only.'
case "$release" in ''|*[!0-9.]*|.*|*.|*..*) fail 'A numbered stable ImmortalWrt release is required.' ;; esac
comparison=$(apk version -t "$release" 25.12.1)
case "$comparison" in '='|'>') ;; *) fail 'ImmortalWrt 25.12.1 or newer is required.' ;; esac
apk info -e luci-base rpcd-mod-ucode ucode-mod-fs ucode-mod-uci ucode-mod-ubus ip-full >/dev/null ||
	fail 'Install the required LuCI/ucode and ip-full runtime packages first.'
ip -j link show >/dev/null || fail 'JSON-capable ip-full is required.'

download() {
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL --retry 2 --connect-timeout 10 --max-time 60 -o "$2" "$1"
	elif command -v uclient-fetch >/dev/null 2>&1; then
		uclient-fetch -q -T 60 -O "$2" "$1"
	else
		fail 'uclient-fetch or curl is required.'
	fi
}

work=$(mktemp -d /tmp/passipv6-install.XXXXXX)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
app="luci-app-passipv6-$VERSION-r$REVISION.apk"
language="luci-i18n-passipv6-zh-cn-$VERSION-r$REVISION.apk"
download "$BASE/SHA256SUMS" "$work/SHA256SUMS"
for package in "$app" "$language"; do
	awk -v name="$package" '
		$2 == name { if (length($1) != 64 || $1 ~ /[^0-9a-fA-F]/) exit 1; print; count++ }
		END { if (count != 1) exit 1 }
	' "$work/SHA256SUMS" >> "$work/packages.sha256" || fail "Invalid checksum entry: $package"
	download "$BASE/$package" "$work/$package"
done
(cd "$work" && sha256sum -c packages.sha256) || fail 'Package checksum verification failed.'

mkdir "$work/stage"
apk extract --allow-untrusted --destination "$work/stage" "$work/$app"
ucode -L "$work/stage/usr/share/ucode" "$work/stage/usr/share/passipv6/run.uc" check ||
	fail 'Compatibility check failed; the installed policy was not changed.'

previous=$(uci -q export passipv6 2>/dev/null || true)
apk add --simulate --allow-untrusted --force-reinstall --no-network --repositories-file /dev/null \
	"$work/$app" "$work/$language"
apk add --allow-untrusted --force-reinstall --no-network --repositories-file /dev/null \
	"$work/$app" "$work/$language"
if [ -n "$previous" ]; then
	[ "$(uci -q export passipv6)" = "$previous" ] ||
		fail 'Configuration changed during installation. Review the current allowlist.'
fi
ucode -e 'import { status } from "passipv6"; let s = status(); if (!s.active || !s.applied) { warn(s.error ?? "IPv6 protection is not active", "\n"); exit(1); }' ||
	fail 'The package is installed, but the active policy could not be verified.'
printf 'PassIPV6 %s-r%s installed and active. Open Services > PassIPV6 in LuCI.\n' "$VERSION" "$REVISION"
