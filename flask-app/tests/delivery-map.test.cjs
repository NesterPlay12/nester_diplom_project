// Browser-independent regression checks for catalog selection and overlapping requests.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/delivery-map.js'), 'utf8');

function setup({ allCities = false, mapApi = false } = {}) {
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
    'final-comment', 'courier-phone', 'courier-comment', 'pvz-map-search', 'btn-reload-pvz',
    'delivery-cost', 'delivery-distance', 'checkout-total'];
  ids.forEach(id => elements.set(id, new Element(id)));
  elements.get('delivery-cost').dataset = {
    originCity: 'Новомосковск', originLat: '54.0105', originLng: '38.2915',
    baseFee: '50', perKm: '0.4',
  };
  elements.get('checkout-total').dataset.itemsTotal = '100';
  if (allCities) {
    elements.get('pvz-map').dataset.catalogScope = 'all';
    elements.delete('pvz-city');
    elements.delete('btn-search-pvz');
  }
  const mapState = { centers: [], bounds: [], markers: [], opened: [], closed: 0 };
  const ymaps = {
    ready(handler) { handler(); },
    Map: function () {
      return {
        setCenter(center) { mapState.centers.push(center); },
        setBounds(bounds) { mapState.bounds.push(bounds); },
         balloon: { close() { mapState.closed += 1; } },
        geoObjects: { add() {} },
        container: { fitToViewport() {} },
      };
    },
    Clusterer: function () {
      return {
        removeAll() { mapState.markers = []; },
        add(markers) { mapState.markers = markers; },
        getBounds() { return mapState.markers.length ? [[50, 30], [60, 50]] : null; },
      };
    },
    Placemark: function (coordinates, properties) {
      return {
        coordinates, properties, events: { add() {} },
        balloon: { open() { mapState.opened.push(coordinates); } },
      };
    },
    templateLayoutFactory: { createClass: value => value },
    geocode() { throw Error('Known addresses must not depend on external geocoding'); },
  };
  const calls = [];
  let ready, documentClick;
  vm.runInNewContext(source, {
    document: {
      querySelector: selector => selector.includes('delivery_type') ? { value: 'pickup' } : null,
      querySelectorAll: () => [],
      getElementById: id => elements.get(id),
      addEventListener: (name, handler) => {
        if (name === 'DOMContentLoaded') ready = handler;
        if (name === 'click') documentClick = handler;
      },
    },
    window: mapApi ? { ymaps } : {}, ymaps,
    AbortController, console: { error() {} }, setTimeout() {}, alert() {},
    fetch: (url, options) => new Promise(resolve => calls.push({ url, options, resolve })),
  });
  ready();
  const el = id => elements.get(id);
  const search = city => { el('pvz-city').value = city; return el('btn-search-pvz').fire('click'); };
  const choose = id => documentClick({
    target: { closest: selector => selector === '.btn-select-pvz' ? { dataset: { pvzId: id } } : null },
  });
  const flush = () => new Promise(resolve => setImmediate(resolve));
  const answerRows = async (call, points, status = 200) => {
    call.resolve({
      ok: status === 200, status,
      json: async () => ({ center: [54, 37], unavailable: {}, pvz: points }),
    });
    await flush();
  };
  const answer = (call, id, status = 200) => answerRows(call, [
    { id, name: `Пункт ${id}`, address: `Адрес ${id}`, lat: 54, lng: 37, provider: 'cdek' },
  ], status);
  return { el, search, choose, calls, answer, answerRows, mapState };
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
  assert.equal(el('pvz-id').value, '');
  assert.equal(el('pvz-city-selected').value, '');
});

test('editing the city clears both the visible selection and submitted identifiers', async () => {
  const { el, search, choose, calls, answer } = setup();
  search('Тула');
  await answer(calls[0], 'A');
  el('pvz-list').items[0].fire('click');
  assert.equal(el('pvz-id').value, '');
  choose('A');
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

const countryPoints = [
  { id: 'moscow', name: 'Москва', address: 'Москва, Тверская, 1',
    city: 'Москва', lat: 55.7, lng: 37.6, provider: 'demo' },
  { id: 'kazan', name: 'Казань', address: 'Казань, Баумана, 1',
    city: 'Казань', lat: 55.8, lng: 49.1, provider: 'demo' },
];

test('all-city map starts without a city picker and loads every marker at once', async () => {
  const { calls, answerRows, el, mapState } = setup({ allCities: true, mapApi: true });
  assert.equal(el('pvz-city'), undefined);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/delivery/pvz?provider=demo');
  await answerRows(calls[0], countryPoints);
  assert.equal(el('pvz-list').items.length, 2);
  assert.equal(mapState.markers.length, 2);
  assert.equal(el('pvz-map-wrap').style.display, 'flex');
  assert.ok(mapState.bounds.length > 0);
});

test('selection requires the explicit button and submits the point city with its delivery quote', async () => {
  const { calls, answerRows, el, choose, mapState } = setup({ allCities: true, mapApi: true });
  await answerRows(calls[0], countryPoints);
  el('pvz-list').items[1].fire('click');
  assert.equal(el('pvz-id').value, '');
  assert.equal(el('checkout-total').textContent, '100 ₽');
  assert.equal(mapState.opened.length, 1);
  choose('kazan');
  assert.equal(el('pvz-id').value, 'kazan');
  assert.equal(el('pvz-city-selected').value, 'Казань');
  assert.equal(mapState.closed, 1);
  assert.equal(el('selected-pvz-card').style.display, 'none');
  assert.match(el('delivery-cost').textContent, /₽/);
  assert.notEqual(el('checkout-total').textContent, '100 ₽');
  let prevented = false;
  el('checkout-form').fire('submit', { preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(el('pvz-city-selected').value, 'Казань');
  assert.match(el('final-address').value, /Казань, Баумана/);
});

test('local map search moves the viewport without removing other cities or refetching', async () => {
  const { calls, answerRows, el, mapState } = setup({ allCities: true, mapApi: true });
  await answerRows(calls[0], countryPoints);
  el('pvz-map-search').value = 'Казань';
  el('pvz-map-search').fire('keydown', { key: 'Enter', target: el('pvz-map-search'), preventDefault() {} });
  assert.deepEqual(Array.from(mapState.centers.at(-1)), [55.8, 49.1]);
  assert.equal(mapState.markers.length, 2);
  assert.equal(calls.length, 1);
});

test('refresh replaces the shared catalogue and clears outdated selections', async () => {
  const { calls, answerRows, el, mapState, choose } = setup({ allCities: true, mapApi: true });
  await answerRows(calls[0], countryPoints);
  choose('kazan');
  assert.notEqual(el('delivery-cost').textContent, '—');
  el('btn-reload-pvz').fire('click');
  assert.equal(el('pvz-id').value, '');
  assert.equal(el('pvz-city-selected').value, '');
  assert.equal(el('delivery-cost').textContent, '—');
  assert.equal(el('checkout-total').textContent, '100 ₽');
  await answerRows(calls[1], [countryPoints[0]]);
  assert.equal(mapState.markers.length, 1);
  assert.doesNotMatch(el('pvz-list').html, /Баумана/);
});

test('a shared catalogue network failure can be retried without the city picker', async () => {
  const { calls, answerRows, el, choose } = setup({ allCities: true });
  await answerRows(calls[0], [], 503);
  assert.match(el('pvz-status').textContent, /Не удалось/);
  el('btn-reload-pvz').fire('click');
  await answerRows(calls[1], countryPoints);
  assert.equal(el('pvz-list').items.length, 2);
  choose('kazan');
  assert.equal(el('pvz-city-selected').value, 'Казань');
});
