#!/bin/sh
set -eu
base=/opt/passipv6-build/vm
name=immortalwrt-25.12.1-x86-64-generic-ext4-combined.img.gz
url=https://downloads.immortalwrt.org/releases/25.12.1/targets/x86/64
mkdir -p "$base"
cd "$base"
if [ ! -f disk.img ]; then
	curl -fsSL --retry 2 -o "$name" "$url/$name"
	curl -fsSL -o sha256sums "$url/sha256sums"
	expected=$(awk -v name="$name" '$2 == "*" name || $2 == name { print $1 }' sha256sums)
	printf '%s  %s\n' "$expected" "$name" | sha256sum -c -
	gzip -dc "$name" > disk.img
	qemu-img resize -f raw disk.img 512M
fi
exec qemu-system-x86_64 -m 768 -smp 2 -accel tcg \
	-drive file=disk.img,format=raw,if=virtio \
	-netdev user,id=lan,net=192.168.1.0/24,host=192.168.1.2,dhcpstart=192.168.1.100,hostfwd=tcp:127.0.0.1:22222-192.168.1.1:22,hostfwd=tcp:127.0.0.1:22280-192.168.1.1:80 \
	-device virtio-net-pci,netdev=lan \
	-display none -monitor none -serial tcp:127.0.0.1:22444,server=on,wait=off
