#!/usr/bin/env python3
"""Real packet tests. Run via network.sh in private mount/network namespaces."""
import json
import pathlib
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = ['p6r', 'p6ap', 'p6a', 'p6b', 'p6c', 'p6w']
WHITE = '02:00:00:00:00:0a'
BLACK = '02:00:00:00:00:0b'
CONTEXT = {'bridge': 'br-lan', 'ports': ['la', 'lc'], 'devices': ['br-lan', 'la', 'lc']}
HELPER = '/usr/libexec/passipv6-ra'
GENERATION = 0


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
    global GENERATION
    GENERATION += 1
    snapshot = json.dumps({'bridge': 'br-lan', 'mac': sorted(macs), 'generation': GENERATION})
    pathlib.Path('/var/run/passipv6/ra-candidate.json').write_text(snapshot)
    run([HELPER, 'prepare'], 'p6r')
    rendered = run(['sh', str(ROOT / 'tests/ucode.sh'), str(ROOT / 'tests/render.uc'),
                    json.dumps({'network': 'lan', 'mac': macs}), json.dumps(CONTEXT)]).stdout
    run(['nft', '-c', '-f', '-'], 'p6r', input=rendered)
    nft(rendered)
    pathlib.Path('/var/run/passipv6/ra-active.json').write_text(snapshot)
    run([HELPER, 'commit'], 'p6r')
    assert json.loads(run([HELPER, 'status'], 'p6r').stdout)['ready']


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


def connect(router_port, ns, address4, address6, mac=None, router_ns='p6r'):
    run(['ip', 'link', 'add', router_port, 'type', 'veth', 'peer', 'name', router_port + 'p'])
    run(['ip', 'link', 'set', router_port, 'netns', router_ns])
    run(['ip', 'link', 'set', router_port + 'p', 'netns', ns])
    run(['ip', 'link', 'set', router_port + 'p', 'name', 'eth0'], ns)
    if mac:
        run(['ip', 'link', 'set', 'eth0', 'address', mac], ns)
    run(['ip', 'link', 'set', 'eth0', 'up'], ns)
    run(['ip', 'addr', 'add', address4, 'dev', 'eth0'], ns)
    run(['ip', '-6', 'addr', 'add', address6, 'dev', 'eth0', 'nodad'], ns)
    run(['ip', 'link', 'set', router_port, 'up'], router_ns)


def router_advertisements():
    send = '''import socket,struct
idx=socket.if_nametoindex('br-lan')
s=socket.socket(socket.AF_INET6,socket.SOCK_RAW,socket.IPPROTO_ICMPV6)
s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_IF,idx)
s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_HOPS,255)
ra=struct.pack('!BBHBBHII',134,0,0,64,0,12,0,0)
ra+=struct.pack('!BBBBIII16s',3,4,64,192,90,60,0,socket.inet_pton(socket.AF_INET6,'fd44::'))
ra+=struct.pack('!BBHI16s',25,3,0,12,socket.inet_pton(socket.AF_INET6,'fd42::1'))
s.sendto(ra,('ff02::1',0,0,idx))
'''
    receive = '''import socket,time,json
s=socket.socket(socket.AF_INET6,socket.SOCK_RAW,socket.IPPROTO_ICMPV6)
s.settimeout(.1); print('READY',flush=True)
end=time.monotonic()+2; frames=[]
while time.monotonic()<end:
 try:
  data,peer=s.recvfrom(4096)
  if data[0]==134: frames.append(data.hex())
 except TimeoutError: pass
print(json.dumps(frames),flush=True)
'''

    def observe():
        readers = [subprocess.Popen(['ip', 'netns', 'exec', ns, 'python3', '-c', receive],
                   text=True, stdout=subprocess.PIPE) for ns in ['p6a', 'p6b']]
        try:
            for reader in readers:
                assert reader.stdout.readline().strip() == 'READY'
            run(['python3', '-c', send], 'p6r')
            return [json.loads(reader.communicate(timeout=5)[0]) for reader in readers]
        finally:
            for reader in readers:
                if reader.poll() is None:
                    reader.terminate()
                reader.wait(timeout=5)

    def ra_default(ns):
        return any(r.get('dst') == 'default' and r.get('protocol') == 'ra'
                   for r in json.loads(run(['ip', '-6', '-j', 'route'], ns).stdout))

    policy([WHITE])
    allowed, denied = observe()
    assert len(allowed) == 1 and denied == [], (allowed, denied)
    frame = bytes.fromhex(allowed[0])
    assert frame[16:20] == bytes([3, 4, 64, 192]) and frame[48:50] == bytes([25, 3])
    assert int.from_bytes(frame[52:56], 'big') == 12, 'RDNSS lifetime must remain unchanged'
    assert ra_default('p6a') and not ra_default('p6b')
    for _ in range(6):
        time.sleep(4)
        run(['python3', '-c', send], 'p6r')
        assert ra_default('p6a') and not ra_default('p6b')
    print('PASS: one shared AP uplink delivers RA/PIO/RDNSS only to the allowlist; route renewal survives two lifetimes', flush=True)

    # Even a stale helper snapshot must not bypass the kernel destination filter.
    stale = {'bridge': 'br-lan', 'mac': [WHITE, BLACK], 'generation': 999}
    pathlib.Path('/var/run/passipv6/ra-candidate.json').write_text(json.dumps(stale))
    run([HELPER, 'prepare'], 'p6r')
    run([HELPER, 'commit'], 'p6r')
    allowed, denied = observe()
    assert len(allowed) == 1 and denied == []
    print('PASS: bridge egress blocks a stale helper from advertising IPv6 to a removed MAC', flush=True)

    policy([])
    run(['ip', 'link', 'set', 'eth0', 'down'], 'p6a')
    run(['ip', 'link', 'set', 'eth0', 'up'], 'p6a')
    time.sleep(1.2)
    allowed, denied = observe()
    assert allowed == denied == []
    assert not ra_default('p6a') and not ra_default('p6b')
    print('PASS: empty allowlist and reconnect leave clients without advertised IPv6 routes or DNS', flush=True)


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


def lan_communication():
    policy([WHITE])
    addresses = {}
    for ns, suffix in [('p6b', '11'), ('p6c', '12')]:
        run(['ip', '-6', 'addr', 'add', f'2001:db8:42::{suffix}/64', 'dev', 'eth0'], ns)
        addresses[ns] = next(a['local'] for link in json.loads(
            run(['ip', '-6', '-j', 'addr', 'show', 'dev', 'eth0'], ns).stdout)
            for a in link['addr_info'] if a['scope'] == 'link')
    time.sleep(2)
    for ns in ['p6b', 'p6c']:
        assert not any(a.get('tentative') or a.get('dadfailed') for link in json.loads(
            run(['ip', '-6', '-j', 'addr', 'show', 'dev', 'eth0'], ns).stdout)
            for a in link['addr_info']), 'DAD must work after IPv6 routing is denied'
        run(['ip', '-6', 'neigh', 'flush', 'dev', 'eth0'], ns)
    for address in ['192.0.2.11', 'fd42::11', '2001:db8:42::11', addresses['p6b'] + '%eth0']:
        ping('p6c', address)
    ping('p6b', 'fd42::12')
    ping('p6b', 'fd43::2', False)
    ping('p6c', 'fd43::2', False)

    peer = '''import socket,struct,sys,time
role,family,group,port,multicast=sys.argv[1:]; family=int(family); port=int(port)
af=socket.AF_INET if family==4 else socket.AF_INET6
s=socket.socket(af,socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.settimeout(4);s.bind(('0.0.0.0' if family==4 else '::',port))
idx=socket.if_nametoindex('eth0')
if family==4:
 local='192.0.2.12' if role=='server' else '192.0.2.11'
 s.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton(group)+socket.inet_aton(local))
 s.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(local))
 s.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,255)
 destination=(group,port)
else:
 s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_JOIN_GROUP,socket.inet_pton(af,group)+struct.pack('@I',idx))
 s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_IF,idx)
 s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_HOPS,255)
 destination=(group,port,0,idx)
query=b'passipv6-discovery-query'; reply=b'passipv6-discovery-reply'
print('READY',flush=True)
if role=='client':
 time.sleep(.5)
 s.sendto(query,destination)
deadline=time.monotonic()+4
while time.monotonic()<deadline:
 data,source=s.recvfrom(4096)
 if role=='server' and data==query:
  s.sendto(reply,destination if multicast=='1' else source);time.sleep(.2);break
 if role=='client' and data==reply:break
else:raise AssertionError('No discovery exchange')
'''
    groups = [(5353, '224.0.0.251', 'ff02::fb'), (1900, '239.255.255.250', 'ff02::c'),
              (5355, '224.0.0.252', 'ff02::1:3'), (319, '224.0.1.129', 'ff02::181'),
              (320, '224.0.1.129', 'ff02::181')]
    for snooping in ['0', '1']:
        run(['ip', 'link', 'set', 'br-lan', 'type', 'bridge', 'mcast_snooping', snooping,
             'mcast_querier', snooping], 'p6r')
        run(['ip', 'link', 'set', 'br-ap', 'type', 'bridge', 'mcast_snooping', snooping,
             'mcast_querier', snooping], 'p6ap')
        for port, group4, group6 in groups:
            for family, group in [(4, group4), (6, group6)]:
                for multicast in ['0', '1']:
                    args = [str(family), group, str(port), multicast]
                    server = subprocess.Popen(['ip', 'netns', 'exec', 'p6c', 'python3', '-c', peer,
                                               'server', *args], text=True, stdout=subprocess.PIPE)
                    try:
                        assert server.stdout.readline().strip() == 'READY'
                        run(['python3', '-c', peer, 'client', *args], 'p6b')
                        assert server.wait(timeout=5) == 0
                    finally:
                        if server.poll() is None:
                            server.terminate()
                        server.wait(timeout=5)
        print(f'PASS: discovery transport matrix with multicast snooping={snooping}', flush=True)
    stream = '''import socket,sys
role,family=sys.argv[1:]; family=int(family)
s=socket.socket(socket.AF_INET if family==4 else socket.AF_INET6,socket.SOCK_STREAM)
s.settimeout(4)
if role=='server':
 s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 s.bind(('192.0.2.12' if family==4 else 'fd42::12',45682));s.listen()
 print('READY',flush=True);s,_=s.accept();s.settimeout(4)
 assert s.recv(1024)==b'control';s.sendall(b'audio')
else:
 s.connect(('192.0.2.12' if family==4 else 'fd42::12',45682))
 s.sendall(b'control');assert s.recv(1024)==b'audio'
'''
    for family in ['4', '6']:
        server = subprocess.Popen(['ip', 'netns', 'exec', 'p6c', 'python3', '-c', stream,
                                   'server', family], text=True, stdout=subprocess.PIPE)
        try:
            assert server.stdout.readline().strip() == 'READY'
            run(['python3', '-c', stream, 'client', family], 'p6b')
            assert server.wait(timeout=5) == 0
        finally:
            if server.poll() is None:
                server.terminate()
            server.wait(timeout=5)
    # Replies must survive even when neither endpoint has routing permission.
    policy([])
    ping('p6c', 'fd42::11')
    ping('p6c', 'fd43::2', False)
    print('PASS: separate LAN bridge ports preserve IPv4/IPv6 discovery transports, unicast replies, TCP, fresh NDP/DAD and multicast joins with snooping on/off; routing stays denied', flush=True)


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
        run(['ip', 'link', 'add', 'br-ap', 'type', 'bridge'], 'p6ap')
        run(['ip', 'link', 'set', 'br-ap', 'up'], 'p6ap')
        run(['ip', 'link', 'add', 'la', 'type', 'veth', 'peer', 'name', 'ap-up'], 'p6r')
        run(['ip', 'link', 'set', 'ap-up', 'netns', 'p6ap'], 'p6r')
        run(['ip', 'link', 'set', 'la', 'up'], 'p6r')
        run(['ip', 'link', 'set', 'ap-up', 'up'], 'p6ap')
        connect('ap-a', 'p6a', '192.0.2.10/24', 'fd42::10/64', WHITE, 'p6ap')
        connect('ap-b', 'p6b', '192.0.2.11/24', 'fd42::11/64', BLACK, 'p6ap')
        connect('lc', 'p6c', '192.0.2.12/24', 'fd42::12/64', '02:00:00:00:00:0c')
        connect('wan', 'p6w', '198.51.100.2/24', 'fd43::2/64')
        for port in ['ap-up', 'ap-a', 'ap-b']:
            run(['ip', 'link', 'set', port, 'master', 'br-ap'], 'p6ap')
        for port in ['la', 'lc']:
            run(['ip', 'link', 'set', port, 'master', 'br-lan'], 'p6r')
        run(['ip', 'addr', 'add', '198.51.100.1/24', 'dev', 'wan'], 'p6r')
        run(['ip', '-6', 'addr', 'add', 'fd43::1/64', 'dev', 'wan', 'nodad'], 'p6r')
        for ns in ['p6a', 'p6b', 'p6c']:
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
        processes.append(subprocess.Popen(['ip', 'netns', 'exec', 'p6r', HELPER, 'daemon']))
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
            router_advertisements()
            lan_communication()
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
