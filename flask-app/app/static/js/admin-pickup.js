/* Admin-only map helper: always use coordinates returned for the chosen address. */
(() => {
  const city = document.getElementById('point-city');
  const address = document.getElementById('point-address');
  const lat = document.getElementById('point-lat');
  const lng = document.getElementById('point-lng');
  const button = document.getElementById('point-locate');
  const status = document.getElementById('point-map-status');
  if (!city || !button) return;
  if (!window.ymaps) {
    status.textContent = 'Карта недоступна. Проверьте адрес и координаты вручную.';
    button.disabled = true;
    return;
  }
  ymaps.ready(() => {
    const hasCoordinates = lat.value !== '' && lng.value !== ''
      && Number.isFinite(Number(lat.value)) && Number.isFinite(Number(lng.value))
      && Math.abs(Number(lat.value)) <= 90 && Math.abs(Number(lng.value)) <= 180;
    const initial = hasCoordinates ? [Number(lat.value), Number(lng.value)] : [55.751244, 37.618423];
    const map = new ymaps.Map('point-map', { center: initial, zoom: hasCoordinates ? 16 : 10, controls: ['zoomControl'] });
    const marker = new ymaps.Placemark(initial, {}, { preset: 'islands#violetDotIcon' });
    if (hasCoordinates) map.geoObjects.add(marker);
    let revision = 0;
    [city, address, lat, lng].forEach(input => input.addEventListener('input', () => {
      revision += 1;
      button.disabled = false;
      status.textContent = 'Данные изменены. Сверьте адрес и координаты перед сохранением.';
    }));
    async function locate(query) {
      const current = ++revision;
      button.disabled = true;
      status.textContent = 'Ищем здание…';
      try {
        const response = await fetch(button.dataset.geocodeUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value,
          },
          body: JSON.stringify(Array.isArray(query)
            ? { lat: query[0], lng: query[1] }
            : { city: city.value.trim(), address: query }),
        });
        const found = await response.json();
        if (current !== revision) return;
        if (!response.ok) throw new Error(found.error || 'Не удалось определить адрес.');
        const coords = [found.lat, found.lng];
        city.value = found.city;
        address.value = found.address;
        lat.value = coords[0].toFixed(7);
        lng.value = coords[1].toFixed(7);
        marker.geometry.setCoordinates(coords);
        map.geoObjects.add(marker);
        map.setCenter(coords, 16);
        status.textContent = 'Адрес и координаты здания связаны. Проверьте данные и сохраните ПВЗ.';
      } catch (error) {
        if (current === revision) status.textContent = error.message || 'Не удалось определить адрес. Повторите поиск.';
      } finally {
        if (current === revision) button.disabled = false;
      }
    }
    button.addEventListener('click', () => {
      if (!city.value.trim() || !address.value.trim()) {
        status.textContent = 'Сначала введите город и адрес здания.';
        return;
      }
      const fullAddress = address.value.trim();
      locate(fullAddress.toLocaleLowerCase().includes(city.value.trim().toLocaleLowerCase())
        ? fullAddress : `${city.value.trim()}, ${fullAddress}`);
    });
    map.events.add('click', event => locate(event.get('coords')));
    status.textContent = 'Найдите адрес или выберите здание на карте. Это демонстрационный ПВЗ.';
  });
})();
