from math import isfinite
from urllib.parse import urlparse

from ..models import Category, db


def parse_product_form(form, current=None):
    """Validate common seller/admin product fields once at the request boundary."""
    errors = []
    name = form.get('name', current.name if current else '').strip()
    description = form.get('description', '').strip()
    brand = form.get('brand', '').strip()
    sku = form.get('sku', '').strip()
    colors = form.get('color_options', '').strip()
    sizes = form.get('size_options', '').strip()
    image_url = form.get('image_url', '').strip()

    if not name:
        errors.append('Укажите название товара.')
    if len(name) > 255:
        errors.append('Название товара не должно превышать 255 символов.')
    if len(description) > 10000:
        errors.append('Описание товара слишком длинное.')
    if len(brand) > 100 or len(sku) > 50:
        errors.append('Бренд или артикул превышает допустимую длину.')
    if len(colors) > 2000 or len(sizes) > 2000:
        errors.append('Список цветов или размеров слишком длинный.')
    if any(len(value.strip()) > 80 for value in colors.split(',')):
        errors.append('Название цвета не должно превышать 80 символов.')
    if any(len(value.strip()) > 40 for value in sizes.split(',')):
        errors.append('Название размера не должно превышать 40 символов.')

    price = _parse_number(form.get('price'), current.price if current else None)
    old_price = _parse_number(form.get('old_price'), None, allow_blank=True)
    stock = _parse_integer(form.get('stock'), current.stock if current else 0)
    category_id = _parse_integer(
        form.get('category_id'),
        current.category_id if current else None,
    )
    if price is None or price <= 0:
        errors.append('Укажите корректную цену больше нуля.')
    if old_price is not None and (old_price <= 0 or (price is not None and old_price <= price)):
        errors.append('Старая цена должна быть выше текущей цены.')
    if form.get('old_price', '').strip() and old_price is None:
        errors.append('Укажите корректную старую цену.')
    if stock is None or stock < 0:
        errors.append('Остаток должен быть целым числом от нуля.')
    if category_id is None or db.session.get(Category, category_id) is None:
        errors.append('Выберите существующую категорию.')

    if image_url:
        parsed = urlparse(image_url)
        valid_remote = parsed.scheme in ('http', 'https') and bool(parsed.netloc)
        valid_local = image_url.startswith('/static/') and not image_url.startswith('//')
        if len(image_url) > 255 or not (valid_remote or valid_local):
            errors.append('Ссылка на изображение должна быть HTTP(S) или локальным адресом /static/.')

    if errors:
        return None, errors
    return {
        'name': name,
        'description': description,
        'price': price,
        'old_price': old_price,
        'brand': brand,
        'sku': sku,
        'category_id': category_id,
        'stock': stock,
        'color_options': colors,
        'size_options': sizes,
        'image_url': image_url or (current.image_url if current else ''),
    }, []


def apply_product_form(product, values):
    for field, value in values.items():
        if field == 'image_url' and not value:
            continue
        setattr(product, field, value)


def _parse_number(value, default, allow_blank=False):
    if value is None or not value.strip():
        return None if allow_blank else default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _parse_integer(value, default):
    if value is None or not value.strip():
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 2147483647 else None
