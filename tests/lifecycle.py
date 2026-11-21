#!/usr/bin/env python3
"""Run ONLY inside the disposable ImmortalWrt VM after installing the package."""
import json
import os
import pathlib
import signal
import subprocess
import time


def run(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True)
    if check and result.returncode:
        raise AssertionError(f'{args}: {result.stderr} {result.stdout}')
    return result


def status():
    return json.loads(run('ubus', 'call', 'luci.passipv6', 'status').stdout)


def rules():
    return '\n'.join(run('nft', '-s', 'list', 'table', family, 'passipv6').stdout for family in ['inet', 'bridge'])


def helper_pid():
    for p in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
        try:
            if p.read_bytes().split(b'\0')[:2] == [b'/usr/libexec/passipv6-ra', b'daemon']:
                return int(p.parent.name)
        except FileNotFoundError:
            pass
    return None


def wait_applied():
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if status()['applied']:
            return
        time.sleep(.2)
    raise AssertionError('The service did not recover')


assert os.environ.get('PASSIPV6_TEST_VM') == '1', 'Explicit disposable VM opt-in is required'
assert run('uci', '-q', 'get', 'system.@system[0].hostname').stdout.strip() == 'ImmortalWrt', 'Use the test VM only'
assert status()['applied']
assert status()['ra_ready']
before = rules()
run('uci', 'set', 'passipv6.main.mac=invalid')
run('uci', 'commit', 'passipv6')
result = run('/usr/libexec/passipv6', 'reload', check=False)
assert result.returncode != 0
assert rules() == before
assert status()['error']
run('uci', 'set', 'passipv6.main.mac=52:55:c0:a8:01:02')
run('uci', 'commit', 'passipv6')
assert json.loads(run('ubus', 'call', 'luci.passipv6', 'apply').stdout)['success']
assert status()['applied']
print('PASS: invalid configuration retains policy and a no-delta retry recovers', flush=True)
for action in ['reload', 'restart']:
    before = rules()
    run('/etc/init.d/firewall', action)
    assert status()['applied']
    assert rules() == before
    print(f'PASS: firewall {action} preserves the allowlist', flush=True)
processes = [subprocess.Popen(['/usr/libexec/passipv6', 'reload']) for _ in range(3)]
assert all(p.wait(timeout=15) == 0 for p in processes)
assert status()['applied']
assert rules() == before
assert json.loads(run('ubus', 'call', 'luci.passipv6', 'devices').stdout)['devices']
print('PASS: concurrent reloads, RPC device enumeration and policy consistency', flush=True)

checkpoint = pathlib.Path('/etc/passipv6/last-good.json').read_bytes()
snapshot = pathlib.Path('/var/run/passipv6/ra-active.json').read_bytes()
helper = pathlib.Path('/usr/libexec/passipv6-ra')
real = helper.with_suffix('.real')
helper.rename(real)
try:
    helper.write_text('#!/bin/sh\n[ "$1" != commit ] || exit 1\nexec /usr/libexec/passipv6-ra.real "$@"\n')
    helper.chmod(0o755)
    run('uci', 'add_list', 'passipv6.main.mac=02:00:00:00:00:0c')
    run('uci', 'commit', 'passipv6')
    assert run('/usr/libexec/passipv6', 'reload', check=False).returncode != 0
    assert rules() == before
    assert pathlib.Path('/etc/passipv6/last-good.json').read_bytes() == checkpoint
    assert pathlib.Path('/var/run/passipv6/ra-active.json').read_bytes() == snapshot
    assert status()['ra_ready'] and not status()['applied']
finally:
    helper.unlink()
    real.rename(helper)
    run('uci', 'set', 'passipv6.main.mac=52:55:c0:a8:01:02')
    run('uci', 'commit', 'passipv6')
run('/usr/libexec/passipv6', 'reload')
assert status()['applied']
print('PASS: failed helper commit restores both tables, active RA snapshot and last-good configuration', flush=True)

table = json.loads(run('nft', '-j', 'list', 'table', 'bridge', 'passipv6').stdout)
guard = next(e['rule'] for e in table['nftables'] if e.get('rule', {}).get('comment') == 'passipv6-ra-guard')
run('nft', 'replace', 'rule', 'bridge', 'passipv6', 'lan_postrouting', 'handle', str(guard['handle']),
    'counter', 'accept', 'comment', '"passipv6-ra-guard"')
assert not status()['active'], 'A rule count and comment are not proof of an active RA guard'
run('/usr/libexec/passipv6', 'reload')
assert status()['applied']
print('PASS: status detects a replaced multicast guard even with unchanged rule count', flush=True)

daemon = helper_pid()
assert daemon
os.kill(daemon, signal.SIGSTOP)
try:
    assert not status()['ra_ready'] and not status()['applied']
    assert rules() == before
finally:
    os.kill(daemon, signal.SIGKILL)
wait_applied()
assert rules() == before
print('PASS: helper failure keeps filtering enforced, reports failure and recovers through procd', flush=True)

wrapper = pathlib.Path('/usr/share/passipv6/daemon.sh')
original = wrapper.read_bytes()
previous_pid = helper_pid()
try:
    wrapper.write_bytes(original + b'\n# changed package file\n')
    run('/etc/init.d/passipv6', 'start')
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if helper_pid() not in [None, previous_pid] and status()['applied']:
            break
        time.sleep(.2)
    else:
        raise AssertionError('Changed program files did not replace the running helper')
finally:
    wrapper.write_bytes(original)
    run('/etc/init.d/passipv6', 'start')
wait_applied()
assert rules() == before
print('PASS: package file changes replace the helper without removing the policy', flush=True)
