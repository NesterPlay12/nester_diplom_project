# WildMarket — Аналог Wildberries

Полноценный маркетплейс (дипломная работа) — аналог Wildberries на Python/Flask/SQLite (с поддержкой MySQL).

## Запуск

- **Flask-приложение**: воркфлоу `WildMarket (Flask)` — порт 8000
- `cd flask-app && python seed.py` — заполнить базу тестовыми данными (запустить один раз)
- `cd flask-app && python run.py` — запустить вручную

## Стек

- Python 3.11
- Flask 3.x + Flask-SQLAlchemy + Flask-Login
- SQLite (по умолчанию) / MySQL (через PyMySQL)
- Bootstrap 5 (CDN)
- Werkzeug (хэширование паролей)

## Где что лежит

- `flask-app/` — всё Python-приложение
- `flask-app/app/models.py` — все модели БД (User, Product, Category, Order, Review, Favorite, CartItem)
- `flask-app/app/routes/` — маршруты: main, auth, products, cart, account, seller, admin
- `flask-app/app/templates/` — Jinja2 шаблоны
- `flask-app/app/static/` — CSS и JS
- `flask-app/seed.py` — заполнение БД тестовыми данными
- `flask-app/wildberries.db` — SQLite база данных

## База данных

**По умолчанию**: SQLite (`flask-app/wildberries.db`) — работает без настройки.

**Для MySQL**: задать переменную окружения `FLASK_DATABASE_URL`:
```
mysql+pymysql://user:password@localhost/wildberries?charset=utf8mb4
```
Или задать отдельно: `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`.

## Тестовые аккаунты

| Роль | Email | Пароль |
|------|-------|--------|
| Администратор | admin@wildmarket.ru | admin123 |
| Модератор | moder@wildmarket.ru | moder123 |
| Продавец | seller1@wildmarket.ru | seller123 |
| Покупатель | ivan@example.ru | user123 |

## Функционал

**Покупатели:**
- Регистрация, вход, профиль
- Каталог товаров с фильтрами и поиском
- Страницы товаров с отзывами
- Корзина, оформление заказа
- История заказов, отмена
- Избранное

**Продавцы** (`/seller`):
- Добавление и редактирование товаров
- Статистика продаж
- Товары отправляются на модерацию

**Администраторы/Модераторы** (`/admin`):
- Dashboard со статистикой
- Модерация товаров (одобрить / отклонить)
- Управление пользователями (роли, блокировка)
- Управление заказами (смена статусов)
- Управление категориями (CRUD)
- Управление отзывами

## Архитектурные решения

- Flask Blueprints — каждый раздел в отдельном модуле
- Flask-SQLAlchemy ORM — поддержка SQLite и MySQL через одну конфигурацию
- Flask-Login — сессии и защита маршрутов через декораторы
- Jinja2 шаблоны — наследование от base.html, admin/dashboard.html
- Bootstrap 5 из CDN — без сборщика, максимальная простота

## Gotchas

- Не использовать переменную `DATABASE_URL` (она занята Node.js API) — для Flask использовать `FLASK_DATABASE_URL`
- Перед первым запуском выполнить `python seed.py` для заполнения БД
- Admin-панель доступна только для ролей `admin` и `moderator`
- Seller-панель доступна для ролей `seller` и `admin`

## User preferences

- Стек: Python / Flask / MySQL (SQLite для разработки)
- Язык интерфейса: русский
