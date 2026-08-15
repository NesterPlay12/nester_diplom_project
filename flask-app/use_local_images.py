"""Переводит товары на локальные изображения, доступные в опубликованном Flask-приложении."""
from app import create_app
from app.models import db, Product


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

app = create_app()

with app.app_context():
    updated = 0
    for product_id, image_url in IMAGE_BY_PRODUCT_ID.items():
        product = db.session.get(Product, product_id)
        if product:
            product.image_url = image_url
            updated += 1
    db.session.commit()
    print(f"Локальные изображения назначены для {updated} товаров.")