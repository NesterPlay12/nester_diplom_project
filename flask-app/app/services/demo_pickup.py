"""Demonstration locations, not carrier offices or deliverable destinations.

Address/coordinate pairs checked with OpenStreetMap Nominatim. Randomness only
changes the display order: it never separates a marker from its street address.
Data attribution: https://www.openstreetmap.org/copyright (ODbL).
"""
import hashlib
import random
import re
from flask import current_app, has_app_context
from ..models import DemoPickupPoint

_LOCATIONS = {
    'Москва': [
        ('Тверская улица, 30/2 с5-6', 55.7693761, 37.5975376),
        ('улица Арбат, 12 с1', 55.7511069, 37.5959493),
        ('улица Покровка, 42 с10', 55.7621401, 37.6533836),
    ],
    'Санкт-Петербург': [
        ('Невский проспект, 28', 59.9358726, 30.3258989),
        ('Лиговский проспект, 30', 59.9266102, 30.3616563),
        ('Большая Конюшенная улица, 19/8', 59.9385679, 30.3225404),
    ],
    'Казань': [
        ('улица Баумана, 44', 55.7914018, 49.11208),
        ('Кремлёвская улица, 18 к5', 55.7909601, 49.1190647),
        ('Петербургская улица, 1', 55.786592, 49.1241156),
    ],
    'Новосибирск': [
        ('Красный проспект, 25/1', 55.0287121, 82.9195412),
        ('улица Ленина, 12', 55.0297333, 82.9133423),
    ],
    'Екатеринбург': [
        ('проспект Ленина, 24/8', 56.8368427, 60.5930693),
        ('улица Малышева, 51', 56.8361062, 60.6146045),
    ],
    'Нижний Новгород': [
        ('Большая Покровская улица, 43', 56.3181132, 43.9952372),
        ('улица Белинского, 61', 56.3162348, 44.0181493),
    ],
    'Красноярск': [
        ('проспект Мира, 91', 56.0109364, 92.8568321),
        ('улица Ленина, 120', 56.0127499, 92.849293),
    ],
    'Краснодар': [
        ('Красная улица, 122', 45.0348216, 38.9753368),
        ('Ставропольская улица, 107/10', 45.0241405, 39.0198946),
    ],
    'Омск': [
        ('улица Ленина, 10', 54.9866872, 73.3729606),
        ('проспект Карла Маркса, 18', 54.9680826, 73.3826578),
    ],
    'Самара': [
        ('Ленинградская улица, 64', 53.1868512, 50.0952998),
        ('Молодогвардейская улица, 204', 53.20195, 50.1089812),
    ],
    'Ростов-на-Дону': [
        ('Большая Садовая улица, 55/45', 47.2221369, 39.7154043),
        ('Пушкинская улица, 104', 47.2255574, 39.7178425),
    ],
    'Уфа': [
        ('улица Ленина, 5/4', 54.7249708, 55.9456764),
        ('улица Цюрупы, 97', 54.7366688, 55.9571648),
    ],
    'Волгоград': [
        ('проспект Ленина, 15', 48.7090005, 44.5191603),
        ('улица Мира, 19', 48.7134271, 44.5223473),
    ],
    'Пермь': [
        ('улица Ленина, 50', 58.0119048, 56.2423957),
        ('Комсомольский проспект, 27', 58.0095556, 56.2392461),
    ],
    'Воронеж': [
        ('проспект Революции, 38', 51.6679468, 39.2060399),
        ('Пушкинская улица, 2', 51.664451, 39.20353),
    ],
}


def normalize_city(city):
    normalized = ' '.join(city.casefold().replace('ё', 'е').split())
    return {'спб': 'санкт-петербург', 'петербург': 'санкт-петербург'}.get(normalized, normalized)


def _visible_pickup_label(value, fallback):
    value = str(value or '').strip()
    if not value or re.search(r'демо|демонстрац|demo', value, re.IGNORECASE):
        return fallback
    return value


def managed_catalog():
    """Defaults remain until explicitly overridden; disabled defaults never reappear."""
    points = {}
    for city, locations in _LOCATIONS.items():
        for address, lat, lng in locations:
            full_address = f'{city}, {address}'
            identifier = hashlib.sha256(full_address.encode()).hexdigest()[:16]
            point_id = f'demo-{identifier}'
            points[point_id] = {
                'id': point_id, 'provider': 'demo', 'city': city,
                'name': 'Точка WildMarket',
                'address': full_address, 'lat': lat, 'lng': lng,
                'work_time': 'График уточняется',
                'is_demo': True, 'is_active': True,
            }
    if has_app_context() and current_app.config.get('PICKUP_ADMIN_SCHEMA_READY', True):
        for row in DemoPickupPoint.query.all():
            points[row.id] = {
                'id': row.id, 'provider': 'demo', 'city': row.city,
                'name': _visible_pickup_label(row.name, 'Пункт выдачи'),
                'address': row.address, 'lat': row.lat, 'lng': row.lng,
                'work_time': _visible_pickup_label(row.work_time, 'График уточняется'),
                'is_demo': True, 'is_active': row.is_active,
            }
    return points


def demo_points(city=None):
    """Active catalogue across all cities unless an explicit city is requested."""
    normalized = normalize_city(city) if city else None
    points = [
        point for point in managed_catalog().values()
        if point['is_active']
        and (normalized is None or normalize_city(point['city']) == normalized)
    ]
    random.SystemRandom().shuffle(points)
    return points


def supported_cities():
    return sorted({
        point['city'] for point in managed_catalog().values() if point['is_active']
    })
