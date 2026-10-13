from math import isfinite

from ..models import Product


def parse_price_filters(args):
    values = {}
    errors = []
    for name, label in (('min_price', 'Минимальная цена'), ('max_price', 'Максимальная цена')):
        raw = args.get(name, '').strip()
        if not raw:
            values[name] = None
            continue
        try:
            parsed = float(raw)
        except ValueError:
            parsed = float('nan')
        if not isfinite(parsed) or parsed < 0:
            errors.append(f'{label}: укажите неотрицательное число.')
            values[name] = None
        else:
            values[name] = parsed
    if (
        values['min_price'] is not None
        and values['max_price'] is not None
        and values['min_price'] > values['max_price']
    ):
        errors.append('Минимальная цена не может превышать максимальную.')
        values = {'min_price': None, 'max_price': None}
    return values['min_price'], values['max_price'], errors


def filter_by_price(query, min_price=None, max_price=None):
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    return query


def sort_products(query, sort):
    if sort == 'price_asc':
        return query.order_by(Product.price.asc(), Product.id.asc())
    if sort == 'price_desc':
        return query.order_by(Product.price.desc(), Product.id.asc())
    if sort == 'new':
        return query.order_by(Product.created_at.desc(), Product.id.desc())
    return query.order_by(Product.rating.desc(), Product.id.desc())
