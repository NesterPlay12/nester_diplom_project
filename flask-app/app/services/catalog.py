from ..models import Product


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
