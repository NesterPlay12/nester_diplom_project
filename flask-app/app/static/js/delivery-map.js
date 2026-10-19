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
  let unavailableProviders = {};
  let currentProvider = 'all';
  let mapCityUnresolved = false;
  let mapCenter = [55.7558, 37.6176];
  let loadedCity = '';
  let requestVersion = 0;
  let loading = false;
  const appBasePath = document.querySelector('meta[name="app-base-path"]')?.content || '';
  const appUrl = path => `${appBasePath}${path}`;

  const PROVIDER_COLOR = { cdek: '#ff7a00', pochta: '#a700ff', demo: '#cb11ab' };
  const PROVIDER_LABEL = { cdek: 'СДЭК', pochta: 'Почта России', demo: 'Демо WildMarket' };
  const qs = id => document.getElementById(id);

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

  function markerLayout(pvz) {
    const color = PROVIDER_COLOR[pvz.provider] || '#cb11ab';
    return {
      preset: 'islands#circleDotIcon',
      iconColor: color,
      iconCaption: pvz.provider === 'demo' ? 'Д' : pvz.provider === 'cdek' ? 'С' : 'П',
      iconCaptionMaxWidth: 18,
      hideIconOnBalloonOpen: false,
    };
  }

  function popupHtml(pvz) {
    return `<div style="min-width:220px">
      <b>${escapeHtml(pvz.name)}</b>
      <div style="margin:6px 0;color:#555">${escapeHtml(pvz.address)}</div>
      <div style="font-size:12px;color:#777">${escapeHtml(pvz.work_time || 'График уточняется')}</div>
      <button type="button" class="btn-select-pvz" data-pvz-id="${escapeHtml(pvz.id)}"
        style="margin-top:10px;padding:7px 12px;background:#cb11ab;color:#fff;border:0;border-radius:6px;font-weight:600;width:100%">
        Выбрать этот пункт
      </button>
    </div>`;
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
    document.addEventListener('click', e => {
      const button = e.target.closest('.btn-select-pvz');
      if (!button) return;
      const pvz = allPvz.find(item => item.id === button.dataset.pvzId);
      if (pvz) selectPvz(pvz);
    });
    qs('pvz-map-search')?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        e.preventDefault();
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
    const geoObjects = list.filter(p => Number.isFinite(Number(p.lat)) && Number.isFinite(Number(p.lng))).map(pvz => {
      const point = new ymaps.Placemark([pvz.lat, pvz.lng], {
        name: pvz.name, address: pvz.address,
        balloonContentBody: popupHtml(pvz),
        hintContent: `${PROVIDER_LABEL[pvz.provider]} · ${pvz.address}`,
      }, markerLayout(pvz));
      point.events.add('click', () => selectPvz(pvz));
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
      <button type="button" class="pvz-list-item mb-1 text-start w-100" data-pvz-id="${escapeHtml(pvz.id)}">
        <div class="small fw-semibold">${escapeHtml(pvz.address)}</div>
        <div class="pvz-address small mt-1">${escapeHtml(pvz.name)}</div>
        <div class="pvz-meta mt-1">${escapeHtml(PROVIDER_LABEL[pvz.provider] || 'Пункт выдачи')}${pvz.work_time ? ` · ${escapeHtml(pvz.work_time)}` : ''}</div>
      </button>`).join('');
    container.querySelectorAll('.pvz-list-item').forEach(item => item.addEventListener('click', () => {
      const pvz = list.find(point => point.id === item.dataset.pvzId);
      if (!pvz) return;
      selectPvz(pvz);
      map?.setCenter([pvz.lat, pvz.lng], 15);
    }));
    highlightList();
  }

  function highlightList() {
    document.querySelectorAll('.pvz-list-item').forEach(item => {
      item.classList.toggle('pvz-list-item--active', item.dataset.pvzId === selectedPvz?.id);
    });
  }

  function selectPvz(pvz) {
    if (qs('pvz-city')?.value.trim() !== loadedCity || loading) return;
    selectedPvz = pvz;
    if (qs('pvz-provider')) qs('pvz-provider').value = pvz.provider;
    if (qs('pvz-id')) qs('pvz-id').value = pvz.id;
    if (qs('pvz-city-selected')) qs('pvz-city-selected').value = loadedCity;
    const display = qs('pvz-address-display');
    if (display) display.value = pvz.address;
    const card = qs('selected-pvz-card');
    if (card) {
      card.style.display = 'block';
      card.innerHTML = `<div class="d-flex justify-content-between align-items-start gap-2">
        <div><span class="badge text-white mb-2" style="background:${PROVIDER_COLOR[pvz.provider]}">${PROVIDER_LABEL[pvz.provider]}</span>
          <div class="fw-bold">${escapeHtml(pvz.name)}</div>
          <div class="small text-muted mt-1"><i class="bi bi-geo-alt me-1"></i>${escapeHtml(pvz.address)}</div>
          <div class="small text-muted mt-1"><i class="bi bi-clock me-1"></i>${escapeHtml(pvz.work_time || '')}</div>
        </div><button type="button" class="btn btn-sm btn-outline-secondary" id="btn-change-pvz">Изменить</button>
      </div>`;
      qs('btn-change-pvz')?.addEventListener('click', clearPvz);
    }
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
      status.textContent = relevantErrors.join(' ') || (!allPvz.length ? 'В выбранном городе каталог не вернул пунктов выдачи.' : '');
      status.hidden = !status.textContent;
    }
  }

  async function loadPvz(city) {
    const version = ++requestVersion;
    loading = true;
    const spinner = qs('pvz-spinner'), wrap = qs('pvz-map-wrap');
    if (spinner) spinner.style.display = 'flex';
    if (wrap) wrap.style.display = 'none';
    clearPvz();
    try {
      const response = await fetch(appUrl(`/delivery/pvz?city=${encodeURIComponent(city)}&provider=all`));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (version !== requestVersion) return;
      loadedCity = city;
      allPvz = data.pvz || [];
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
      mapCityUnresolved = !cityResolved;
      if (version !== requestVersion) return;
      loading = false;
      const mapElement = qs('pvz-map');
      if (mapElement) mapElement.style.display = cityResolved ? '' : 'none';
      initMap();
      if (cityResolved) map?.setCenter(mapCenter, 12);
      applyProvider(currentProvider);
      if (wrap) wrap.style.display = 'flex';
    } catch (error) {
      if (version !== requestVersion) return;
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
      if (qs('pvz-count')) qs('pvz-count').textContent = '';
    } finally {
      if (version === requestVersion) {
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
    if (pickup && !loadedCity && !loading && qs('pvz-city')?.value.trim()) {
      loadPvz(qs('pvz-city').value.trim());
    }
    if (!pickup) clearPvz();
    setTimeout(() => map?.container.fitToViewport(), 200);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[name="delivery_type"]').forEach(radio => radio.addEventListener('change', onDeliveryTypeChange));
    onDeliveryTypeChange();
    qs('btn-search-pvz')?.addEventListener('click', () => {
      const city = qs('pvz-city')?.value.trim();
      if (city) loadPvz(city);
      else qs('pvz-city')?.focus();
    });
    qs('pvz-city')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); qs('btn-search-pvz')?.click(); }
    });
    qs('pvz-city')?.addEventListener('input', () => {
      ++requestVersion;
      loading = false;
      clearPvz();
      allPvz = [];
      renderMarkers([]);
      renderList([]);
      if (qs('pvz-count')) qs('pvz-count').textContent = '';
      if (qs('pvz-spinner')) qs('pvz-spinner').style.display = 'none';
    });
    document.querySelectorAll('[data-pvz-provider]').forEach(button =>
      button.addEventListener('click', () => applyProvider(button.dataset.pvzProvider)));
    qs('checkout-form')?.addEventListener('submit', e => {
      const pickup = document.querySelector('input[name="delivery_type"]:checked')?.value === 'pickup';
      if (pickup) {
        if (!selectedPvz || loading || loadedCity !== qs('pvz-city')?.value.trim()) {
          e.preventDefault();
          alert('Введите город и выберите пункт выдачи на карте');
          return;
        }
       qs('final-address').value = `ПВЗ ${PROVIDER_LABEL[selectedPvz.provider]}: ${selectedPvz.address}`;
       qs('pvz-city-selected').value = loadedCity;
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