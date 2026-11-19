#!/usr/bin/env python3
"""Run ONLY inside the disposable ImmortalWrt VM after installing the package."""
import json
import subprocess


def run(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True)
    if check and result.returncode:
        raise AssertionError(f'{args}: {result.stderr} {result.stdout}')
    return result


def status():
    return json.loads(run('ubus', 'call', 'luci.passipv6', 'status').stdout)


def rules():
    return '\n'.join(run('nft', '-s', 'list', 'table', family, 'passipv6').stdout for family in ['inet', 'bridge'])


assert run('uci', '-q', 'get', 'system.@system[0].hostname').stdout.strip() == 'ImmortalWrt', 'Use the test VM only'
assert status()['applied']
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
