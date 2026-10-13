# WildMarket

Онлайн-площадка с каталогом товаров, продавцами, заказами и административной панелью. Приложение работает на Python/Flask.

## Запуск

- **Flask-приложение**: воркфлоу `WildMarket (Flask)` — порт 8000
- `cd flask-app && python manage.py create-admin` — создать администратора с интерактивным вводом пароля
- `cd flask-app && python seed.py --demo` — создать демонстрационные данные для локальной разработки
- `cd flask-app && python run.py` — запустить вручную
- `cd flask-app && python -m unittest discover -s tests -v` — запустить регрессионные тесты

## Стек

- Python 3.11
- Flask 3.x + Flask-SQLAlchemy + Flask-Login
- Flask-WTF CSRF protection
- SQLite (по умолчанию) / MySQL (через PyMySQL)
- Bootstrap 5 (CDN)
- Werkzeug (хэширование паролей)

## Где что лежит

- `flask-app/` — всё Python-приложение
- `flask-app/app/models.py` — все модели БД (User, Product, Category, Order, Review, Favorite, CartItem)
- `flask-app/app/routes/` — маршруты: main, auth, products, cart, account, seller, admin
- `flask-app/app/templates/` — Jinja2 шаблоны
- `flask-app/app/static/` — CSS и JS
- `flask-app/seed.py` — локальные демонстрационные данные (не запускаются приложением)
- `flask-app/manage.py` — административные команды
- `flask-app/wildberries.db` — SQLite база данных

## База данных

**Для локальной разработки**: SQLite (`flask-app/wildberries.db`).

**Для production**: подключить постоянную базу через `FLASK_DATABASE_URL` (приоритет), `MYSQL_URL` или `MYSQL_HOST`/`MYSQL_USER`/`MYSQL_PASSWORD`/`MYSQL_DB`. Локальный SQLite не подходит для autoscale deployment.
```
mysql+pymysql://user:password@localhost/wildberries?charset=utf8mb4
```
Production также требует `SESSION_SECRET`. Приложение не создаёт пользователей и демонстрационные товары при старте. Первый аккаунт администратора создаётся вручную командой `python manage.py create-admin`.

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
- Демонстрационные данные создавать только вручную для локальной разработки
- Admin-панель доступна ролям `admin` и `moderator`; назначать роль администратора может только `admin`
- Seller-панель доступна для ролей `seller` и `admin`
- Пункты выдачи берутся только из официальных каталогов операторов; фиктивные адреса не используются

## User preferences

- Стек: Python / Flask / MySQL (SQLite для разработки)
- Язык интерфейса: русский
