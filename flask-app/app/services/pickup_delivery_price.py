"""Straight-line pickup delivery pricing from central Novomoskovsk."""
from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt, isfinite

ORIGIN_CITY = 'Новомосковск'
ORIGIN_LAT = 54.0105
ORIGIN_LNG = 38.2915
BASE_FEE_RUB = Decimal('50.00')
PER_KM_RUB = Decimal('0.40')
EARTH_RADIUS_KM = 6371.0088


def pickup_delivery_settings():
    return {
        'origin_city': ORIGIN_CITY,
        'origin_lat': ORIGIN_LAT,
        'origin_lng': ORIGIN_LNG,
        'base_fee_rub': float(BASE_FEE_RUB),
        'per_km_rub': float(PER_KM_RUB),
    }


def calculate_pickup_delivery_price(point):
    """Return distance rounded to meters and fee rounded to kopecks."""
    try:
        lat = float(point['lat'])
        lng = float(point['lng'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('У выбранного пункта нет корректных координат.') from error

    if not isfinite(lat) or not isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError('У выбранного пункта нет корректных координат.')

    origin_lat = radians(ORIGIN_LAT)
    point_lat = radians(lat)
    delta_lat = point_lat - origin_lat
    delta_lng = radians(lng - ORIGIN_LNG)
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(origin_lat) * cos(point_lat) * sin(delta_lng / 2) ** 2
    )
    distance_km = round(
        2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, haversine))),
        3,
    )
    fee = (
        BASE_FEE_RUB + Decimal(str(distance_km)) * PER_KM_RUB
    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return distance_km, fee
