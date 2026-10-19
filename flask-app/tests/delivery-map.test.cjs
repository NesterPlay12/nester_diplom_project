// Browser-independent regression checks for catalog selection and overlapping requests.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/delivery-map.js'), 'utf8');

function setup() {
  class Element {
    constructor(id = '') {
      this.id = id;
      this.value = '';
      this.style = {};
      this.dataset = {};
      this.handlers = {};
      this.classList = { toggle() {} };
    }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    fire(name, event = {}) { return this.handlers[name]?.(event); }
    set innerHTML(html) {
      this.html = html;
      this.items = [...html.matchAll(/class="pvz-list-item mb-1[^"]*" data-pvz-id="([^"]+)"/g)].map(match => {
        const item = new Element();
        item.dataset.pvzId = match[1];
        return item;
      });
    }
    querySelectorAll() { return this.items || []; }
  }
  const elements = new Map();
  const ids = ['pvz-map', 'pvz-map-wrap', 'pvz-list', 'pvz-city', 'pvz-provider', 'pvz-id',
    'pvz-city-selected', 'pvz-address-display', 'selected-pvz-card', 'btn-search-pvz',
    'pvz-count', 'pvz-status', 'pvz-spinner', 'checkout-form', 'final-address', 'final-phone',
    'final-comment', 'courier-phone', 'courier-comment'];
  ids.forEach(id => elements.set(id, new Element(id)));
  const calls = [];
  let ready;
  vm.runInNewContext(source, {
    document: {
      querySelector: selector => selector.includes('delivery_type') ? { value: 'pickup' } : null,
      querySelectorAll: () => [],
      getElementById: id => elements.get(id),
      addEventListener: (name, handler) => { if (name === 'DOMContentLoaded') ready = handler; },
    },
    window: {}, AbortController, console: { error() {} }, setTimeout() {}, alert() {},
    fetch: (url, options) => new Promise(resolve => calls.push({ url, options, resolve })),
  });
  ready();
  const el = id => elements.get(id);
  const search = city => { el('pvz-city').value = city; return el('btn-search-pvz').fire('click'); };
  const flush = () => new Promise(resolve => setImmediate(resolve));
  const answer = async (call, id, status = 200) => {
    call.resolve({
      ok: status === 200, status,
      json: async () => ({ center: [54, 37], unavailable: {}, pvz: [
        { id, name: `Пункт ${id}`, address: `Адрес ${id}`, lat: 54, lng: 37, provider: 'cdek' },
      ] }),
    });
    await flush();
  };
  return { el, search, calls, answer };
}

test('an older response cannot replace the new city catalog', async () => {
  const { el, search, calls, answer } = setup();
  search('Тула');
  search('Казань');
  assert.equal(calls[0].options.signal.aborted, true);
  await answer(calls[1], 'NEW');
  await answer(calls[0], 'OLD');
  assert.match(el('pvz-list').html, /NEW/);
  assert.doesNotMatch(el('pvz-list').html, /OLD/);
  el('pvz-list').items[0].fire('click');
  assert.equal(el('pvz-id').value, 'NEW');
  assert.equal(el('pvz-city-selected').value, 'Казань');
});

test('editing the city clears both the visible selection and submitted identifiers', async () => {
  const { el, search, calls, answer } = setup();
  search('Тула');
  await answer(calls[0], 'A');
  el('pvz-list').items[0].fire('click');
  assert.equal(el('pvz-id').value, 'A');
  el('pvz-city').value = 'Казань';
  el('pvz-city').fire('input');
  assert.equal(el('pvz-id').value, '');
  assert.equal(el('pvz-provider').value, '');
  assert.equal(el('pvz-city-selected').value, '');
  assert.equal(el('selected-pvz-card').style.display, 'none');
  let prevented = false;
  el('checkout-form').fire('submit', { preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
});

test('city edits invalidate requests still in flight', async () => {
  const { el, search, calls, answer } = setup();
  search('Тула');
  el('pvz-city').value = 'Казань';
  el('pvz-city').fire('input');
  await answer(calls[0], 'STALE');
  assert.doesNotMatch(el('pvz-list').html, /STALE/);
  assert.equal(el('pvz-id').value, '');
});

test('failed reloads remove the old catalog and selection', async () => {
  const { el, search, calls, answer } = setup();
  search('Тула');
  await answer(calls[0], 'A');
  el('pvz-list').items[0].fire('click');
  search('Тула');
  await answer(calls[1], 'IGNORED', 503);
  assert.equal(el('pvz-id').value, '');
  assert.doesNotMatch(el('pvz-list').html, /Адрес A/);
  assert.match(el('pvz-status').textContent, /Не удалось/);
  assert.equal(el('pvz-spinner').style.display, 'none');
});
