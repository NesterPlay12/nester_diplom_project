"""Server-side access to official carrier pickup-point catalogs."""
import logging
import math
import os
import threading
import time

import requests
from flask import Blueprint, jsonify, request

delivery_bp = Blueprint('delivery', __name__)
logger = logging.getLogger(__name__)

_CDEK_URL = 'https://api.cdek.ru/v2'
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
            cache['token'] = payload['access_token']
            cache['credentials'] = credentials
            cache['expires_at'] = time.time() + int(payload.get('expires_in', 3600))
            return cache['token']
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            logger.warning('CDEK token request failed: %s', type(error).__name__)
            cache.update(token=None, expires_at=0.0, credentials=None)
            return None


def _cdek_city_code(city, token):
    try:
        response = requests.get(
            f'{_CDEK_URL}/location/cities',
            headers={'Authorization': f'Bearer {token}'},
            params={'city': city, 'size': 100},
            timeout=(3.05, 10),
        )
        response.raise_for_status()
        cities = response.json()
        normalized = city.casefold().strip()
        exact = next(
            (item for item in cities if str(item.get('city', '')).casefold().strip() == normalized),
            None,
        )
        chosen = exact or (cities[0] if cities else None)
        return chosen.get('code') if chosen else None
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
        return [], 'Не удалось определить город в каталоге СДЭК.'

    result = []
    try:
        for page in range(100):
            response = requests.get(
                f'{_CDEK_URL}/deliverypoints',
                headers={'Authorization': f'Bearer {token}'},
                params={
                    'city_code': city_code,
                    'type': 'PVZ',
                    'is_handout': True,
                    'size': 1000,
                    'page': page,
                },
                timeout=(3.05, 20),
            )
            response.raise_for_status()
            payload = response.json()
            raw = payload.get('items', []) if isinstance(payload, dict) else payload
            if not isinstance(raw, list):
                return [], 'API СДЭК вернул ответ неизвестного формата.'
            for point in raw:
                if not isinstance(point, dict):
                    continue
                location = point.get('location') or {}
                if not isinstance(location, dict):
                    continue
                try:
                    lat = float(location.get('latitude'))
                    lng = float(location.get('longitude'))
                except (TypeError, ValueError):
                    continue
                point_code = point.get('code')
                name = point.get('name')
                address = location.get('address') or location.get('address_full')
                if (
                    not point_code
                    or not isinstance(name, str) or not name.strip()
                    or not isinstance(address, str) or not address.strip()
                    or not math.isfinite(lat) or not math.isfinite(lng)
                    or not -90 <= lat <= 90 or not -180 <= lng <= 180
                ):
                    continue
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
            if len(raw) < 1000:
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
    now = time.time()
    with _points_cache_lock:
        cached = _points_cache.get(key)
        if cached and cached['expires_at'] > now:
            return cached['points'], cached['reason']
    points, reason = _fetch_cdek(city)
    with _points_cache_lock:
        _points_cache.pop(key, None)
        while len(_points_cache) >= 64:
            _points_cache.pop(next(iter(_points_cache)))
        _points_cache[key] = {
            'points': points,
            'reason': reason,
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
    """Validate submitted pickup details against the server-fetched official catalog."""
    if provider != 'cdek' or not point_id or not city:
        return None
    points, _reason = _get_cdek_points(city)
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
    if provider not in ('all', 'cdek', 'pochta'):
        return jsonify({'error': 'Неизвестный оператор доставки'}), 400

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
