import * as policy from 'passipv6';

function assert(value, message) { if (!value) die(message); }
function rejects(fn, message) {
	let rejected = false;
	try { fn(); } catch (e) { rejected = true; }
	assert(rejected, message);
}

let normalized = policy.normalizeConfig({ network: 'lan', mac: ['02:AA:00:00:00:01', '02:aa:00:00:00:01'] });
assert(length(normalized.mac) == 1 && normalized.mac[0] == '02:aa:00:00:00:01', 'normalize/deduplicate');
for (let mac in ['00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff', '01:00:5e:00:00:01', '02:00:00:00:00:01\n', '$(id)', null])
	rejects(() => policy.normalizeMac(mac), 'invalid MAC must be rejected');
rejects(() => policy.normalizeConfig({ network: "lan';reboot", mac: [] }), 'network injection');

let ctx = { bridge: 'br-lan', ports: ['eth0'], devices: ['br-lan', 'eth0'] };
let ft = { nftables: [{ flowtable: { dev: ['br-lan', 'wan'], prio: 0 } }] };
policy.checkOffload(ctx, ft, '0');
rejects(() => policy.checkOffload(ctx, ft, '1'), 'hardware offload');
rejects(() => policy.checkOffload(ctx, { nftables: [{ flowtable: { dev: ['eth0'] } }] }, '0'), 'direct bridge offload');
rejects(() => policy.checkOffload(ctx, { nftables: [{ flowtable: { dev: ['br-lan'], prio: -600 } }] }, '0'), 'early flowtable');

let devices = policy.mergeDevices(
	{ '02:AA:00:00:00:01': { name: '<script>bad()</script>' }, '02:00:00:00:00:99': { name: 'WAN' } },
	[{ macaddr: '02:aa:00:00:00:01', ipaddr: '10.0.1.10' }],
	[{ lladdr: '02:aa:00:00:00:01', dst: '2001:db8::10', state: ['STALE'] },
	 { lladdr: '02:00:00:00:00:04', dst: '10.0.1.4', state: ['FAILED'] }],
	['02:00:00:00:00:02', '02:00:00:00:00:fe'],
	['02:00:00:00:00:03'], ['02:00:00:00:00:fe']);
assert(length(devices) == 3, 'union, WAN exclusion, own MAC exclusion, failed neighbor exclusion');
assert(devices[0].mac == '02:00:00:00:00:02' && devices[0].seen, 'FDB-only device');
assert(devices[1].mac == '02:00:00:00:00:03' && !devices[1].seen, 'offline allowlist');
assert(devices[2].name == '<script>bad()</script>' && length(devices[2].ipv6) == 1, 'untrusted name remains text data');

let leases = policy.parseLeases('101 02:00:00:00:00:01 192.0.2.1 phone *\n99 02:00:00:00:00:02 192.0.2.2 old *\n0 02:00:00:00:00:03 192.0.2.3 * *\nmalformed\n', 100);
assert(length(leases) == 2 && leases[1].hostname == '', 'expired, infinite and malformed leases');
print('PASS: MAC validation, offload checks, lease parsing and device merging\n');
