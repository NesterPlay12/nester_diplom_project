"""On-demand admin geocoding, not autocomplete. OSM attribution is shown in UI."""
import fcntl
import math
import re
import time
from contextlib import contextmanager

import requests
from flask import has_app_context
from sqlalchemy import text
from ..models import db


@contextmanager
def _request_slot():
    # PostgreSQL lock also coordinates separate production app instances.
    if has_app_context() and db.engine.dialect.name == 'postgresql':
        with db.engine.begin() as connection:
            acquired = connection.execute(
                text('SELECT pg_try_advisory_xact_lock(3921013)')
            ).scalar()
            if not acquired:
                raise ValueError('Поиск адреса уже выполняется. Повторите через несколько секунд.')
            try:
                yield
            finally:
                time.sleep(1.1)
    else:
        with open('/tmp/wildmarket-admin-geocoder.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                time.sleep(1.1)


def locate_building(data):
    params = {'format': 'jsonv2', 'addressdetails': 1, 'accept-language': 'ru'}
    expected_house = None
    if data.get('address'):
        address = str(data['address']).strip()
        city = str(data.get('city', '')).strip()
        if not city or len(city) > 120 or not address or len(address) > 500:
            raise ValueError('Введите город и адрес здания.')
        params.update(q=address if city.casefold() in address.casefold() else f'{city}, {address}', limit=1, countrycodes='ru')
        match = re.search(r'(?:,\s*|\s)(\d[^,]*)$', address)
        expected_house = re.sub(r'\s+', '', match[1]).casefold() if match else None
        endpoint = 'search'
    else:
        try:
            lat, lng = float(data['lat']), float(data['lng'])
            if not math.isfinite(lat) or not math.isfinite(lng) or abs(lat) > 90 or abs(lng) > 180:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('Некорректные координаты.') from None
        params.update(lat=lat, lon=lng, zoom=18)
        endpoint = 'reverse'
    # On-demand single requests only, never address autocomplete or bulk queries.
    with _request_slot():
        response = requests.get(
            f'https://nominatim.openstreetmap.org/{endpoint}',
            params=params,
            headers={'User-Agent': 'WildMarket-DemoPickupAdmin/1.0 (+https://wildmarket.su)'},
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    if endpoint == 'search':
        result = result[0] if isinstance(result, list) and result else {}
    address = result.get('address', {})
    house = address.get('house_number', '')
    road = address.get('road') or address.get('pedestrian')
    city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality')
    if not house or not road or not city:
        raise ValueError('Здание с адресом не найдено. Уточните улицу и номер дома.')
    if expected_house and re.sub(r'\s+', '', house).casefold() != expected_house:
        raise ValueError('Точный номер дома не найден. Уточните адрес или выберите другое здание на карте.')
    lat, lng = float(result['lat']), float(result['lon'])
    if not math.isfinite(lat) or not math.isfinite(lng) or abs(lat) > 90 or abs(lng) > 180:
        raise ValueError('Сервис вернул некорректные координаты.')
    return {'city': city, 'address': f'{city}, {road}, {house}', 'lat': lat, 'lng': lng}
