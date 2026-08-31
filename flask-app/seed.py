"""
Заполнение базы данных тестовыми данными.
Запуск: cd flask-app && python seed.py
"""
from app import create_app
from app.models import db, User, Category, Product

app = create_app()

with app.app_context():
    db.create_all()

    if User.query.count() > 0:
        print("База уже заполнена, пропускаем.")
        exit()

    admin = User(username='admin', email='admin@wildmarket.ru', role='admin', phone='+7-800-555-00-00', is_active=True)
    admin.set_password('admin123')
    db.session.add(admin)

    moderator = User(username='moderator', email='moder@wildmarket.ru', role='moderator', is_active=True)
    moderator.set_password('moder123')
    db.session.add(moderator)

    seller1 = User(username='seller_tech', email='seller1@wildmarket.ru', role='seller', is_active=True)
    seller1.set_password('seller123')
    db.session.add(seller1)

    seller2 = User(username='seller_fashion', email='seller2@wildmarket.ru', role='seller', is_active=True)
    seller2.set_password('seller123')
    db.session.add(seller2)

    buyer = User(username='ivan_petrov', email='ivan@example.ru', role='user', phone='+7-999-123-45-67', is_active=True)
    buyer.set_password('user123')
    db.session.add(buyer)

    db.session.flush()

    cats_data = [
        ('Электроника', 'electronics', '💻', None),
        ('Одежда', 'clothing', '👗', None),
        ('Обувь', 'shoes', '👟', None),
        ('Красота', 'beauty', '💄', None),
        ('Дом и сад', 'home', '🏠', None),
        ('Спорт', 'sport', '⚽', None),
        ('Детское', 'kids', '🧸', None),
        ('Книги', 'books', '📚', None),
    ]

    cats = {}
    for name, slug, icon, parent in cats_data:
        c = Category(name=name, slug=slug, icon=icon)
        db.session.add(c)
        cats[slug] = c

    db.session.flush()

    sub_cats = [
        ('Смартфоны', 'smartphones', '📱', 'electronics'),
        ('Ноутбуки', 'laptops', '💻', 'electronics'),
        ('Наушники', 'headphones', '🎧', 'electronics'),
        ('Мужская одежда', 'mens-clothing', '👔', 'clothing'),
        ('Женская одежда', 'womens-clothing', '👗', 'clothing'),
    ]

    for name, slug, icon, parent_slug in sub_cats:
        c = Category(name=name, slug=slug, icon=icon, parent_id=cats[parent_slug].id)
        db.session.add(c)
        cats[slug] = c

    db.session.flush()

    products_data = [
        ('iPhone 15 Pro 256GB', 'Флагманский смартфон Apple с процессором A17 Pro, камерой 48 Мп и USB-C. Цвет: титан. Дисплей 6.1"', 119990, 149990, 'Apple', 'smartphones', seller1.id, 50, 4.8, 342, '/static/uploads/products/iphone-15-pro.jpg'),
        ('Samsung Galaxy S24 Ultra', 'Флагман Samsung с S Pen, камерой 200 Мп и AI-функциями. 12GB RAM, 256GB.', 109990, 129990, 'Samsung', 'smartphones', seller1.id, 30, 4.7, 218, '/static/uploads/products/galaxy-s24-ultra.jpg'),
        ('MacBook Air M3 13"', 'Ноутбук Apple с чипом M3, 8GB RAM, 256GB SSD, 18 часов работы без зарядки.', 119990, 139990, 'Apple', 'laptops', seller1.id, 20, 4.9, 156, '/static/uploads/products/macbook-air-m3.jpg'),
        ('Sony WH-1000XM5', 'Беспроводные наушники с лучшим в классе шумоподавлением, 30 часов работы.', 29990, 39990, 'Sony', 'headphones', seller1.id, 45, 4.8, 891, '/static/uploads/products/sony-headphones.jpg'),
        ('Xiaomi Redmi Note 13 Pro', 'Смартфон с камерой 200 Мп, AMOLED 120 Гц, 5000 мАч, быстрая зарядка 67W.', 24990, 29990, 'Xiaomi', 'smartphones', seller1.id, 80, 4.5, 567, '/static/uploads/products/redmi-note-13.jpg'),
        ('Платье летнее миди', 'Лёгкое платье из 100% хлопка с цветочным принтом. Размеры 42-52.', 2990, 4990, 'FashionLine', 'womens-clothing', seller2.id, 120, 4.3, 234, '/static/uploads/products/summer-dress.jpg'),
        ('Джинсы прямые мужские', 'Классические прямые джинсы из денима 320г/м². Размеры 28-38.', 3490, 5990, 'DenimCo', 'mens-clothing', seller2.id, 90, 4.4, 178, '/static/uploads/products/mens-jeans.jpg'),
        ('Кроссовки беговые', 'Лёгкие беговые кроссовки с амортизацией EVA. Размеры 36-46.', 6990, 9990, 'RunMax', 'shoes', seller2.id, 60, 4.6, 312, '/static/uploads/products/running-shoes.jpg'),
        ('Набор для ухода за лицом', 'Комплекс из 5 средств: тоник, сыворотка, крем, маска, мицеллярная вода.', 3990, 6990, 'BeautyRus', 'beauty', seller2.id, 200, 4.7, 445, '/static/uploads/products/beauty-set.jpg'),
        ('Фитнес-браслет Mi Band 8', 'Умный браслет с AMOLED-экраном, 150+ режимов тренировок, SpO2, 16 дней работы.', 4990, 6990, 'Xiaomi', 'sport', seller1.id, 150, 4.5, 623, '/static/uploads/products/fitness-band.jpg'),
        ('Конструктор LEGO City', 'Набор LEGO "Полицейский участок", 668 деталей, для детей от 6 лет.', 5990, 7990, 'LEGO', 'kids', seller2.id, 40, 4.9, 189, '/static/uploads/products/lego-city.jpg'),
        ('Гарри Поттер: Полное собрание', 'Все 7 книг серии о Гарри Поттере в твёрдом переплёте. Перевод Mahon.', 4490, 5990, 'Азбука', 'books', seller2.id, 75, 4.9, 2341, '/static/uploads/products/harry-potter-books.jpg'),
    ]

    for index, (name, desc, price, old_price, brand, cat_slug, seller_id, stock, rating, reviews_count, img) in enumerate(products_data):
        p = Product(
            name=name, description=desc, price=price, old_price=old_price,
            brand=brand, category_id=cats[cat_slug].id, seller_id=seller_id,
            stock=stock, rating=rating, review_count=reviews_count,
            image_url=img, is_active=True, is_approved=True
        )
        if cat_slug in ('womens-clothing', 'mens-clothing', 'shoes'):
            p.color_options = 'Чёрный, Белый, Синий'
            p.size_options = 'S, M, L, XL' if cat_slug != 'shoes' else '36, 37, 38, 39, 40, 41, 42'
        elif cat_slug in ('smartphones', 'laptops'):
            p.color_options = 'Чёрный, Серебристый'
        db.session.add(p)

    db.session.commit()
    print("✅ База данных заполнена:")
    print(f"   Пользователи: {User.query.count()}")
    print(f"   Категории: {Category.query.count()}")
    print(f"   Товары: {Product.query.count()}")
    print()
    print("Тестовые аккаунты:")
    print("  Админ:     admin@wildmarket.ru / admin123")
    print("  Модератор: moder@wildmarket.ru / moder123")
    print("  Продавец:  seller1@wildmarket.ru / seller123")
    print("  Покупатель: ivan@example.ru / user123")
