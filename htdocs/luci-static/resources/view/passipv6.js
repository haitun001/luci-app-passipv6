'use strict';
'require view';
'require rpc';
'require uci';
'require ui';
'require poll';

const callDevices = rpc.declare({ object: 'luci.passipv6', method: 'devices', expect: { devices: [] } });
const callStatus = rpc.declare({ object: 'luci.passipv6', method: 'status', expect: { '': {} } });
const callApply = rpc.declare({ object: 'luci.passipv6', method: 'apply', expect: { '': {} } });
const callHints = rpc.declare({ object: 'luci-rpc', method: 'getHostHints', expect: { '': {} } });

function macList(value) {
	return L.toArray(value).map(mac => mac.toLowerCase()).sort();
}

return view.extend({
	load: function() {
		return Promise.all([uci.load('passipv6'), callDevices(), callStatus(), callHints().catch(() => ({}))]);
	},

	render: function(data) {
		this.generation = 0;
		this.storageKey = 'passipv6.apply.' + L.env.sessionid;
		this.saved = macList(uci.get('passipv6', 'main', 'mac'));
		this.selected = new Set(this.saved);
		this.rows = new Map();
		this.lastStatus = data[2];
		this.hints = data[3] || {};
		this.writable = L.hasViewPermission();
		try {
			const pending = JSON.parse(sessionStorage.getItem(this.storageKey));
			if (pending && pending.kind === 'apply' && Number.isFinite(pending.expires) && Array.isArray(pending.target)) {
				pending.target = macList(pending.target);
				this.operation = pending;
				this.armTimeout();
			}
		} catch (e) { /* Browser storage may be unavailable. */ }
		document.addEventListener('uci-applied', L.bind(function() {
			if (!this.operation || this.operation.kind !== 'apply') return;
			this.operation.committed = true;
			this.rememberApply();
			this.refresh();
		}, this));
		document.addEventListener('uci-reverted', L.bind(function() {
			if (this.operation) this.finishOperation(_('Application was cancelled or rolled back.'));
		}, this));
		this.message = E('p', { 'role': 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
		this.error = E('p', { 'role': 'alert', 'aria-atomic': 'true', 'hidden': true });
		this.body = E('tbody');
		this.empty = E('p', {}, _('No devices have been discovered yet.'));
		const table = E('table', { 'class': 'table', 'aria-describedby': 'passipv6-description' }, [
			E('caption', {}, _('LAN devices and IPv6 permissions')),
			E('thead', {}, E('tr', { 'class': 'tr' }, [
				_('Allow IPv6'), _('Device / MAC address'), _('IPv4 addresses'),
				_('IPv6 addresses'), _('Discovery status')
			].map(title => E('th', { 'scope': 'col', 'class': 'th' }, title)))),
			this.body
		]);
		const node = E('div', { 'class': 'passipv6' }, [
			E('style', {}, `
				.passipv6 caption{text-align:start;font-weight:bold;margin-block:1em}
				.passipv6 td,.passipv6 th{overflow-wrap:anywhere;vertical-align:top}
				.passipv6 label{display:inline-flex;align-items:center;gap:.5em;min-height:44px;cursor:pointer}
				.passipv6 input[type=checkbox]{min-width:24px;min-height:24px}
				.passipv6 input:focus-visible{outline:3px solid currentColor;outline-offset:3px}
				.passipv6 .mac{display:block;font-family:monospace}
				.passipv6 [hidden]{display:none!important}
				.passipv6 .device-name{font-weight:normal}
				.passipv6-actions .cbi-button-apply{background:#126078!important;border-color:#126078!important;color:#fff!important}
				.passipv6-actions .cbi-button-reset{background:#b52d29!important;border-color:#b52d29!important;color:#fff!important}
				.passipv6-actions button:focus-visible{outline:2px solid #111;outline-offset:2px;box-shadow:0 0 0 4px #fff}
			`),
			E('h2', {}, 'PassIPV6'),
			E('p', { 'id': 'passipv6-description' }, _('Only selected devices may use IPv6 through this router. IPv4 remains available.')),
			E('p', {}, _('Unselected devices may still display automatically generated IPv6 addresses. These addresses do not grant IPv6 access through this router.')),
			E('p', {}, _('After upgrading or changing IPv6 permissions, reconnect affected devices once to refresh their network settings.')),
			E('p', {}, _('Devices refresh every 5 seconds. Offline allowlist entries are kept.')),
			this.message, this.error, table, this.empty
		]);
		this.updateDevices(data[1]);
		this.updateStatus(data[2]);
		poll.add(L.bind(this.refresh, this), 5);
		return node;
	},

	rememberApply: function() {
		try {
			if (this.operation && this.operation.kind === 'apply')
				sessionStorage.setItem(this.storageKey, JSON.stringify(this.operation));
			else sessionStorage.removeItem(this.storageKey);
		} catch (e) { /* Progress still works without browser storage. */ }
	},

	armTimeout: function() {
		window.clearTimeout(this.operationTimer);
		this.operationTimer = window.setTimeout(L.bind(function() {
			if (this.operation) this.finishOperation(_('The operation result could not be confirmed.'));
		}, this), Math.max(0, this.operation.expires - Date.now()));
	},

	beginOperation: function(kind) {
		this.generation++;
		this.actionError = '';
		this.operation = {
			kind: kind, target: Array.from(this.selected).sort(), committed: false,
			expires: Date.now() + ((L.env.apply_rollback || 90) + (L.env.apply_holdoff || 4) + 10) * 1000
		};
		this.armTimeout();
		this.setBusy(true);
		this.updateStatus(this.lastStatus);
	},

	finishOperation: function(error) {
		this.generation++;
		this.operation = null;
		this.actionError = error || '';
		window.clearTimeout(this.operationTimer);
		if (this.modalObserver) this.modalObserver.disconnect();
		this.rememberApply();
		this.setBusy(false);
		this.updateStatus(this.lastStatus);
	},

	setBusy: function(busy) {
		for (const row of this.rows.values()) row.checkbox.disabled = !this.writable || busy;
		if (this.footer) this.footer.querySelectorAll('button').forEach(button => { button.disabled = !this.writable || busy; });
	},

	updateDevices: function(devices) {
		const found = new Map(devices.map(device => [device.mac.toLowerCase(), device]));
		for (const mac of new Set([...this.saved, ...this.selected, ...this.rows.keys()])) {
			if (!found.has(mac)) found.set(mac, { mac: mac, ipv4: [], ipv6: [], seen: false });
		}
		for (const [mac, device] of Array.from(found.entries()).sort()) {
			let row = this.rows.get(mac);
			if (!row) {
				const id = 'passipv6-' + mac.replace(/:/g, '');
				const checkbox = E('input', {
					'type': 'checkbox', 'id': id, 'disabled': this.writable ? null : true,
					'aria-labelledby': id + '-label ' + id + '-device',
					'change': L.bind(function(ev) {
						this.actionError = '';
						if (ev.target.checked) this.selected.add(mac);
						else this.selected.delete(mac);
						this.updateStatus(this.lastStatus);
					}, this)
				});
				const name = E('span', { 'class': 'device-name' });
				const ips4 = E('td', { 'class': 'td', 'data-title': _('IPv4 addresses') });
				const ips6 = E('td', { 'class': 'td', 'data-title': _('IPv6 addresses') });
				const seen = E('td', { 'class': 'td', 'data-title': _('Discovery status') });
				const tr = E('tr', { 'class': 'tr' }, [
					E('td', { 'class': 'td', 'data-title': _('Allow IPv6') },
						E('label', { 'for': id }, [checkbox, E('span', { 'id': id + '-label' }, _('Allow IPv6'))])),
					E('th', { 'scope': 'row', 'class': 'td', 'id': id + '-device' },
						[name, E('span', { 'class': 'mac' }, mac.toUpperCase())]), ips4, ips6, seen
				]);
				row = { node: tr, checkbox: checkbox, name: name, ips4: ips4, ips6: ips6, seen: seen };
				this.rows.set(mac, row);
				this.body.appendChild(tr);
			}
			row.checkbox.checked = this.selected.has(mac);
			row.checkbox.disabled = !this.writable || !!this.operation;
			row.name.textContent = device.name || (this.hints[mac.toUpperCase()] || {}).name || _('Unknown device');
			for (const [cell, values] of [[row.ips4, device.ipv4], [row.ips6, device.ipv6]]) {
				const text = (values || []).join('\n') || _('Not known');
				if (cell.textContent !== text) {
					cell.textContent = text;
					cell.style.whiteSpace = 'pre-line';
				}
			}
			row.seen.textContent = device.seen ? _('Recently observed') : _('Lease or saved entry; presence unknown');
		}
		this.empty.hidden = this.rows.size > 0;
	},

	updateStatus: function(status) {
		this.lastStatus = status;
		if (this.operation && this.operation.kind === 'apply' && this.operation.committed) {
			if (status.error) { this.finishOperation(status.error); return; }
			if (status.active && status.applied && status.ra_ready !== false && JSON.stringify(this.operation.target) === JSON.stringify(macList(status.mac))) {
				this.finishOperation();
				return;
			}
		}
		const selected = Array.from(this.selected).sort();
		let text;
		if (this.operation) text = this.operation.kind === 'apply' ? _('Saving and applying changes…') : _('Saving changes…');
		else if (this.actionError) text = _('The operation did not complete.');
		else if (JSON.stringify(selected) !== JSON.stringify(this.saved)) text = _('Unsaved changes.');
		else if (status.error) text = _('The policy could not be applied. Check the error below.');
		else if (status.ra_ready === false) text = _('IPv6 network settings could not be applied.');
		else if (!status.active) text = _('IPv6 protection is not active.');
		else if (!status.applied || JSON.stringify(selected) !== JSON.stringify(macList(status.mac)))
			text = _('Saved. Not yet applied.');
		else text = _('IPv6 protection is active. Allowed devices: %s.').format(status.mac.length);
		if (this.message.textContent !== text) this.message.textContent = text;
		this.showError(this.operation ? '' : (this.actionError || status.error || ''));
	},

	showError: function(message) {
		if (this.error.textContent !== message) this.error.textContent = message;
		this.error.hidden = !message;
	},

	refresh: function() {
		const generation = this.generation;
		return Promise.all([callDevices(), callStatus(), callHints().catch(() => ({}))]).then(L.bind(function(data) {
			if (generation !== this.generation) return;
			this.hints = data[2];
			this.updateDevices(data[0]);
			this.updateStatus(data[1]);
		}, this)).catch(L.bind(function(error) {
			if (generation !== this.generation) return;
			this.showError(_('Refresh failed. Your choices have been kept.') + ' ' + error.message);
		}, this));
	},

	saveSelection: function(selected, operation) {
		if (selected.length) uci.set('passipv6', 'main', 'mac', selected);
		else uci.unset('passipv6', 'main', 'mac');
		return uci.save().then(L.bind(function() {
			if (this.operation !== operation) return;
			this.saved = selected;
			this.updateStatus(this.lastStatus);
			return ui.changes.init();
		}, this));
	},

	handleSave: function() {
		if (!this.writable) return Promise.reject(new Error(_('Permission denied.')));
		if (this.operation) return Promise.resolve();
		this.beginOperation('save');
		const operation = this.operation;
		return this.saveSelection(operation.target, operation).then(L.bind(function() {
			if (this.operation === operation) this.finishOperation();
		}, this)).catch(L.bind(function(error) {
			if (this.operation === operation) this.finishOperation(error.message || String(error));
		}, this));
	},

	handleSaveApply: function(ev, mode) {
		if (!this.writable) return Promise.reject(new Error(_('Permission denied.')));
		if (this.operation) return Promise.resolve();
		this.beginOperation('apply');
		const operation = this.operation;
		return this.saveSelection(operation.target, operation).then(function() { return uci.changes(); }).then(L.bind(function(changes) {
			if (this.operation !== operation) return;
			this.rememberApply();
			if (Object.keys(changes).length) {
				// LuCI emits uci-applied on success, but cancellation only closes its modal.
				this.modalObserver = new MutationObserver(L.bind(function() {
					if (this.operation && !this.operation.committed && !document.body.classList.contains('modal-overlay-active'))
						this.finishOperation(_('Application was cancelled or did not complete.'));
				}, this));
				ui.changes.apply(mode === '0');
				this.modalObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
				return;
			}
			// A failed apply may leave no UCI delta; the same button must still allow a retry.
			return callApply().then(L.bind(function(result) {
				if (this.operation !== operation) return;
				this.operation.committed = true;
				this.rememberApply();
				if (!result.success) {
					this.finishOperation(result.message || _('The policy could not be applied. Check the error below.'));
					return;
				}
				this.updateStatus(result.status);
			}, this));
		}, this)).catch(L.bind(function(error) {
			if (this.operation === operation) this.finishOperation(error.message || String(error));
		}, this));
	},

	handleReset: function() {
		if (this.operation) return Promise.resolve();
		this.actionError = '';
		this.selected = new Set(this.saved);
		for (const [mac, row] of this.rows) row.checkbox.checked = this.selected.has(mac);
		this.updateStatus(this.lastStatus);
		return Promise.resolve();
	},

	addFooter: function() {
		const disabled = L.hasViewPermission() && !this.operation ? null : true;
		this.footer = E('div', { 'class': 'cbi-page-actions passipv6-actions' }, [
			E('button', {
				'type': 'button', 'class': 'cbi-button cbi-button-apply important', 'disabled': disabled,
				'click': ui.createHandlerFn(this, function(ev) { return this.handleSaveApply(ev, '0'); })
			}, _('Save & Apply')), ' ',
			E('button', {
				'type': 'button', 'class': 'cbi-button cbi-button-save', 'disabled': disabled,
				'click': ui.createHandlerFn(this, 'handleSave')
			}, _('Save')), ' ',
			E('button', {
				'type': 'button', 'class': 'cbi-button cbi-button-reset', 'disabled': disabled,
				'click': ui.createHandlerFn(this, 'handleReset')
			}, _('Reset'))
		]);
		return this.footer;
	}
});
