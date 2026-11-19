#!/usr/bin/env python3
"""Real packet tests. Run via network.sh in private mount/network namespaces."""
import json
import pathlib
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = ['p6r', 'p6a', 'p6b', 'p6w']
WHITE = '02:00:00:00:00:0a'
BLACK = '02:00:00:00:00:0b'
CONTEXT = {'bridge': 'br-lan', 'ports': ['la', 'lb'], 'devices': ['br-lan', 'la', 'lb']}


def run(args, ns=None, check=True, **kwargs):
    if ns:
        args = ['ip', 'netns', 'exec', ns, *args]
    result = subprocess.run(args, text=True, capture_output=True, **kwargs)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stderr}\n{result.stdout}')
    return result


def nft(text):
    run(['nft', '-f', '-'], 'p6r', input=text)


def policy(macs):
    rendered = run(['sh', str(ROOT / 'tests/ucode.sh'), str(ROOT / 'tests/render.uc'),
                    json.dumps({'network': 'lan', 'mac': macs}), json.dumps(CONTEXT)]).stdout
    run(['nft', '-c', '-f', '-'], 'p6r', input=rendered)
    nft(rendered)


def ping(ns, address, success=True):
    result = run(['ping', '-n', '-c', '1', '-W', '2', address], ns, check=False)
    assert (result.returncode == 0) == success, (ns, address, result.stdout, result.stderr)


def wait_for_traffic(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and int(path.read_text() or '0') > 10:
            return
        time.sleep(.1)
    raise AssertionError('The test stream did not become ready')


def connect(router_port, ns, address4, address6, mac=None):
    run(['ip', 'link', 'add', router_port, 'type', 'veth', 'peer', 'name', router_port + 'p'])
    run(['ip', 'link', 'set', router_port, 'netns', 'p6r'])
    run(['ip', 'link', 'set', router_port + 'p', 'netns', ns])
    run(['ip', 'link', 'set', router_port + 'p', 'name', 'eth0'], ns)
    if mac:
        run(['ip', 'link', 'set', 'eth0', 'address', mac], ns)
    run(['ip', 'link', 'set', 'eth0', 'up'], ns)
    run(['ip', 'addr', 'add', address4, 'dev', 'eth0'], ns)
    run(['ip', '-6', 'addr', 'add', address6, 'dev', 'eth0', 'nodad'], ns)
    run(['ip', 'link', 'set', router_port, 'up'], 'p6r')


def dhcpv6(tmp, processes):
    processes.append(subprocess.Popen(['ip', 'netns', 'exec', 'p6r', 'dnsmasq',
        '--no-daemon', '--user=root', '--conf-file=/dev/null', '--port=0',
        '--interface=br-lan', '--bind-interfaces', '--dhcp-range=fd42::100,fd42::1ff,64,1h',
        '--pid-file=' + str(tmp / 'dnsmasq.pid'), '--dhcp-leasefile=' + str(tmp / 'leases')],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(.3)
    client = '''import socket,struct,sys
mac=bytes.fromhex(sys.argv[1].replace(':','')); idx=socket.if_nametoindex('eth0')
s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM); s.bind(('::',546)); s.settimeout(2)
s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_IF,idx)
def option(code,value): return struct.pack('!HH',code,len(value))+value
def options(data):
 result={}; offset=0
 while offset+4<=len(data):
  code,size=struct.unpack('!HH',data[offset:offset+4]); offset+=4
  result[code]=data[offset:offset+size]; offset+=size
 return result
clientid=option(1,b'\\x00\\x03\\x00\\x01'+mac)
ia=struct.pack('!III',123,0,0)
s.sendto(b'\\x01\\xaa\\xbb\\xcc'+clientid+option(3,ia),('ff02::1:2',547,0,idx))
try: advertise,peer=s.recvfrom(4096)
except TimeoutError: print('BLOCKED'); sys.exit(0)
assert advertise[:4]==b'\\x02\\xaa\\xbb\\xcc',advertise
offered=options(advertise[4:])
s.sendto(b'\\x03\\xaa\\xbb\\xcd'+clientid+option(2,offered[2])+option(3,offered[3]),('ff02::1:2',547,0,idx))
reply,peer=s.recvfrom(4096); assert reply[:4]==b'\\x07\\xaa\\xbb\\xcd'
assigned=options(options(reply[4:])[3][12:])[5]
print('LEASE',socket.inet_ntop(socket.AF_INET6,assigned[:16]))
'''
    assert 'LEASE fd42:' in run(['python3', '-c', client, WHITE], 'p6a').stdout
    assert run(['python3', '-c', client, BLACK], 'p6b').stdout.strip() == 'BLOCKED'
    print('PASS: authorized client obtains a DHCPv6 lease; denied client receives no offer', flush=True)


def tcp_stream(tmp, processes):
    policy([WHITE, BLACK])
    server = '''import socket,time
s=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('fd43::2',45680));s.listen();c,peer=s.accept()
for _ in range(1500):
 c.sendall(b'x');time.sleep(.02)
'''
    receiver = '''import socket,time,pathlib,sys
s=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);s.connect(('fd43::2',45680));s.settimeout(.05)
count=0;end=time.monotonic()+40;path=pathlib.Path(sys.argv[1]);temporary=path.with_suffix('.tmp')
while time.monotonic()<end:
 try: count+=len(s.recv(4096))
 except TimeoutError: pass
 try: temporary.write_text(str(count));temporary.replace(path)
 except FileNotFoundError: break
'''
    processes.append(subprocess.Popen(['ip', 'netns', 'exec', 'p6w', 'python3', '-c', server]))
    time.sleep(.15)
    countfile = tmp / 'tcp-count'
    processes.append(subprocess.Popen(['ip', 'netns', 'exec', 'p6b', 'python3', '-c', receiver, str(countfile)]))
    wait_for_traffic(countfile)
    ct = run(['cat', '/proc/net/nf_conntrack'], 'p6r').stdout
    assert any(' tcp ' in line and '[OFFLOAD]' in line for line in ct.splitlines())
    policy([WHITE])
    time.sleep(.3)
    before = int(countfile.read_text())
    time.sleep(.7)
    assert int(countfile.read_text()) == before
    ping('p6a', 'fd43::2')
    ping('p6b', '198.51.100.2')
    print('PASS: existing offloaded TCP stops after revocation; allowed IPv6 and denied-client IPv4 survive', flush=True)


def main():
    processes = []
    try:
        for ns in NAMES:
            run(['ip', 'netns', 'add', ns])
            run(['ip', 'link', 'set', 'lo', 'up'], ns)
        run(['sysctl', '-qw', 'net.ipv4.ip_forward=1', 'net.ipv6.conf.all.forwarding=1'], 'p6r')
        run(['ip', 'link', 'add', 'br-lan', 'type', 'bridge'], 'p6r')
        run(['ip', 'link', 'set', 'br-lan', 'up'], 'p6r')
        run(['ip', 'addr', 'add', '192.0.2.1/24', 'dev', 'br-lan'], 'p6r')
        run(['ip', '-6', 'addr', 'add', 'fd42::1/64', 'dev', 'br-lan', 'nodad'], 'p6r')
        connect('la', 'p6a', '192.0.2.10/24', 'fd42::10/64', WHITE)
        connect('lb', 'p6b', '192.0.2.11/24', 'fd42::11/64', BLACK)
        connect('wan', 'p6w', '198.51.100.2/24', 'fd43::2/64')
        for port in ['la', 'lb']:
            run(['ip', 'link', 'set', port, 'master', 'br-lan'], 'p6r')
        run(['ip', 'addr', 'add', '198.51.100.1/24', 'dev', 'wan'], 'p6r')
        run(['ip', '-6', 'addr', 'add', 'fd43::1/64', 'dev', 'wan', 'nodad'], 'p6r')
        for ns in ['p6a', 'p6b']:
            run(['ip', 'route', 'add', 'default', 'via', '192.0.2.1'], ns)
            run(['ip', '-6', 'route', 'add', 'default', 'via', 'fd42::1'], ns)
        run(['ip', 'route', 'add', '192.0.2.0/24', 'via', '198.51.100.1'], 'p6w')
        run(['ip', '-6', 'route', 'add', 'fd42::/64', 'via', 'fd43::1'], 'p6w')
        nft('''table inet fw4 {
            flowtable ft { hook ingress priority 0; devices = { "br-lan", "wan" }; counter; }
            chain forward { type filter hook forward priority 0; policy accept;
                meta l4proto { tcp, udp } flow add @ft
            }
        }
        table inet passwall {
            chain test { type filter hook prerouting priority -151; policy accept; }
        }
        ''')
        baseline = run(['nft', '-s', 'list', 'table', 'inet', 'fw4'], 'p6r').stdout
        passwall = run(['nft', '-s', 'list', 'table', 'inet', 'passwall'], 'p6r').stdout
        # Let IPv6 multicast memberships and link-local DAD settle on new veth devices.
        time.sleep(2)
        ping('p6w', 'fd43::1')
        policy([WHITE, BLACK])
        for ns in ['p6a', 'p6b']:
            ping(ns, 'fd43::2')
            ping(ns, '198.51.100.2')
        print('PASS: both authorized clients have IPv4 and IPv6', flush=True)

        with tempfile.TemporaryDirectory(prefix='passipv6-network-') as tmp:
            tmp = pathlib.Path(tmp)
            server = '''import socket,time
s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM); s.bind(('fd43::2',45678)); s.settimeout(.02)
peer=None; end=time.monotonic()+45
while time.monotonic()<end:
 try: data,peer=s.recvfrom(100)
 except TimeoutError: pass
 if peer:
  try: s.sendto(b'x',peer)
  except TimeoutError: pass
'''
            receiver = '''import socket,time,pathlib,sys
s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM); s.bind(('fd42::11',45679)); s.settimeout(.02)
count=0; end=time.monotonic()+45; nextsend=0
while time.monotonic()<end:
 if time.monotonic()>nextsend:
  s.sendto(b'x',('fd43::2',45678)); nextsend=time.monotonic()+.1
 try: s.recvfrom(100); count+=1
 except TimeoutError: pass
 path=pathlib.Path(sys.argv[1]); temporary=path.with_suffix('.tmp')
 try: temporary.write_text(str(count)); temporary.replace(path)
 except FileNotFoundError: break
'''
            processes.append(subprocess.Popen(['ip', 'netns', 'exec', 'p6w', 'python3', '-c', server]))
            time.sleep(.15)
            countfile = tmp / 'count'
            processes.append(subprocess.Popen(['ip', 'netns', 'exec', 'p6b', 'python3', '-c', receiver, str(countfile)]))
            wait_for_traffic(countfile)
            conntrack = run(['cat', '/proc/net/nf_conntrack'], 'p6r', check=False)
            assert '[OFFLOAD]' in conntrack.stdout, 'test must exercise real software flow offload'
            policy([WHITE])
            time.sleep(.3)
            count = int(countfile.read_text() or '0')
            time.sleep(.7)
            later = int(countfile.read_text())
            assert later == count, f'offloaded replies survived revocation: {count} -> {later}'
            ping('p6a', 'fd43::2')
            ping('p6b', 'fd43::2', False)
            ping('p6w', 'fd42::11', False)
            for ns in ['p6a', 'p6b']:
                ping(ns, '198.51.100.2')
            print('PASS: revocation stops existing offloaded UDP in both directions; IPv4 remains live', flush=True)

            dhcpv6(tmp, processes)
            tcp_stream(tmp, processes)

            before = run(['nft', '-s', 'list', 'table', 'inet', 'passipv6'], 'p6r').stdout
            bad = run(['nft', '-f', '-'], 'p6r', check=False,
                      input='destroy table inet passipv6\nadd rule inet table_does_not_exist missing drop\n')
            assert bad.returncode != 0
            assert before == run(['nft', '-s', 'list', 'table', 'inet', 'passipv6'], 'p6r').stdout
            print('PASS: failed nft transaction preserves the previous policy', flush=True)

            policy([])
            ping('p6a', 'fd43::2', False)
            ping('p6a', '198.51.100.2')
            policy([WHITE])
            policy([WHITE])
            ping('p6a', 'fd43::2')
            assert baseline == run(['nft', '-s', 'list', 'table', 'inet', 'fw4'], 'p6r').stdout
            assert passwall == run(['nft', '-s', 'list', 'table', 'inet', 'passwall'], 'p6r').stdout
            print('PASS: empty policy, repeat apply and unrelated firewall tables', flush=True)
    except Exception:
        for ns in ['p6a', 'p6r', 'p6w']:
            for command in [['ip', '-6', 'route'], ['ip', '-6', 'neigh'], ['nft', 'list', 'ruleset']]:
                result = run(command, ns, check=False)
                print(ns, command, result.stdout, result.stderr, flush=True)
        raise
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=5)
        for ns in reversed(NAMES):
            run(['ip', 'netns', 'del', ns], check=False)


if __name__ == '__main__':
    main()
