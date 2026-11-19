const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const quote = s => "'" + s.replaceAll("'", "'\\''") + "'";
const source = fs.readFileSync(path.join(__dirname, '../tools/install.sh'), 'utf8')
  .replaceAll('@VERSION@', '1.0.1').replaceAll('@REVISION@', '1');
const digest = createHash('sha256').update('package').digest('hex');
const stubs = `
id() { if [ "$CASE" = nonroot ]; then echo 1000; else echo 0; fi; }
ubus() { printf '{}'; }
jsonfilter() {
 cat >/dev/null
 case "$2" in
  '@.release.distribution') if [ "$CASE" = distro ]; then echo OpenWrt; else echo ImmortalWrt; fi ;;
  '@.release.target') if [ "$CASE" = arch ]; then echo armsr/armv8; else echo x86/64; fi ;;
  '@.release.version') if [ "$CASE" = snapshot ]; then echo SNAPSHOT; elif [ "$CASE" = future ]; then echo 27.12.1; else echo 25.12.1; fi ;;
 esac
}
nft() { return 0; }
fw4() { return 0; }
ip() { return 0; }
uci() { [ -f "$CASE_ROOT/config" ] && cat "$CASE_ROOT/config"; }
mktemp() { command mktemp -d "$CASE_ROOT/work.XXXXXX"; }
uclient-fetch() {
 [ "$1" = -q ] && [ "$2" = -O ] || return 1
 printf '%s\\n' "$4" >> "$CASE_ROOT/downloads"
 case "$4" in
  https://github.com/haitun001/luci-app-passipv6/releases/download/1.0.1/SHA256SUMS)
   printf '%s  %s\\n' '${digest}' luci-app-passipv6-1.0.1-r1.apk > "$3"
   if [ "$CASE" = duplicate ]; then printf '%s  %s\\n' '${digest}' luci-app-passipv6-1.0.1-r1.apk >> "$3"; fi
   if [ "$CASE" != missing ]; then printf '%s  %s\\n' '${digest}' luci-i18n-passipv6-zh-cn-1.0.1-r1.apk >> "$3"; fi
   ;;
  https://github.com/haitun001/luci-app-passipv6/releases/download/1.0.1/luci-app-passipv6-1.0.1-r1.apk|https://github.com/haitun001/luci-app-passipv6/releases/download/1.0.1/luci-i18n-passipv6-zh-cn-1.0.1-r1.apk)
   printf package > "$3"
   if [ "$CASE" = checksum ]; then printf corrupt >> "$3"; fi
   ;;
  *) return 1 ;;
 esac
 [ "$CASE" != download ]
}
apk() {
 case "$1" in
  version) if [ "$CASE" = old ]; then echo '<'; elif [ "$CASE" = future ]; then echo '>'; else echo '='; fi ;;
  info) [ "$CASE" != dependencies ] ;;
  extract) printf 'extract\\n' >> "$CASE_ROOT/order" ;;
  add)
   case " $* " in *' --force-reinstall '*) ;; *) return 1 ;; esac
   case " $* " in *' --no-network --repositories-file /dev/null '*) ;; *) return 1 ;; esac
   for arg do case "$arg" in --force-overwrite|--upgrade) return 1 ;; esac; done
   if [ "$2" = --simulate ]; then printf 'simulate\\n' >> "$CASE_ROOT/order"; [ "$CASE" != solve ]; return; fi
   printf 'install\\n' >> "$CASE_ROOT/order"
   [ "$CASE" != install ] || return 1
   printf '1.0.1-r1' > "$CASE_ROOT/program"
   [ -f "$CASE_ROOT/config" ] || printf 'network lan' > "$CASE_ROOT/config"
   ;;
  *) return 1 ;;
 esac
}
ucode() {
 if [ "$1" = -L ]; then printf 'check\\n' >> "$CASE_ROOT/order"; [ "$CASE" != capability ];
 else printf 'status\\n' >> "$CASE_ROOT/order"; [ "$CASE" != inactive ]; fi
}
`;

for (const scenario of ['new', 'upgrade', 'repeat', 'future', 'nonroot', 'distro', 'arch', 'snapshot', 'old', 'dependencies', 'duplicate', 'missing', 'checksum', 'download', 'capability', 'solve', 'install', 'inactive']) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'passipv6-install-test-'));
  try {
    const installer = path.join(root, 'install.sh');
    fs.writeFileSync(installer, source);
    fs.writeFileSync(path.join(root, 'unrelated.apk'), 'keep');
    if (scenario !== 'new') fs.writeFileSync(path.join(root, 'config'), 'network lan\nmac 02:00:00:00:00:0a');
    fs.writeFileSync(path.join(root, 'program'), scenario === 'repeat' ? 'damaged' : '1.0.0-r2');
    const run = () => spawnSync('bash', ['-c', stubs + '\n. ' + quote(installer)], {
      env: { ...process.env, CASE: scenario, CASE_ROOT: root }, encoding: 'utf8'
    });
    const result = run();
    assert.ifError(result.error);
    const success = ['new', 'upgrade', 'repeat', 'future'].includes(scenario);
    assert.equal(result.status === 0, success, scenario + ': ' + result.stderr);
    assert.equal(fs.readFileSync(path.join(root, 'unrelated.apk'), 'utf8'), 'keep');
    assert(!fs.readdirSync(root).some(name => name.startsWith('work.')), scenario + ': leaked temp directory');
    if (scenario !== 'new') assert.equal(fs.readFileSync(path.join(root, 'config'), 'utf8'), 'network lan\nmac 02:00:00:00:00:0a');
    const order = fs.existsSync(path.join(root, 'order')) ? fs.readFileSync(path.join(root, 'order'), 'utf8').trim().split('\n') : [];
    assert.equal(order.includes('install'), success || ['install', 'inactive'].includes(scenario));
    if (success) {
      assert.deepEqual(order, ['extract', 'check', 'simulate', 'install', 'status']);
      assert.equal(fs.readFileSync(path.join(root, 'program'), 'utf8'), '1.0.1-r1');
    }
    if (scenario === 'repeat') {
      fs.writeFileSync(path.join(root, 'program'), 'damaged again');
      assert.equal(run().status, 0);
      assert.equal(fs.readFileSync(path.join(root, 'program'), 'utf8'), '1.0.1-r1');
      assert.equal(fs.readFileSync(path.join(root, 'config'), 'utf8'), 'network lan\nmac 02:00:00:00:00:0a');
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}
console.log('PASS: installer compatibility, exact assets/checksums, failed downloads/installs, upgrades, repeat installs and isolated cleanup');
