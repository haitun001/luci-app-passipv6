#!/usr/bin/env python3
"""Prepare the two packages, versioned installer and checksums for one release."""
import hashlib
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[1]
output = pathlib.Path(sys.argv[1])
makefile = (root / 'Makefile').read_text(encoding='utf-8')
version = re.search(r'^PKG_VERSION:=([0-9]+(?:\.[0-9]+)+)$', makefile, re.M).group(1)
revision = re.search(r'^PKG_RELEASE:=([0-9]+)$', makefile, re.M).group(1)
expected = [f'{package}-{version}-r{revision}.apk' for package in ['luci-app-passipv6', 'luci-i18n-passipv6-zh-cn']]
assert sorted(p.name for p in output.glob('*.apk')) == sorted(expected), 'Unexpected package assets'
installer = (root / 'tools/install.sh').read_text(encoding='utf-8').replace('@VERSION@', version).replace('@REVISION@', revision)
(output / 'install.sh').write_text(installer, encoding='utf-8', newline='\n')
assets = [output / name for name in expected] + [output / 'install.sh']
(output / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in assets), encoding='ascii')
print(f'Prepared {version}: two APKs, install.sh and SHA256SUMS')
