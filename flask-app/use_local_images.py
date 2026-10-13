"""Assign bundled images to missing images in an explicitly selected local demo catalog."""
import argparse

from app import create_app
from app.models import db, Product


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    '--demo',
    action='store_true',
    help='Confirm that this command is being run against a local demo database.',
)
args = parser.parse_args()
if not args.demo:
    parser.error('This data-changing command requires the explicit --demo flag.')

app = create_app()
if app.config.get('ENVIRONMENT') != 'development':
    raise SystemExit('Bundled demo images may only be applied in development mode.')

IMAGE_BY_PRODUCT_ID = {
    1: "/static/uploads/products/iphone-15-pro.jpg",
    2: "/static/uploads/products/galaxy-s24-ultra.jpg",
    3: "/static/uploads/products/macbook-air-m3.jpg",
    4: "/static/uploads/products/sony-headphones.jpg",
    5: "/static/uploads/products/redmi-note-13.jpg",
    6: "/static/uploads/products/summer-dress.jpg",
    7: "/static/uploads/products/mens-jeans.jpg",
    8: "/static/uploads/products/running-shoes.jpg",
    9: "/static/uploads/products/beauty-set.jpg",
    10: "/static/uploads/products/fitness-band.jpg",
    11: "/static/uploads/products/lego-city.jpg",
    12: "/static/uploads/products/harry-potter-books.jpg",
}

with app.app_context():
    updated = 0
    for product_id, image_url in IMAGE_BY_PRODUCT_ID.items():
        product = db.session.get(Product, product_id)
        if product and not (product.image_url or '').strip():
            product.image_url = image_url
            updated += 1
    db.session.commit()
    print(f"Локальные изображения назначены для {updated} товаров.")