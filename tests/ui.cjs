const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const axe = require('axe-core');
const source = fs.readFileSync(path.join(__dirname, '../htdocs/luci-static/resources/view/passipv6.js'), 'utf8');
const MAC = '02:00:00:00:00:0a';
const windows = [];
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

async function fixture(options = {}) {
  const dom = new JSDOM('<!doctype html><html lang="en"><head><title>PassIPV6</title></head><body><main></main></body></html>', {
    runScripts: 'outside-only', url: 'http://router.test/'
  });
  const w = dom.window;
  windows.push(w);
  const state = {
    stored: [MAC], writable: true, applies: 0, saved: 0, nativeCalls: 0,
    changes: {}, status: { active: true, applied: true, mac: [MAC] },
    devices: [{ mac: MAC, name: '<img src=x onerror=alert(1)>', ipv4: ['192.0.2.10'], ipv6: ['fd42::10'], seen: true }],
    ...options
  };
  w._ = text => text;
  w.eval('String.prototype.format = function(...args) { let i=0; return this.replace(/%s/g, () => args[i++]); };');
  w.L = {
    env: { sessionid: 'test-session', apply_rollback: 90, apply_holdoff: 4 },
    toArray: value => Array.isArray(value) ? value : value ? [value] : [],
    bind: (fn, self) => fn.bind(self), hasViewPermission: () => state.writable
  };
  w.E = (tag, attrs = {}, children = []) => {
    const node = w.document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null) continue;
      if (typeof value === 'function') node.addEventListener(key, value);
      else node.setAttribute(key, value);
    }
    for (const child of Array.isArray(children) ? children : [children]) node.append(child);
    return node;
  };
  w.view = { extend: value => value };
  w.rpc = { declare: spec => async () => {
    if (state.failRefresh && spec.method !== 'apply') throw new Error('offline');
    if (spec.method === 'devices') return state.devices;
    if (spec.method === 'getHostHints') return {};
    if (spec.method === 'apply') {
      state.applies++;
      return state.apply ? state.apply() : { success: true, status: state.status };
    }
    return state.getStatus ? state.getStatus() : state.status;
  } };
  w.uci = {
    load: async () => {}, get: () => state.stored,
    set: (pkg, section, option, value) => { state.stored = value; },
    unset: () => { state.stored = []; },
    save: async () => { state.saved++; if (state.save) await state.save(); },
    changes: async () => state.changes
  };
  w.ui = {
    changes: { init: async () => {}, apply: () => { state.nativeCalls++; w.document.body.classList.add('modal-overlay-active'); } },
    createHandlerFn: (self, method) => typeof method === 'function' ? method.bind(self) : self[method].bind(self)
  };
  w.poll = { add: () => {} };
  if (options.pending) w.sessionStorage.setItem('passipv6.apply.test-session', JSON.stringify(options.pending));
  const page = w.eval('(function(){' + source + '\n})()');
  w.document.querySelector('main').append(page.render(await page.load()), page.addFooter());
  return { w, page, state, checkbox: w.document.querySelector('input'), edit(checked) {
    const input = w.document.querySelector('input');
    input.checked = checked;
    input.dispatchEvent(new w.Event('change'));
  } };
}

async function main() {
  const f = await fixture();
  assert(!f.checkbox.disabled);
  assert.equal(f.w.document.querySelectorAll('img').length, 0);
  assert(!/passwall|ad filtering/i.test(f.w.document.querySelector('.passipv6').textContent));
  f.checkbox.focus(); f.edit(false);
  f.state.devices.push({ mac: '02:00:00:00:00:01', ipv4: [], ipv6: [], seen: true });
  await f.page.refresh();
  assert.equal(f.w.document.activeElement, f.checkbox);
  assert(!f.checkbox.checked);
  await f.page.handleSave();
  assert.equal(f.state.applies, 0);
  assert.equal(f.page.message.textContent, 'Saved. Not yet applied.');

  const save = deferred(), apply = deferred();
  f.state.save = () => save.promise;
  f.state.apply = () => apply.promise;
  const announcements = [];
  const observer = new f.w.MutationObserver(() => announcements.push(f.page.message.textContent));
  observer.observe(f.page.message, { childList: true, subtree: true, characterData: true });
  const applying = f.page.handleSaveApply(null, '0');
  assert.equal(f.page.message.textContent, 'Saving and applying changes…');
  assert(f.checkbox.disabled);
  await f.page.refresh();
  assert.equal(f.page.message.textContent, 'Saving and applying changes…');
  save.resolve(); await settle();
  assert.equal(f.page.message.textContent, 'Saving and applying changes…');
  apply.resolve({ success: true, status: { active: true, applied: true, mac: [] } });
  await applying; await settle();
  assert(f.page.message.textContent.includes('active. Allowed devices: 0'));
  assert(!f.checkbox.disabled);
  assert(!announcements.some(s => /Unsaved|Not yet|Use Save/.test(s)));
  observer.disconnect();
  f.edit(true);
  assert.equal(f.page.message.textContent, 'Unsaved changes.');

  const old = deferred();
  f.state.getStatus = () => old.promise;
  const oldRefresh = f.page.refresh();
  f.state.getStatus = null; f.state.save = null;
  f.state.status = { active: true, applied: true, mac: [MAC] };
  f.state.apply = () => ({ success: true, status: f.state.status });
  await f.page.handleSaveApply(null, '0');
  old.resolve({ active: true, applied: false, mac: [] }); await oldRefresh;
  assert(f.page.message.textContent.includes('active. Allowed devices: 1'));

  const n = await fixture({ changes: { passipv6: [['set']] } });
  n.edit(false); await n.page.handleSaveApply(null, '0');
  assert.equal(n.state.nativeCalls, 1);
  const pending = JSON.parse(n.w.sessionStorage.getItem(n.page.storageKey));
  assert.deepEqual(pending.target, []);
  n.state.status = { active: true, applied: true, mac: [] };
  n.w.document.dispatchEvent(new n.w.CustomEvent('uci-applied'));
  await settle();
  assert(!n.page.operation);
  assert.equal(n.w.sessionStorage.getItem(n.page.storageKey), null);

  const resumed = await fixture({ stored: [], status: { active: true, applied: false, mac: [MAC] }, pending: { ...pending, committed: true } });
  assert.equal(resumed.page.message.textContent, 'Saving and applying changes…');
  resumed.state.status = { active: true, applied: true, mac: [] };
  await resumed.page.refresh();
  assert(!resumed.page.operation);
  assert(resumed.page.message.textContent.includes('active. Allowed devices: 0'));

  const cancelled = await fixture({ changes: { passipv6: [['set']] } });
  cancelled.edit(false); await cancelled.page.handleSaveApply(null, '0');
  cancelled.w.document.body.classList.remove('modal-overlay-active'); await settle();
  assert(!cancelled.page.operation);
  assert(cancelled.page.error.textContent.includes('cancelled'));

  const ra = await fixture({ status: { active: true, applied: true, ra_ready: false, mac: [MAC] } });
  assert.equal(ra.page.message.textContent, 'IPv6 network settings could not be applied.');
  await ra.page.handleSaveApply(null, '0');
  assert(ra.page.operation, 'Do not confirm apply while RA delivery is unavailable');
  ra.state.status = { active: true, applied: true, ra_ready: true, mac: [MAC] };
  await ra.page.refresh();
  assert(!ra.page.operation);
  assert(ra.w.document.querySelector('.passipv6').textContent.includes('reconnect affected devices once'));

  const failure = await fixture();
  failure.state.apply = () => ({ success: false, message: 'nft check failed', status: failure.state.status });
  await failure.page.handleSaveApply(null, '0');
  assert(!failure.page.operation);
  assert.equal(failure.page.error.textContent, 'nft check failed');
  failure.state.save = () => Promise.reject(new Error('save failed'));
  await failure.page.handleSaveApply(null, '0');
  assert.equal(failure.page.error.textContent, 'save failed');

  const timeout = await fixture({ stored: [], status: { active: true, applied: false, mac: [MAC] }, pending: { ...pending, expires: Date.now() - 1, committed: true } });
  await settle();
  assert(!timeout.page.operation);
  assert(timeout.page.error.textContent.includes('could not be confirmed'));
  const readonly = await fixture({ writable: false });
  assert(readonly.checkbox.disabled);
  await assert.rejects(() => readonly.page.handleSaveApply(), /Permission denied/);
  f.state.failRefresh = true; await f.page.refresh();
  assert(f.page.error.textContent.includes('choices have been kept'));

  f.w.eval(axe.source);
  const results = await f.w.axe.run(f.w.document, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
    rules: { 'color-contrast': { enabled: false } }
  });
  assert.equal(results.violations.length, 0, JSON.stringify(results.violations));
  console.log('PASS: save/apply announcements, stale requests, reload recovery, cancellation, errors, timeout, focus, permissions and accessibility');
}
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => windows.forEach(w => w.close()));
