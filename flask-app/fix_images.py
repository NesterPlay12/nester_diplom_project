"""
Обновляет URL изображений товаров в БД на работающие placehold.co ссылки.
Запуск: cd flask-app && python fix_images.py
"""
from app import create_app
from app.models import db, Product

# Карта: product_id -> новый URL изображения
IMAGE_MAP = {
    1:  'https://placehold.co/400x400/1a1a2e/ffffff?text=iPhone+15+Pro',
    2:  'https://placehold.co/400x400/1a1a1a/ffffff?text=Galaxy+S24+Ultra',
    3:  'https://placehold.co/400x400/f5f5f5/333333?text=MacBook+Air+M3',
    4:  'https://placehold.co/400x400/2c2c2c/ffffff?text=Sony+WH-1000XM5',
    5:  'https://placehold.co/400x400/ff6900/ffffff?text=Redmi+Note+13',
    6:  'https://placehold.co/400x400/f9a8d4/333333?text=Dress',
    7:  'https://placehold.co/400x400/3b82f6/ffffff?text=Jeans',
    8:  'https://placehold.co/400x400/10b981/ffffff?text=Sneakers',
    9:  'https://placehold.co/400x400/e879f9/ffffff?text=Beauty+Set',
    10: 'https://placehold.co/400x400/0ea5e9/ffffff?text=Mi+Band+8',
    11: 'https://placehold.co/400x400/f59e0b/ffffff?text=LEGO+City',
    12: 'https://placehold.co/400x400/7c3aed/ffffff?text=Harry+Potter',
}

app = create_app()

with app.app_context():
    updated = 0
    for product_id, new_url in IMAGE_MAP.items():
        product = db.session.get(Product, product_id)
        if product:
            product.image_url = new_url
            updated += 1
        else:
            # Для товаров с другими ID — общий плейсхолдер по ID
            pass

    # Обновляем все товары вне карты — на плейсхолдер по ID
    for product in Product.query.all():
        if product.id not in IMAGE_MAP:
            product.image_url = f'https://placehold.co/400x400/cb11ab/ffffff?text=Product+{product.id}'
            updated += 1

    db.session.commit()
    print(f"Обновлено {updated} товаров.")
    for p in Product.query.all():
        print(f"  [{p.id}] {p.name[:35]}: {p.image_url}")
