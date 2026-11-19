'use strict';

import * as fs from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';

const runDir = '/var/run/passipv6';
const checkpoint = '/etc/passipv6/last-good.json';

function normalizeMac(value) {
	if (type(value) != 'string' || !match(value, /^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$/))
		die('Invalid MAC address');
	let mac = lc(value);
	if (mac == '00:00:00:00:00:00' || (int(substr(mac, 0, 2), 16) & 1))
		die('A unicast device MAC address is required');
	return mac;
}

function normalizeConfig(value) {
	if (type(value) != 'object' || type(value.network) != 'string' ||
	    !match(value.network, /^[a-zA-Z0-9_]{1,32}$/))
		die('Invalid managed network');
	let macs = value.mac ?? [];
	if (type(macs) == 'string') macs = [macs];
	if (type(macs) != 'array' || length(macs) > 4096)
		die('Invalid MAC allowlist');
	let unique = {};
	for (let mac in macs) unique[normalizeMac(mac)] = true;
	return { network: value.network, mac: sort(keys(unique)) };
}

function readConfig() {
	let uci = cursor();
	return normalizeConfig({
		network: uci.get('passipv6', 'main', 'network'),
		mac: uci.get('passipv6', 'main', 'mac')
	});
}

function readJSON(path) {
	let content = fs.readfile(path);
	if (content == null) return null;
	try { return json(content); } catch (e) { return null; }
}

function command(commandLine) {
	let pipe = fs.popen(commandLine, 'r');
	if (!pipe) die('Unable to execute system command');
	let output = pipe.read('all');
	let code = pipe.close();
	if (code != 0) die('System command failed');
	return output;
}

function safeInterface(name) {
	if (type(name) != 'string' || !match(name, /^[a-zA-Z0-9_.:-]{1,15}$/))
		die('Invalid network device');
	return name;
}

function checkOffload(context, ruleset, hardware) {
	if (hardware == '1') die('Hardware flow offload is not supported');
	for (let entry in ruleset.nftables ?? []) {
		let ft = entry.flowtable;
		if (!ft) continue;
		let devices = ft.dev ?? ft.devices ?? [];
		if (type(devices) == 'string') devices = [devices];
		if (length(filter(context.ports, port => index(devices, port) >= 0)))
			die('Direct flow offload on LAN bridge ports is not supported');
		if (index(devices, context.bridge) >= 0 &&
		    (index(ft.flags ?? [], 'offload') >= 0 || (ft.prio ?? 0) <= -500))
			die('The LAN flowtable bypasses the supported filtering path');
	}
}

function context(config) {
	let uci = cursor();
	let bridge = safeInterface(uci.get('network', config.network, 'device'));
	let definition;
	uci.foreach('network', 'device', section => {
		if (section.name == bridge && section.type == 'bridge') definition = section;
	});
	if (!definition) die('The managed network must use a configured Linux bridge');
	let ports = {};
	let configured = definition.ports ?? [];
	if (type(configured) == 'string') configured = [configured];
	for (let port in [...configured, ...(fs.lsdir(`/sys/class/net/${bridge}/brif`) ?? [])])
		ports[safeInterface(port)] = true;
	let result = { bridge, ports: sort(keys(ports)) };
	result.devices = filter([bridge, ...result.ports], device => fs.stat(`/sys/class/net/${device}`) != null);
	checkOffload(result, json(command('/usr/sbin/nft -j list flowtables 2>/dev/null')),
		uci.get('firewall', '@defaults[0]', 'flow_offloading_hw'));
	return result;
}

function elements(values, quoted) {
	if (!length(values)) return '';
	return 'elements = { ' + join(', ', map(values, value => quoted ? sprintf('"%s"', value) : value)) + ' };';
}

function renderRules(config, ctx) {
	config = normalizeConfig(config);
	let bridge = safeInterface(ctx.bridge);
	let ports = map(ctx.ports, safeInterface);
	let devices = map(ctx.devices, safeInterface);
	let allow = `set allowed_macs { type ether_addr; ${elements(config.mac, false)} }`;
	let ingress = length(devices) ? `
    chain lan_ingress {
        type filter hook ingress devices = { ${join(', ', map(devices, d => sprintf('"%s"', d)))} } priority -500; policy accept;
        meta nfproto ipv6 ether saddr != @allowed_macs counter drop
    }` : '';
	return `destroy table inet passipv6
destroy table bridge passipv6
table inet passipv6 {
    ${allow}
    ${ingress}
    chain lan_prerouting {
        type filter hook prerouting priority -310; policy accept;
        iifname "${bridge}" meta nfproto ipv6 ether saddr != @allowed_macs counter drop
    }
}
table bridge passipv6 {
    ${allow}
    set lan_ports { type ifname; ${elements(ports, true)} }
    chain lan_prerouting {
        type filter hook prerouting priority -310; policy accept;
        iifname @lan_ports ether type ip6 ether saddr != @allowed_macs counter drop
    }
    chain lan_postrouting {
        type filter hook postrouting priority 310; policy accept;
        oifname @lan_ports ether type ip6 ether daddr & 01:00:00:00:00:00 == 00:00:00:00:00:00 ether daddr != @allowed_macs counter drop
    }
}
`;
}

function writeAtomic(path, data) {
	let file = fs.open(path + '.new', 'w', 0600);
	if (!file) die('Unable to write state');
	let size = file.write(data);
	file.close();
	if (size != length(data) || !fs.rename(path + '.new', path))
		die('Unable to persist state');
}

function check() {
	let config = fs.stat('/etc/config/passipv6') ? readConfig() : { network: 'lan', mac: [] };
	let ctx = context(config);
	if (index(ctx.devices, ctx.bridge) < 0 || !length(ctx.ports))
		die('The managed LAN bridge must be available');
	let pipe = fs.popen('/usr/sbin/nft --check --file -', 'w');
	if (!pipe) die('Unable to check nftables support');
	let rules = renderRules(config, ctx);
	let written = pipe.write(rules);
	let code = pipe.close();
	if (written != length(rules) || code != 0)
		die('The kernel or nftables does not support the required IPv6 filtering rules');
	return true;
}

function nftApply(text) {
	writeAtomic(runDir + '/candidate.nft', text);
	for (let mode in ['--check ', '']) {
		if (system(`/usr/sbin/nft ${mode}--file ${runDir}/candidate.nft >${runDir}/nft-error 2>&1`) != 0)
			die('nftables rejected the policy: ' + (fs.readfile(runDir + '/nft-error') ?? 'unknown error'));
	}
}

function ownTable(family) {
	try { return json(command(`/usr/sbin/nft -j list table ${family} passipv6 2>/dev/null`)); }
	catch (e) { return null; }
}

function tableMacs(table) {
	for (let entry in table?.nftables ?? [])
		if (entry.set?.name == 'allowed_macs') return sort(entry.set.elem ?? []);
	return null;
}

function same(a, b) { return sprintf('%J', a) == sprintf('%J', b); }

function reload() {
	fs.mkdir(runDir, 0700);
	fs.mkdir('/etc/passipv6', 0700);
	let previous = readJSON(checkpoint);
	let config, ctx, failure;
	try {
		config = readConfig();
		ctx = context(config);
	} catch (e) {
		failure = e.message;
		if (ownTable('inet') && ownTable('bridge')) {
			writeAtomic(runDir + '/status.json', sprintf('%J', { error: failure }));
			die(failure);
		}
		config = normalizeConfig(previous ?? { network: 'lan', mac: [] });
		ctx = context(config);
	}
	try {
		// Prepare durable recovery data before changing packet filtering.
		let changed = !same(previous, config);
		if (changed) writeAtomic(checkpoint + '.pending', sprintf('%J', config));
		nftApply(renderRules(config, ctx));
		if (changed && !fs.rename(checkpoint + '.pending', checkpoint))
			die('Policy is active but recovery state could not be committed');
		writeAtomic(runDir + '/status.json', sprintf('%J', {
			error: failure ?? null, applied_at: time(), context: ctx
		}));
	} catch (e) {
		writeAtomic(runDir + '/status.json', sprintf('%J', { error: e.message }));
		die(e.message);
	}
	if (failure) die(failure);
	return true;
}

function remove() {
	fs.mkdir(runDir, 0700);
	nftApply('destroy table inet passipv6\ndestroy table bridge passipv6\n');
	let uci = cursor();
	if (uci.get('firewall', 'passipv6', 'path') == '/usr/share/passipv6/firewall.include') {
		uci.delete('firewall', 'passipv6');
		if (!uci.commit('firewall')) die('Unable to remove firewall integration');
	}
	fs.unlink(runDir + '/status.json');
}

function status() {
	let state = readJSON(runDir + '/status.json') ?? {};
	let last = readJSON(checkpoint);
	let inet = ownTable('inet'), bridge = ownTable('bridge');
	let imac = tableMacs(inet), bmac = tableMacs(bridge);
	let config, ctx, error = state.error;
	try { config = readConfig(); ctx = context(config); }
	catch (e) { error = e.message; }
	let chainCount = table => length(filter(table?.nftables ?? [], entry => entry.chain != null));
	let ruleCount = table => length(filter(table?.nftables ?? [], entry => entry.rule != null));
	let live = ctx && index(ctx.devices, ctx.bridge) >= 0;
	let active = live && chainCount(inet) == 2 && ruleCount(inet) == 2 &&
		chainCount(bridge) == 2 && ruleCount(bridge) == 2 &&
		imac != null && same(imac, bmac) && same(imac, last?.mac);
	return {
		active: !!active,
		applied: !!(active && !error && same(config, last) && same(ctx, state.context)),
		mac: imac ?? [], network: config?.network ?? last?.network ?? 'lan',
		error: error ?? null, applied_at: state.applied_at ?? null
	};
}

function mergeDevices(hints, leases, neighbors, fdb, allowed, ownMacs) {
	let hosts = {};
	function add(mac, source) {
		try { mac = normalizeMac(mac); } catch (e) { return null; }
		if (index(ownMacs, mac) >= 0) return null;
		let row = hosts[mac] ??= { mac, name: '', ipv4: [], ipv6: [], seen: false };
		if (source) row.seen = true;
		return row;
	}
	for (let mac in allowed) add(mac, false);
	for (let mac in fdb) add(mac, true);
	for (let entry in neighbors) {
		if (index(entry.state ?? [], 'FAILED') >= 0 || index(entry.state ?? [], 'INCOMPLETE') >= 0) continue;
		let row = add(entry.lladdr, true);
		if (!row || type(entry.dst) != 'string') continue;
		push(index(entry.dst, ':') >= 0 ? row.ipv6 : row.ipv4, entry.dst);
	}
	for (let lease in leases) {
		let row = add(lease.macaddr, false);
		if (!row) continue;
		if (lease.hostname) row.name = lease.hostname;
		if (lease.ipaddr) push(row.ipv4, lease.ipaddr);
	}
	for (let mac, hint in hints) {
		let row;
		try { row = hosts[normalizeMac(mac)]; } catch (e) { continue; }
		if (!row) continue;
		row.name = hint.name ?? row.name;
	}
	for (let mac, row in hosts) {
		for (let family in ['ipv4', 'ipv6']) {
			let ips = {};
			for (let ip in row[family]) ips[ip] = true;
			row[family] = sort(keys(ips));
		}
	}
	return map(sort(keys(hosts)), mac => hosts[mac]);
}

function parseLeases(content, now) {
	let leases = [];
	for (let line in split(content, '\n')) {
		let fields = split(trim(line), /\s+/);
		if (length(fields) < 4 || !match(fields[0], /^[0-9]+$/)) continue;
		let expires = int(fields[0]);
		if (expires != 0 && expires <= now) continue;
		push(leases, { macaddr: fields[1], ipaddr: fields[2], hostname: fields[3] == '*' ? '' : fields[3] });
	}
	return leases;
}

function devices() {
	let config = readConfig(), ctx = context(config);
	let uci = cursor(), hints = {}, leases = [], leasefiles = {};
	uci.foreach('dhcp', 'dnsmasq', section => {
		leasefiles[section.leasefile ?? '/tmp/dhcp.leases'] = true;
	});
	for (let path in keys(leasefiles))
		push(leases, ...parseLeases(fs.readfile(path) ?? '', time()));
	uci.foreach('dhcp', 'host', section => {
		let macs = section.mac ?? [];
		if (type(macs) == 'string') macs = [macs];
		for (let mac in macs) hints[mac] = { name: section.name };
	});
	let bus = connect();
	if (!bus) die('Unable to query connected devices');
	// Calling another rpcd object synchronously here would deadlock rpcd's event loop.
	let info = bus.call('network.interface', 'dump', {});
	bus.disconnect();
	let neighbors = json(command(`/sbin/ip -j neigh show dev '${ctx.bridge}'`));
	let macs = [], own = [];
	// Linux bridge FDB records are fixed 16-byte structures; no extra bridge tool is required.
	let fdb = fs.readfile(`/sys/class/net/${ctx.bridge}/brforward`) ?? '';
	for (let offset = 0; offset + 16 <= length(fdb); offset += 16) {
		if (ord(fdb, offset + 7)) continue;
		let parts = [];
		for (let i = 0; i < 6; i++) push(parts, sprintf('%02x', ord(fdb, offset + i)));
		push(macs, join(':', parts));
	}
	for (let device in [ctx.bridge, ...ctx.ports]) {
		let address = fs.readfile(`/sys/class/net/${device}/address`);
		if (address) push(own, lc(trim(address)));
	}
	let addresses = [];
	for (let iface in info?.interface ?? [])
		if (iface.interface == config.network) addresses = iface['ipv4-address'] ?? [];
	function ipv4num(ip) {
		let parts = split(ip ?? '', '.');
		if (length(parts) != 4) return -1;
		return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3]);
	}
	leases = filter(leases, lease => length(filter(addresses, addr => {
		let mask = addr.mask ? (0xffffffff << (32 - addr.mask)) & 0xffffffff : 0;
		return (ipv4num(lease.ipaddr) & mask) == (ipv4num(addr.address) & mask);
	})) > 0);
	return { devices: mergeDevices(hints, leases, neighbors, macs, config.mac, own) };
}

export { normalizeMac, normalizeConfig, checkOffload, renderRules, check, reload, remove, status, mergeDevices, devices, parseLeases };
