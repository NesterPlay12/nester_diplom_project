"""Admin-only management of illustrative pickup locations, never carrier offices."""
import math
import uuid

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from ..models import db, DemoPickupPoint
from ..services.demo_pickup import managed_catalog, normalize_city
import requests
from ..services.pickup_geocoding import locate_building

admin_pickup_bp = Blueprint('admin_pickup', __name__)


@admin_pickup_bp.before_request
@login_required
def require_owner():
    if current_user.role != 'admin':
        abort(403)
    if not current_app.config.get('PICKUP_ADMIN_SCHEMA_READY', True):
        if request.is_json:
            return jsonify(error='Управление ПВЗ недоступно до обновления схемы базы данных.'), 503
        return render_template('admin/pickup_unavailable.html'), 503


@admin_pickup_bp.route('/geocode', methods=['POST'])
def geocode():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Некорректный запрос.'), 400
    try:
        return jsonify(locate_building(data))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except requests.RequestException:
        return jsonify(error='Поиск адресов временно недоступен. Повторите позже или проверьте координаты вручную.'), 503


def _save(point):
    row = db.session.get(DemoPickupPoint, point['id'])
    if row is None:
        row = DemoPickupPoint(id=point['id'])
        db.session.add(row)
    for field in ('city', 'name', 'address', 'lat', 'lng', 'work_time', 'is_active'):
        setattr(row, field, point[field])
    db.session.commit()


@admin_pickup_bp.route('/')
def index():
    search = request.args.get('search', '').strip()[:160]
    points = sorted(managed_catalog().values(), key=lambda p: (p['city'], p['address'], p['id']))
    if search:
        points = [p for p in points if search.casefold() in f"{p['city']} {p['address']} {p['name']}".casefold()]
    return render_template('admin/pickup_points.html', points=points, search=search)


@admin_pickup_bp.route('/add', methods=['GET', 'POST'])
@admin_pickup_bp.route('/<point_id>/edit', methods=['GET', 'POST'])
def edit(point_id=None):
    catalog = managed_catalog()
    original = catalog.get(point_id) if point_id else None
    if point_id and original is None:
        abort(404)
    point = dict(original or {
        'city': '', 'name': 'Пункт выдачи WildMarket', 'address': '',
        'lat': '', 'lng': '', 'work_time': 'График уточняется',
        'is_active': True,
    })
    errors = []
    if request.method == 'POST':
        for field, limit in (('city', 120), ('name', 160), ('address', 500), ('work_time', 200)):
            point[field] = ' '.join(request.form.get(field, '').split())
            if not point[field] or len(point[field]) > limit:
                errors.append(f'Поле «{dict(city="Город", name="Название", address="Адрес", work_time="Режим работы")[field]}» обязательно, максимум {limit} символов.')
        point['is_active'] = request.form.get('is_active') == 'on'
        for field, bound in (('lat', 90), ('lng', 180)):
            raw = request.form.get(field, '').strip().replace(',', '.')
            try:
                value = float(raw)
                if not math.isfinite(value) or not -bound <= value <= bound:
                    raise ValueError()
                point[field] = value
            except ValueError:
                point[field] = raw
                errors.append(f'Некорректная {"широта" if field == "lat" else "долгота"}.')
        if not errors:
            point['city'] = next(
                (p['city'] for p in catalog.values()
                 if normalize_city(p['city']) == normalize_city(point['city'])),
                point['city'],
            )
            # Keep old IDs when moving/renaming points; existing order snapshots
            # are independent and are deliberately never rewritten.
            if not point['address'].casefold().startswith(point['city'].casefold() + ','):
                point['address'] = f"{point['city']}, {point['address']}"
            if len(point['address']) > 500:
                errors.append('Полный адрес вместе с городом не должен превышать 500 символов.')
            if any(
                p['id'] != point_id
                and normalize_city(p['city']) == normalize_city(point['city'])
                and p['address'].casefold() == point['address'].casefold()
                for p in catalog.values()
            ):
                errors.append('Пункт с таким городом и адресом уже существует, в том числе среди отключённых.')
        if not errors:
            point['id'] = point_id or f'demo-{uuid.uuid4().hex[:16]}'
            try:
                _save(point)
            except IntegrityError:
                db.session.rollback()
                errors.append('Такой адрес уже сохранён другим администратором. Обновите список.')
            else:
                flash('Пункт выдачи сохранён. Изменения уже доступны на карте.', 'success')
                return redirect(url_for('admin_pickup.index'))
    return render_template('admin/pickup_edit.html', point=point, editing=bool(point_id), errors=errors), 400 if errors else 200


@admin_pickup_bp.route('/<point_id>/toggle', methods=['POST'])
def toggle(point_id):
    point = managed_catalog().get(point_id)
    if point is None:
        abort(404)
    desired = request.form.get('active')
    if desired not in ('0', '1'):
        abort(400)
    point['is_active'] = desired == '1'
    _save(point)
    flash('ПВЗ включён.' if point['is_active'] else 'ПВЗ отключён. Он больше не доступен для новых заказов.', 'success')
    return redirect(url_for('admin_pickup.index'))
