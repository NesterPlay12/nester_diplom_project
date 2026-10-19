"""Server-side access to official carrier pickup-point catalogs."""
import logging
import math
import os
import threading
import time

import requests
from flask import Blueprint, jsonify, request, current_app
from ..services.demo_pickup import demo_points, supported_cities

delivery_bp = Blueprint('delivery', __name__)
logger = logging.getLogger(__name__)

_CDEK_URL = 'https://api.cdek.ru/v2'
_CATALOG_MAX_PAGES = 100
_CITY_PAGE_SIZE = 100
_POINT_PAGE_SIZE = 1000
_token_cache = {'token': None, 'expires_at': 0.0, 'credentials': None, 'lock': threading.Lock()}
_points_cache = {}
_points_cache_lock = threading.Lock()
_request_history = {}
_request_history_lock = threading.Lock()

_CITY_CENTERS = {
    'москва': (55.7558, 37.6176),
    'санкт-петербург': (59.9343, 30.3351),
    'новосибирск': (54.9885, 82.9207),
    'екатеринбург': (56.8389, 60.6057),
    'казань': (55.8304, 49.0661),
    'нижний новгород': (56.3286, 44.0020),
    'красноярск': (56.0097, 92.8523),
    'краснодар': (45.0355, 38.9753),
    'омск': (54.9914, 73.3645),
    'самара': (53.2001, 50.1500),
    'ростов-на-дону': (47.2357, 39.7015),
    'уфа': (54.7388, 55.9721),
    'волгоград': (48.7080, 44.5133),
    'пермь': (58.0105, 56.2502),
    'воронеж': (51.6754, 39.2089),
}


def _cdek_credentials():
    client_id = os.environ.get('CDEK_CLIENT_ID', '').strip()
    client_secret = os.environ.get('CDEK_CLIENT_SECRET', '').strip()
    return (client_id, client_secret) if client_id and client_secret else None


def _cdek_token(credentials):
    if not credentials:
        return None
    cache = _token_cache
    with cache['lock']:
        if (
            cache['token']
            and cache['credentials'] == credentials
            and time.time() < cache['expires_at'] - 30
        ):
            return cache['token']
        try:
            response = requests.post(
                f'{_CDEK_URL}/oauth/token',
                params={
                    'grant_type': 'client_credentials',
                    'client_id': credentials[0],
                    'client_secret': credentials[1],
                },
                timeout=(3.05, 10),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('access_token'), str) or not payload['access_token'].strip():
                raise ValueError('Missing access token')
            cache['token'] = payload['access_token']
            cache['credentials'] = credentials
            cache['expires_at'] = time.time() + int(payload.get('expires_in', 3600))
            return cache['token']
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            logger.warning('CDEK token request failed: %s', type(error).__name__)
            cache.update(token=None, expires_at=0.0, credentials=None)
            return None


def _cdek_city_code(city, token):
    """Only accept one exact Russian city; a comma-separated region disambiguates."""
    city_name, _, region = city.partition(',')
    def normalize(value):
        return str(value).strip().casefold().replace('ё', 'е')

    matches = {}
    seen_pages = set()
    try:
        for page in range(_CATALOG_MAX_PAGES):
            response = requests.get(
                f'{_CDEK_URL}/location/cities',
                headers={'Authorization': f'Bearer {token}'},
                params={'city': city_name.strip(), 'country_codes': 'RU',
                        'size': _CITY_PAGE_SIZE, 'page': page},
                timeout=(3.05, 10),
            )
            response.raise_for_status()
            cities = response.json()
            if not isinstance(cities, list) or any(not isinstance(item, dict) for item in cities):
                return None
            signature = tuple(str(item.get('code')) for item in cities)
            if cities and signature in seen_pages:
                return None
            seen_pages.add(signature)
            for item in cities:
                if (
                    item.get('code')
                    and item.get('country_code') == 'RU'
                    and normalize(item.get('city', '')) == normalize(city_name)
                    and (not region.strip() or normalize(item.get('region', '')) == normalize(region))
                ):
                    matches[str(item['code'])] = item['code']
            if len(cities) < _CITY_PAGE_SIZE:
                return next(iter(matches.values())) if len(matches) == 1 else None
        return None
    except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
        logger.warning('CDEK city lookup failed: %s', type(error).__name__)
        return None


def _fetch_cdek(city):
    """Return official CDEK points, or an explicit unavailable reason (never mock data)."""
    credentials = _cdek_credentials()
    if not credentials:
        return [], 'Каталог СДЭК недоступен: подключите production-доступ API.'

    token = _cdek_token(credentials)
    if not token:
        return [], 'Не удалось авторизоваться в API СДЭК.'
    city_code = _cdek_city_code(city, token)
    if not city_code:
        return [], 'Не удалось однозначно определить город в каталоге СДЭК. Укажите «Город, регион» точно по каталогу или повторите позже.'

    result = []
    seen_pages = set()
    seen_codes = set()
    try:
        for page in range(_CATALOG_MAX_PAGES):
            response = requests.get(
                f'{_CDEK_URL}/deliverypoints',
                headers={'Authorization': f'Bearer {token}'},
                params={
                    'city_code': city_code,
                    'type': 'PVZ',
                    'is_handout': True,
                    'size': _POINT_PAGE_SIZE,
                    'page': page,
                },
                timeout=(3.05, 20),
            )
            response.raise_for_status()
            payload = response.json()
            raw = payload.get('items') if isinstance(payload, dict) else payload
            if not isinstance(raw, list):
                return [], 'API СДЭК вернул ответ неизвестного формата.'
            signature = tuple(str(point.get('code')) for point in raw if isinstance(point, dict))
            if raw and signature in seen_pages:
                return [], 'API СДЭК повторил страницу каталога. Попробуйте позже.'
            seen_pages.add(signature)
            for point in raw:
                if not isinstance(point, dict):
                    continue
                if (
                    point.get('is_handout') is not True
                    or point.get('type') != 'PVZ'
                    or point.get('status') != 'ACTIVE'
                ):
                    continue
                location = point.get('location') or {}
                if not isinstance(location, dict):
                    continue
                if (
                    location.get('country_code', 'RU') != 'RU'
                    or str(location.get('city_code', city_code)) != str(city_code)
                ):
                    continue
                try:
                    lat = float(location.get('latitude'))
                    lng = float(location.get('longitude'))
                except (TypeError, ValueError):
                    continue
                point_code = point.get('code')
                # The official OfficeDto has no required name; the code labels the point.
                name = point.get('name') or f'СДЭК {point_code}'
                address = location.get('address_full') or location.get('address')
                if (
                    not point_code
                    or not isinstance(name, str) or not name.strip()
                    or not isinstance(address, str) or not address.strip()
                    or not math.isfinite(lat) or not math.isfinite(lng)
                    or not -90 <= lat <= 90 or not -180 <= lng <= 180
                ):
                    continue
                if str(point_code) in seen_codes:
                    continue
                seen_codes.add(str(point_code))
                if not location.get('address_full'):
                    address = ', '.join(
                        value.strip() for value in
                        (location.get('region'), location.get('city'), address)
                        if isinstance(value, str) and value.strip()
                    )
                phones = point.get('phones') or []
                first_phone = phones[0] if isinstance(phones, list) and phones else {}
                if not isinstance(first_phone, dict):
                    first_phone = {}
                result.append({
                    'id': str(point_code),
                    'name': name.strip(),
                    'address': address.strip(),
                    'lat': lat,
                    'lng': lng,
                    'work_time': str(point.get('work_time') or ''),
                    'phone': str(first_phone.get('number', '') or ''),
                    'provider': 'cdek',
                })
            total_pages = response.headers.get('X-Total-Pages')
            if total_pages is not None:
                total_pages = int(total_pages)
                if total_pages < 0 or total_pages > _CATALOG_MAX_PAGES:
                    return [], 'Не удалось полностью загрузить каталог СДЭК.'
                if not raw and total_pages > page + 1:
                    return [], 'API СДЭК вернул неполный каталог.'
                if page + 1 >= total_pages:
                    break
            elif len(raw) < _POINT_PAGE_SIZE:
                break
        else:
            logger.error('CDEK pagination limit reached for city code %s', city_code)
            return [], 'Каталог СДЭК слишком большой для полной загрузки.'
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as error:
        logger.warning('CDEK pickup-point request failed: %s', type(error).__name__)
        return [], 'Не удалось загрузить каталог СДЭК. Попробуйте позже.'

    return result, None if result else 'В этом городе нет доступных пунктов СДЭК.'


def _get_cdek_points(city):
    key = city.casefold().strip()
    credentials = _cdek_credentials()
    if not credentials:
        return [], 'Каталог СДЭК недоступен: подключите production-доступ API.'
    now = time.time()
    with _points_cache_lock:
        cached = _points_cache.get(key)
        if cached and cached['expires_at'] > now and cached['credentials'] == credentials:
            return cached['points'], cached['reason']
    points, reason = _fetch_cdek(city)
    with _points_cache_lock:
        _points_cache.pop(key, None)
        while len(_points_cache) >= 64:
            _points_cache.pop(next(iter(_points_cache)))
        _points_cache[key] = {
            'points': points,
            'reason': reason,
            'credentials': credentials,
            'expires_at': now + (600 if not reason else 60),
        }
    return points, reason


def _request_is_within_limit(client_address):
    """Limit public catalog lookups to 30 requests per client per minute."""
    now = time.monotonic()
    key = client_address or 'unknown'
    with _request_history_lock:
        recent = [stamp for stamp in _request_history.get(key, []) if now - stamp < 60]
        if len(recent) >= 30:
            _request_history[key] = recent
            return False
        recent.append(now)
        _request_history[key] = recent
        if len(_request_history) > 4096:
            for address, stamps in list(_request_history.items()):
                if not stamps or now - stamps[-1] >= 60:
                    _request_history.pop(address, None)
        return True


def verify_pickup_point(provider, point_id, city):
    """Validate demo identities locally; re-fetch official catalogs for real points."""
    if not point_id or not city or len(city) > 120 or len(point_id) > 255:
        return None
    if current_app.config.get('DELIVERY_DEMO_MODE'):
        if provider != 'demo':
            return None
        return next((p for p in demo_points(city) if p['id'] == str(point_id)), None)
    if provider != 'cdek':
        return None
    points, reason = _fetch_cdek(city)
    if reason:
        return None
    return next((point for point in points if point['id'] == str(point_id)), None)


def _fetch_pochta(city):
    """No public official catalog credentials are configured for Russian Post."""
    if not os.environ.get('POCHTA_API_TOKEN', '').strip():
        return [], 'Каталог Почты России недоступен: подключите официальный API-доступ.'
    # The official Otpravka catalog endpoint is account-specific and is not the
    # parcel-label API. Do not guess endpoints or present scraped addresses as real.
    return [], 'Подключение официального каталога Почты России ещё не настроено.'


@delivery_bp.route('/delivery/pvz')
def get_pvz():
    if not _request_is_within_limit(request.remote_addr):
        response = jsonify({'error': 'Слишком много запросов. Повторите через минуту.'})
        response.status_code = 429
        response.headers['Retry-After'] = '60'
        return response
    city = request.args.get('city', '').strip()
    provider = request.args.get('provider', 'all')
    if not city:
        return jsonify({'error': 'Укажите город'}), 400
    if len(city) > 120:
        return jsonify({'error': 'Название города слишком длинное'}), 400
    if provider not in ('all', 'cdek', 'pochta', 'demo'):
        return jsonify({'error': 'Неизвестный оператор доставки'}), 400

    if current_app.config.get('DELIVERY_DEMO_MODE'):
        points = demo_points(city) if provider in ('all', 'demo') else []
        center = (
            [sum(p['lat'] for p in points) / len(points),
             sum(p['lng'] for p in points) / len(points)] if points else None
        )
        return jsonify({
            'pvz': points, 'center': center, 'city': city, 'mode': 'demo',
            'supported_cities': supported_cities(),
            'unavailable': {} if points else {
                'demo': 'Для этого города демонстрационные адреса пока не добавлены. '
                        'Выберите город из подсказок.',
            },
        })

    points = []
    unavailable = {}
    if provider in ('all', 'cdek'):
        result, reason = _get_cdek_points(city)
        points.extend(result)
        if reason:
            unavailable['cdek'] = reason
    if provider in ('all', 'pochta'):
        result, reason = _fetch_pochta(city)
        points.extend(result)
        if reason:
            unavailable['pochta'] = reason

    city_key = city.casefold().strip()
    if city_key in _CITY_CENTERS:
        center = _CITY_CENTERS[city_key]
    elif points:
        center = (
            sum(point['lat'] for point in points) / len(points),
            sum(point['lng'] for point in points) / len(points),
        )
    else:
        center = None

    return jsonify({
        'pvz': points,
        'center': list(center) if center else None,
        'city': city,
        'unavailable': unavailable,
    })
