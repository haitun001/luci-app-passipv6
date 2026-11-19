import json
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1]
for file in (root / 'root').rglob('*.json'):
    json.loads(file.read_text(encoding='utf-8'))
source = (root / 'htdocs/luci-static/resources/view/passipv6.js').read_text(encoding='utf-8')
po = (root / 'po/zh_Hans/passipv6.po').read_text(encoding='utf-8')
messages = set(re.findall(r"_\('([^']*)'\)", source))
translations = dict(re.findall(r'msgid "([^"\n]+)"\s+msgstr "([^"\n]+)"', po))
assert not messages - translations.keys(), f'Missing translations: {messages - translations.keys()}'
assert all(translations.values())
acl = json.loads((root / 'root/usr/share/rpcd/acl.d/luci-app-passipv6.json').read_text(encoding='utf-8'))['luci-app-passipv6']
assert acl['write']['uci'] == ['passipv6']
assert acl['write']['ubus'] == {'luci.passipv6': ['apply']}
assert 'file' not in acl['write']
assert not re.search(r'passwall|ad filtering|广告过滤', source + po, re.I)
makefile = (root / 'Makefile').read_text(encoding='utf-8')
assert 'PKG_LICENSE:=Apache-2.0' in makefile
version = re.search(r'^PKG_VERSION:=(.+)$', makefile, re.M).group(1)
assert json.loads((root / 'package.json').read_text(encoding='utf-8'))['version'] == version
assert f'## {version}\n' in (root / 'CHANGELOG.md').read_text(encoding='utf-8')
print(f'PASS: JSON, {len(messages)} translated messages and RPC privilege boundaries')
