#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if command -v ucode >/dev/null 2>&1; then
	exec ucode -L "$project/root/usr/share/ucode" "$@"
fi
runtime=${PASSIPV6_RUNTIME:-$project/build/runtime}
exec "$runtime/lib/ld-musl-x86_64.so.1" \
	--library-path "$runtime/lib:$runtime/usr/lib" "$runtime/usr/bin/ucode" \
	-L "$runtime/usr/lib/ucode" -L "$project/root/usr/share/ucode" "$@"
