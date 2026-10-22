/**
 * WildMarket — Yandex Maps pickup-point selector.
 * Uses the application's /delivery/pvz data and Yandex's map/cluster UI.
 */
'use strict';

(function () {
  let map = null;
  let clusterer = null;
  let selectedPvz = null;
  let allPvz = [];
  let markerById = new Map();
  let unavailableProviders = {};
  let currentProvider = 'all';
  let mapCityUnresolved = false;
  let mapCenter = [55.7558, 37.6176];

  let catalogRequest = 0;
  let catalogController = null;
  let loadedCity = '';
  let catalogLoaded = false;
  let loading = false;
  const appBasePath = document.querySelector('meta[name="app-base-path"]')?.content || '';
  const appUrl = path => `${appBasePath}${path}`;

  const PROVIDER_COLOR = { cdek: '#ff7a00', pochta: '#a700ff', demo: '#cb11ab' };
  const PROVIDER_LABEL = { cdek: 'СДЭК', pochta: 'Почта России', demo: 'Адрес WildMarket' };
  const qs = id => document.getElementById(id);
  const allCities = qs('pvz-map')?.dataset.catalogScope === 'all';

  function suffix(n) {
    const m10 = n % 10, m100 = n % 100;
    if (m100 >= 11 && m100 <= 14) return 'ов';
    if (m10 === 1) return '';
    if (m10 >= 2 && m10 <= 4) return 'а';
    return 'ов';
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function formatRub(value) {
    return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)} ₽`;
  }

  function calculateDeliveryQuote(pvz) {
    const cost = qs('delivery-cost');
    const originLat = Number(cost?.dataset.originLat);
    const originLng = Number(cost?.dataset.originLng);
    const lat = Number(pvz.lat);
    const lng = Number(pvz.lng);
    if (![originLat, originLng, lat, lng].every(Number.isFinite)) return null;

    const toRadians = value => value * Math.PI / 180;
    const deltaLat = toRadians(lat - originLat);
    const deltaLng = toRadians(lng - originLng);
    const a = Math.sin(deltaLat / 2) ** 2
      + Math.cos(toRadians(originLat)) * Math.cos(toRadians(lat))
      * Math.sin(deltaLng / 2) ** 2;
    const distanceKm = Math.round(
      2 * 6371.0088 * Math.asin(Math.sqrt(Math.min(1, a))) * 1000
    ) / 1000;
    const baseFee = Number(cost.dataset.baseFee);
    const perKm = Number(cost.dataset.perKm);
    const fee = Math.round((baseFee + distanceKm * perKm) * 100) / 100;
    return { distanceKm, fee, originCity: cost.dataset.originCity };
  }

  function updateDeliverySummary(quote = null) {
    const cost = qs('delivery-cost');
    const distance = qs('delivery-distance');
    const total = qs('checkout-total');
    const itemsTotal = Number(total?.dataset.itemsTotal || 0);
    if (!quote) {
      if (cost) cost.textContent = '—';
      if (distance) distance.textContent = '';
      if (total) total.textContent = formatRub(itemsTotal);
      return;
    }

    if (cost) cost.textContent = formatRub(quote.fee);
    if (distance) {
      const km = new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 1, maximumFractionDigits: 1,
      }).format(quote.distanceKm);
      distance.textContent = `${km} км от ${quote.originCity} · 50 ₽ + 0,4 ₽/км`;
    }
    if (total) total.textContent = formatRub(itemsTotal + quote.fee);
  }

  function markerLayout(pvz) {
    const color = PROVIDER_COLOR[pvz.provider] || '#cb11ab';
    return {
      preset: 'islands#circleDotIcon',
      iconColor: color,
      iconCaption: pvz.provider === 'demo' ? 'W' : pvz.provider === 'cdek' ? 'С' : 'П',
      iconCaptionMaxWidth: 18,
      hideIconOnBalloonOpen: false,
    };
  }

  function popupHtml(pvz) {
    return `<div style="min-width:220px">
      <b>${escapeHtml(pvz.name)}</b>
      <div style="margin:6px 0;color:#555">${escapeHtml(pvz.address)}</div>
      ${pvz.provider !== 'demo' ? `<div style="font-size:12px;color:#777">${escapeHtml(pvz.work_time || 'График уточняется')}</div>` : ''}
      <button type="button" class="btn-select-pvz" data-pvz-id="${escapeHtml(pvz.id)}"
        style="margin-top:10px;padding:7px 12px;background:#cb11ab;color:#fff;border:0;border-radius:6px;font-weight:600;width:100%">
        Выбрать этот пункт
      </button>
    </div>`;
  }

  function focusPoints(points) {
    if (!map || !points.length) return;
    if (points.length === 1) {
      map.setCenter([Number(points[0].lat), Number(points[0].lng)], 15);
      return;
    }
    map.setBounds([
      [Math.min(...points.map(p => Number(p.lat))), Math.min(...points.map(p => Number(p.lng)))],
      [Math.max(...points.map(p => Number(p.lat))), Math.max(...points.map(p => Number(p.lng)))],
    ], { checkZoomRange: true, zoomMargin: 40, duration: 250 });
  }

  function initMap() {
    if (map || !window.ymaps || !qs('pvz-map')) return;
    map = new ymaps.Map('pvz-map', {
      center: mapCenter, zoom: 12,
      controls: ['zoomControl', 'geolocationControl', 'fullscreenControl']
    }, { suppressMapOpenBlock: true });
    clusterer = new ymaps.Clusterer({
      preset: 'islands#invertedVioletClusterIcons',
      groupByCoordinates: false,
      clusterDisableClickZoom: false,
      clusterOpenBalloonOnClick: true,
      clusterBalloonContentLayout: 'cluster#balloonCarousel',
      clusterBalloonItemContentLayout: ymaps.templateLayoutFactory.createClass(
        '<b>{{ properties.name }}</b><br><span>{{ properties.address }}</span>'
      )
    });
    renderMarkers(filtered());
    map.geoObjects.add(clusterer);
    qs('pvz-map-search')?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        e.preventDefault();
        const query = e.target.value.trim().toLocaleLowerCase('ru').replace(/ё/g, 'е');
        const local = allPvz.filter(point =>
          `${point.city || ''} ${point.address}`.toLocaleLowerCase('ru').replace(/ё/g, 'е').includes(query));
        if (local.length) {
          focusPoints(local);
          return;
        }
        ymaps.geocode(e.target.value.trim(), { results: 1 }).then(result => {
          const first = result.geoObjects.get(0);
          if (first) map.setCenter(first.geometry.getCoordinates(), 13);
        }).catch(() => {
          const status = qs('pvz-status');
          if (status) {
            status.textContent = 'Поиск адреса недоступен. Выберите пункт из списка.';
            status.hidden = false;
          }
        });
      }
    });
  }

  function renderMarkers(list) {
    if (!map || !clusterer) return;
    clusterer.removeAll();
    markerById = new Map();
    const geoObjects = list.filter(p => Number.isFinite(Number(p.lat)) && Number.isFinite(Number(p.lng))).map(pvz => {
      const point = new ymaps.Placemark([pvz.lat, pvz.lng], {
        name: escapeHtml(pvz.name), address: escapeHtml(pvz.address),
        balloonContentBody: popupHtml(pvz),
        hintContent: `${PROVIDER_LABEL[pvz.provider]} · ${escapeHtml(pvz.address)}`,
      }, markerLayout(pvz));
      markerById.set(pvz.id, point);
      return point;
    });
    clusterer.add(geoObjects);
    if (list.length) {
      const bounds = clusterer.getBounds();
      if (bounds) map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 30, duration: 250 });
    }
  }

  function renderList(list) {
    const container = qs('pvz-list');
    if (!container) return;
    if (!list.length) {
      container.innerHTML = '<div class="p-3 text-center text-secondary">По выбранным условиям пунктов нет</div>';
      return;
    }
    container.innerHTML = list.map(pvz => `
      <div class="pvz-entry mb-2">
        <button type="button" class="pvz-list-item mb-1 text-start w-100" data-pvz-id="${escapeHtml(pvz.id)}">
          <div class="small fw-semibold">${escapeHtml(pvz.address)}</div>
          <div class="pvz-address small mt-1">${escapeHtml(pvz.name)}</div>
          <div class="pvz-meta mt-1">${escapeHtml(PROVIDER_LABEL[pvz.provider] || 'Пункт выдачи')}${pvz.work_time && pvz.provider !== 'demo' ? ` · ${escapeHtml(pvz.work_time)}` : ''}</div>
        </button>
        <button type="button" class="btn btn-wb btn-sm w-100 btn-select-pvz" data-pvz-id="${escapeHtml(pvz.id)}">Выбрать этот пункт</button>
      </div>`).join('');
    container.querySelectorAll('.pvz-list-item').forEach(item => item.addEventListener('click', () => {
      const pvz = list.find(point => point.id === item.dataset.pvzId);
      if (!pvz) return;
      map?.setCenter([pvz.lat, pvz.lng], 15);
      markerById.get(pvz.id)?.balloon?.open();
    }));
    highlightList();
  }

  function highlightList() {
    document.querySelectorAll('.pvz-list-item').forEach(item => {
      item.classList.toggle('pvz-list-item--active', item.dataset.pvzId === selectedPvz?.id);
    });
  }

  function selectPvz(pvz) {
    if (loading || !catalogLoaded || !allPvz.includes(pvz)) return;
    if (!allCities && loadedCity !== qs('pvz-city')?.value.trim()) return;
    const quote = calculateDeliveryQuote(pvz);
    if (!quote) {
      const status = qs('pvz-status');
      if (status) {
        status.textContent = 'Не удалось рассчитать доставку: у пункта нет корректных координат.';
        status.hidden = false;
      }
      return;
    }
    selectedPvz = pvz;
    if (qs('pvz-provider')) qs('pvz-provider').value = pvz.provider;
    if (qs('pvz-id')) qs('pvz-id').value = pvz.id;
    if (qs('pvz-city-selected')) qs('pvz-city-selected').value = pvz.city || loadedCity;
    const display = qs('pvz-address-display');
    if (display) display.value = pvz.address;
    const card = qs('selected-pvz-card');
    if (card) {
      card.style.display = 'none';
      card.innerHTML = '';
    }
    updateDeliverySummary(quote);
    map?.balloon?.close();
    highlightList();
  }

  function clearPvz() {
    selectedPvz = null;
    if (qs('pvz-provider')) qs('pvz-provider').value = '';
    if (qs('pvz-id')) qs('pvz-id').value = '';
    if (qs('pvz-city-selected')) qs('pvz-city-selected').value = '';
    if (qs('pvz-address-display')) qs('pvz-address-display').value = '';
    if (qs('selected-pvz-card')) {
      qs('selected-pvz-card').style.display = 'none';
      qs('selected-pvz-card').innerHTML = '';
    }
    updateDeliverySummary();
    highlightList();
  }

  function filtered() {
    return currentProvider === 'all' ? allPvz : allPvz.filter(p => p.provider === currentProvider);
  }

  function applyProvider(provider) {
    currentProvider = provider;
    if (selectedPvz && provider !== 'all' && selectedPvz.provider !== provider) clearPvz();
    document.querySelectorAll('[data-pvz-provider]').forEach(button => {
      const active = button.dataset.pvzProvider === provider;
      button.classList.toggle('active', active);
      button.classList.toggle('btn-wb', active);
      button.classList.toggle('btn-outline-secondary', !active);
    });
    const list = filtered();
    renderMarkers(list);
    renderList(list);
    if (qs('pvz-count')) qs('pvz-count').textContent = `${list.length} пункт${suffix(list.length)} выдачи`;
    const relevantErrors = provider === 'all'
      ? Object.values(unavailableProviders)
      : [unavailableProviders[provider]].filter(Boolean);
    if (mapCityUnresolved) relevantErrors.push('Не удалось определить город на карте. Проверьте его название.');
    const status = qs('pvz-status');
    if (status) {
      status.textContent = relevantErrors.join(' ') || (!allPvz.length
        ? (allCities ? 'Адреса пока не добавлены.' : 'В выбранном городе каталог не вернул пунктов выдачи.') : '');
      status.hidden = !status.textContent;
    }
  }

  async function loadPvz(city = '') {
    catalogController?.abort();
    catalogController = new AbortController();
    const requestId = ++catalogRequest;
    loading = true;
    const spinner = qs('pvz-spinner'), wrap = qs('pvz-map-wrap');
    if (spinner) spinner.style.display = 'flex';
    if (wrap) wrap.style.display = 'none';
    clearPvz();
    catalogLoaded = false;
    loadedCity = '';
    allPvz = [];
    renderMarkers([]);
    renderList([]);
    try {
      const query = allCities ? 'provider=demo' : `city=${encodeURIComponent(city)}&provider=all`;
      const response = await fetch(appUrl(`/delivery/pvz?${query}`),
        { signal: catalogController.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (requestId !== catalogRequest) return;
      if (!Array.isArray(data.pvz)) throw new Error('Invalid catalog response');
      const points = data.pvz;
      unavailableProviders = data.unavailable || {};
      mapCityUnresolved = false;
      let cityResolved = false;
      if (
        Array.isArray(data.center)
        && data.center.length === 2
        && data.center.every(value => Number.isFinite(Number(value)))
      ) {
        mapCenter = data.center.map(Number);
        cityResolved = true;
      } else if (allCities) {
        cityResolved = true;
      } else if (window.ymaps) {
        try {
          const geo = await ymaps.geocode(city, { results: 1 });
          const first = geo.geoObjects.get(0);
          if (first) {
            mapCenter = first.geometry.getCoordinates();
            cityResolved = true;
          }
        } catch (_) {
          cityResolved = false;
        }
      }
      if (requestId !== catalogRequest) return;
      allPvz = points;
      loadedCity = city;
      catalogLoaded = true;
      mapCityUnresolved = !cityResolved;
      const mapElement = qs('pvz-map');
      if (mapElement) mapElement.style.display = cityResolved ? '' : 'none';
      if (wrap) wrap.style.display = 'flex';
      applyProvider(currentProvider);
      if (window.ymaps) {
        ymaps.ready(() => {
          if (requestId !== catalogRequest) return;
          initMap();
          map?.container.fitToViewport();
          if (!allCities && cityResolved) map?.setCenter(mapCenter, 12);
          renderMarkers(filtered());
        });
      }
    } catch (error) {
      if (requestId !== catalogRequest || error.name === 'AbortError') return;
      console.error('PVZ load error:', error);
      allPvz = [];
      unavailableProviders = {};
      mapCityUnresolved = false;
      const status = qs('pvz-status');
      if (status) {
        status.textContent = 'Не удалось получить каталог пунктов выдачи. Попробуйте ещё раз.';
        status.hidden = false;
      }
      renderList([]);
      renderMarkers([]);
      if (qs('pvz-count')) qs('pvz-count').textContent = '';
    } finally {
      if (requestId === catalogRequest) {
        loading = false;
        if (spinner) spinner.style.display = 'none';
      }
    }
  }

  function onDeliveryTypeChange() {
    const pickup = document.querySelector('input[name="delivery_type"]:checked')?.value === 'pickup';
    if (qs('section-courier')) qs('section-courier').style.display = pickup ? 'none' : 'block';
    if (qs('section-pickup')) qs('section-pickup').style.display = pickup ? 'block' : 'none';
    if (pickup && !map && window.ymaps) ymaps.ready(initMap);
    if (pickup && !catalogLoaded && !loading && (allCities || qs('pvz-city')?.value.trim())) {
      loadPvz(allCities ? '' : qs('pvz-city').value.trim());
    }
    if (!pickup) clearPvz();
    setTimeout(() => map?.container.fitToViewport(), 200);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.addEventListener('click', e => {
      const button = e.target.closest?.('.btn-select-pvz');
      if (!button) return;
      const pvz = allPvz.find(item => item.id === button.dataset.pvzId);
      if (pvz) selectPvz(pvz);
    });
    document.querySelectorAll('input[name="delivery_type"]').forEach(radio => radio.addEventListener('change', onDeliveryTypeChange));
    onDeliveryTypeChange();
    qs('btn-reload-pvz')?.addEventListener('click', () => loadPvz());
    qs('btn-search-pvz')?.addEventListener('click', () => {
      const city = qs('pvz-city')?.value.trim();
      if (city) loadPvz(city);
      else qs('pvz-city')?.focus();
    });
    qs('pvz-city')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); qs('btn-search-pvz')?.click(); }
    });
    qs('pvz-city')?.addEventListener('input', () => {
      ++catalogRequest;
      catalogController?.abort();
      loading = false;
      loadedCity = '';
      catalogLoaded = false;
      clearPvz();
      allPvz = [];
      unavailableProviders = {};
      renderMarkers([]);
      renderList([]);
      if (qs('pvz-spinner')) qs('pvz-spinner').style.display = 'none';
      if (qs('pvz-count')) qs('pvz-count').textContent = '';
      if (qs('pvz-status')) {
        qs('pvz-status').textContent = 'Нажмите «Найти», чтобы загрузить каталог для указанного города.';
        qs('pvz-status').hidden = false;
      }
    });
    document.querySelectorAll('[data-pvz-provider]').forEach(button =>
      button.addEventListener('click', () => applyProvider(button.dataset.pvzProvider)));
    qs('checkout-form')?.addEventListener('submit', e => {
      const pickup = document.querySelector('input[name="delivery_type"]:checked')?.value === 'pickup';
      if (pickup) {
        if (!selectedPvz || loading || !catalogLoaded
            || (!allCities && loadedCity !== qs('pvz-city')?.value.trim())) {
          e.preventDefault();
          alert(allCities ? 'Выберите адрес на карте или в списке' : 'Введите город и выберите пункт выдачи на карте');
          return;
        }
       qs('final-address').value = `ПВЗ ${PROVIDER_LABEL[selectedPvz.provider]}: ${selectedPvz.address}`;
        qs('pvz-city-selected').value = selectedPvz.city || loadedCity;
      } else {
        const address = qs('courier-address')?.value.trim();
        if (!address) {
          e.preventDefault();
          qs('courier-address')?.focus();
          return;
        }
        qs('final-address').value = address;
      }
      qs('final-phone').value = qs('courier-phone')?.value || '';
      qs('final-comment').value = qs('courier-comment')?.value || '';
    });
  });
})();

