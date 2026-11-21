#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "${1:-}" != isolated ]; then
	exec unshare --mount --net --pid --fork --mount-proc sh "$0" isolated
fi
mount --make-rprivate /
mkdir -p /run/netns
mount -t tmpfs tmpfs /run/netns
mkdir -p /var/run/passipv6
mount -t tmpfs tmpfs /var/run/passipv6
exec python3 "$project/tests/network.py"
