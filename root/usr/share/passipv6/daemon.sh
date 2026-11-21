#!/bin/sh
umask 077
/usr/libexec/passipv6-ra daemon &
worker=$!
trap 'kill "$worker" 2>/dev/null; wait "$worker" 2>/dev/null' EXIT
trap 'exit 0' INT TERM
/usr/libexec/passipv6 reload || true
wait "$worker"
