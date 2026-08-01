/**
 * WildMarket — выбор пункта выдачи заказа
 * Leaflet.js + OpenStreetMap (бесплатно, без API-ключа)
 */

'use strict';

(function () {
  let map          = null;
  let markersLayer = null;
  let selectedPvz  = null;
  let allPvz       = [];
  let currentProvider = 'all';

  const PROVIDER_COLOR = { cdek: '#f97316', pochta: '#3b82f6' };
  const PROVIDER_LABEL = { cdek: 'СДЭК',   pochta: 'Почта России' };

  // ── Вспомогательные функции ──────────────────────────────────────────────

  function qs(id) { return document.getElementById(id); }

  function pvzSuffix(n) {
    const m10 = n % 10, m100 = n % 100;
    if (m100 >= 11 && m100 <= 14) return 'ов';
    if (m10 === 1)                 return '';
    if (m10 >= 2 && m10 <= 4)     return 'а';
    return 'ов';
  }

  // ── Инициализация карты ───────────────────────────────────────────────────

  function initMap(lat, lng) {
    const container = qs('pvz-map');
    if (!container) return;

    if (map) { map.setView([lat, lng], 12); return; }

    map = L.map('pvz-map', { zoomControl: true }).setView([lat, lng], 12);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);

    markersLayer = L.layerGroup().addTo(map);
    setTimeout(() => map && map.invalidateSize(), 300);
  }

  // ── Кастомные маркеры ─────────────────────────────────────────────────────

  function makeIcon(provider) {
    const color = PROVIDER_COLOR[provider] || '#6366f1';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="30" height="42" viewBox="0 0 30 42">
      <path fill="${color}" stroke="white" stroke-width="1.5"
        d="M15 0C7.27 0 1 6.27 1 14c0 9.14 14 28 14 28S29 23.14 29 14C29 6.27 22.73 0 15 0z"/>
      <circle cx="15" cy="14" r="5" fill="white"/>
    </svg>`;
    return L.divIcon({ html: svg, className: '', iconSize: [30, 42],
                       iconAnchor: [15, 42], popupAnchor: [0, -44] });
  }

  // ── Рендер маркеров ───────────────────────────────────────────────────────

  function renderMarkers(list) {
    if (!markersLayer) return;
    markersLayer.clearLayers();

    list.forEach(pvz => {
      if (!pvz.lat || !pvz.lng) return;
      const marker = L.marker([pvz.lat, pvz.lng], { icon: makeIcon(pvz.provider) });

      marker.bindPopup(`
        <div style="min-width:200px">
          <div style="font-weight:700;margin-bottom:4px">${pvz.name}</div>
          <div style="font-size:12px;color:#555;margin-bottom:4px">${pvz.address}</div>
          ${pvz.work_time ? `<div style="font-size:11px;color:#888">${pvz.work_time}</div>` : ''}
          <button class="btn-select-pvz" data-pvz-id="${pvz.id}"
            style="margin-top:8px;padding:5px 12px;background:#cb11ab;color:#fff;border:none;
                   border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;width:100%">
            Выбрать этот пункт
          </button>
        </div>
      `);

      marker.on('popupopen', () => {
        setTimeout(() => {
          const btn = document.querySelector(`.btn-select-pvz[data-pvz-id="${pvz.id}"]`);
          if (btn) btn.addEventListener('click', () => {
            selectPvz(pvz);
            marker.closePopup();
          });
        }, 50);
      });

      marker.addTo(markersLayer);
    });

    if (list.length > 0) {
      const bounds = L.latLngBounds(list.map(p => [p.lat, p.lng]));
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }
  }

  // ── Выбор ПВЗ ─────────────────────────────────────────────────────────────

  function selectPvz(pvz) {
    selectedPvz = pvz;

    // Показываем адрес в read-only поле
    const display = qs('pvz-address-display');
    if (display) display.value = pvz.address;

    // Карточка выбранного ПВЗ
    const card = qs('selected-pvz-card');
    if (card) {
      card.style.display = 'block';
      card.innerHTML = `
        <div class="d-flex align-items-start gap-3">
          <div class="flex-shrink-0 mt-1">
            <span class="badge rounded-pill text-white fw-bold"
                  style="background:${PROVIDER_COLOR[pvz.provider] || '#6366f1'}">
              ${PROVIDER_LABEL[pvz.provider] || pvz.provider}
            </span>
          </div>
          <div class="flex-grow-1">
            <div class="fw-bold mb-1">${pvz.name}</div>
            <div class="small text-muted mb-1"><i class="bi bi-geo-alt me-1"></i>${pvz.address}</div>
            ${pvz.work_time ? `<div class="small text-muted"><i class="bi bi-clock me-1"></i>${pvz.work_time}</div>` : ''}
            ${pvz.phone    ? `<div class="small text-muted"><i class="bi bi-telephone me-1"></i>${pvz.phone}</div>` : ''}
          </div>
          <button type="button" class="btn btn-sm btn-outline-secondary flex-shrink-0"
                  id="btn-change-pvz">Изменить</button>
        </div>`;
      qs('btn-change-pvz')?.addEventListener('click', clearPvz);
    }

    highlightList(pvz.id);
  }

  function clearPvz() {
    selectedPvz = null;
    const display = qs('pvz-address-display');
    if (display) display.value = '';
    const card = qs('selected-pvz-card');
    if (card) { card.style.display = 'none'; card.innerHTML = ''; }
    highlightList(null);
  }

  function highlightList(id) {
    document.querySelectorAll('.pvz-list-item').forEach(el => {
      el.classList.toggle('pvz-list-item--active', el.dataset.pvzId === id);
    });
  }

  // ── Список ПВЗ ────────────────────────────────────────────────────────────

  function renderList(list) {
    const container = qs('pvz-list');
    if (!container) return;

    if (!list.length) {
      container.innerHTML = `<div class="text-muted text-center py-4 small">
        <i class="bi bi-exclamation-circle me-1"></i>Пункты не найдены для этого города
      </div>`;
      return;
    }

    container.innerHTML = list.map(pvz => `
      <div class="pvz-list-item p-2 mb-1 rounded" data-pvz-id="${pvz.id}"
           style="border:1px solid #e9ecef;transition:all .15s">
        <div class="d-flex align-items-start gap-2">
          <span class="badge text-white mt-1 flex-shrink-0"
                style="background:${PROVIDER_COLOR[pvz.provider]||'#6366f1'};font-size:10px">
            ${PROVIDER_LABEL[pvz.provider] || pvz.provider}
          </span>
          <div class="min-width-0">
            <div class="small fw-semibold lh-sm">${pvz.name}</div>
            <div class="small text-muted lh-sm text-truncate">${pvz.address}</div>
            ${pvz.work_time ? `<div style="font-size:10px;color:#aaa">${pvz.work_time}</div>` : ''}
          </div>
        </div>
      </div>
    `).join('');

    container.querySelectorAll('.pvz-list-item').forEach(el => {
      el.addEventListener('click', () => {
        const pvz = list.find(p => p.id === el.dataset.pvzId);
        if (!pvz) return;
        selectPvz(pvz);
        if (map) {
          map.setView([pvz.lat, pvz.lng], 16);
          markersLayer?.eachLayer(m => {
            const ll = m.getLatLng();
            if (Math.abs(ll.lat - pvz.lat) < 0.0001 &&
                Math.abs(ll.lng - pvz.lng) < 0.0001) {
              m.openPopup();
            }
          });
        }
      });
    });
  }

  // ── Загрузка ПВЗ с сервера ────────────────────────────────────────────────

  function loadPvz(city, provider) {
    const spinner  = qs('pvz-spinner');
    const mapWrap  = qs('pvz-map-wrap');
    const pvzCount = qs('pvz-count');

    if (spinner)  spinner.style.display = 'flex';
    if (mapWrap)  mapWrap.style.display = 'none';
    clearPvz();

    fetch(`/delivery/pvz?city=${encodeURIComponent(city)}&provider=${provider}`)
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error);
        allPvz = data.pvz || [];

        if (spinner) spinner.style.display = 'none';
        if (mapWrap) { mapWrap.style.display = 'flex'; }

        initMap(data.center[0], data.center[1]);
        setTimeout(() => map && map.invalidateSize(), 150);

        const filtered = filterPvz(allPvz, provider);
        renderMarkers(filtered);
        renderList(filtered);

        if (pvzCount)
          pvzCount.textContent = `${filtered.length} пункт${pvzSuffix(filtered.length)} выдачи`;
      })
      .catch(err => {
        if (spinner) spinner.style.display = 'none';
        renderList([]);  // shows "not found" message
        if (pvzCount) pvzCount.textContent = '';
        console.error('PVZ load error:', err);
      });
  }

  function filterPvz(list, provider) {
    return provider === 'all' ? list : list.filter(p => p.provider === provider);
  }

  // ── Переключатель типа доставки ───────────────────────────────────────────

  function onDeliveryTypeChange() {
    const val            = document.querySelector('input[name="delivery_type"]:checked')?.value;
    const courierSection = qs('section-courier');
    const pickupSection  = qs('section-pickup');
    if (val === 'pickup') {
      if (courierSection) courierSection.style.display = 'none';
      if (pickupSection)  pickupSection.style.display  = 'block';
      setTimeout(() => map && map.invalidateSize(), 200);
    } else {
      if (courierSection) courierSection.style.display = 'block';
      if (pickupSection)  pickupSection.style.display  = 'none';
      clearPvz();
    }
  }

  // ── Обновление фильтра провайдера ─────────────────────────────────────────

  function applyProvider(provider) {
    currentProvider = provider;
    document.querySelectorAll('[data-pvz-provider]').forEach(btn => {
      const active = btn.dataset.pvzProvider === provider;
      btn.classList.toggle('active', active);
      btn.classList.toggle('btn-wb', active);
      btn.classList.toggle('btn-outline-secondary', !active);
    });
    if (allPvz.length) {
      const filtered = filterPvz(allPvz, provider);
      renderMarkers(filtered);
      renderList(filtered);
      const pvzCount = qs('pvz-count');
      if (pvzCount)
        pvzCount.textContent = `${filtered.length} пункт${pvzSuffix(filtered.length)} выдачи`;
    }
  }

  // ── Инициализация страницы ───────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {

    // Тип доставки
    document.querySelectorAll('input[name="delivery_type"]').forEach(r =>
      r.addEventListener('change', onDeliveryTypeChange)
    );
    onDeliveryTypeChange();

    // Поиск
    qs('btn-search-pvz')?.addEventListener('click', () => {
      const city = qs('pvz-city')?.value.trim();
      if (!city) { qs('pvz-city')?.focus(); return; }
      loadPvz(city, currentProvider);
    });

    qs('pvz-city')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); qs('btn-search-pvz')?.click(); }
    });

    // Провайдерные фильтры
    document.querySelectorAll('[data-pvz-provider]').forEach(btn =>
      btn.addEventListener('click', () => applyProvider(btn.dataset.pvzProvider))
    );

    // Валидация + заполнение скрытых полей перед сабмитом
    qs('checkout-form')?.addEventListener('submit', e => {
      const type = document.querySelector('input[name="delivery_type"]:checked')?.value;

      if (type === 'pickup') {
        if (!selectedPvz) {
          e.preventDefault();
          const city = qs('pvz-city')?.value.trim();
          alert(city ? 'Выберите пункт выдачи на карте' : 'Введите город и выберите пункт выдачи');
          return;
        }
        // Заполняем скрытый address из выбранного ПВЗ
        const fa = qs('final-address');
        if (fa) fa.value = `ПВЗ ${PROVIDER_LABEL[selectedPvz.provider]}: ${selectedPvz.address}`;

      } else {
        // Курьер: берём из видимых полей
        const addr = qs('courier-address')?.value.trim();
        if (!addr) {
          e.preventDefault();
          qs('courier-address')?.focus();
          qs('courier-address')?.classList.add('is-invalid');
          return;
        }
        qs('courier-address')?.classList.remove('is-invalid');
        const fa = qs('final-address');
        if (fa) fa.value = addr;
      }

      // Телефон и комментарий
      const fp = qs('final-phone');
      const fc = qs('final-comment');
      if (fp) fp.value = qs('courier-phone')?.value || '';
      if (fc) fc.value = qs('courier-comment')?.value || '';
    });

    // Убираем красную рамку при вводе
    qs('courier-address')?.addEventListener('input', function () {
      this.classList.remove('is-invalid');
    });
  });

})();
