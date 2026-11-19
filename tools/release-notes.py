#!/usr/bin/env python3
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
root = pathlib.Path(__file__).resolve().parents[1]
version = sys.argv[1]
assert re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', version)
changes = (root / 'CHANGELOG.md').read_text(encoding='utf-8').split(f'## {version}\n', 1)[1].split('\n## ', 1)[0].strip()
readme = (root / 'README.md').read_text(encoding='utf-8')
command = readme.split('<!-- install-command -->\n```sh\n', 1)[1].split('\n```', 1)[0]
print(changes)
print('\n### 安装 / 升级 / 重装 · Install / upgrade / reinstall\n')
print('适用于 x86/64、ImmortalWrt 25.12.1 及更高正式版，须通过运行时能力检查。首次安装默认空白名单，请使用 IPv4 管理连接。已有白名单会保留。')
print('\nFor x86/64 ImmortalWrt 25.12.1 or newer stable releases with the required runtime capabilities. Use an IPv4 management connection for a first installation. Existing allowlists are preserved.')
print('\n以下命令安装最新正式版；下载失败不会执行不完整脚本，安装包会校验 SHA-256。\n')
print('```sh\n' + command + '\n```')
print('\nAssets: application APK, Simplified Chinese APK, version-pinned install.sh and SHA256SUMS. Older releases are not overwritten.')
