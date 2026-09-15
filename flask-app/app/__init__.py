from flask import Flask
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text
from .models import db, User
from .config import Config
from .oauth import init_oauth, oauth


login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Корректно обрабатываем HTTPS-заголовки от Replit/nginx-прокси
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Пожалуйста, войдите в аккаунт'
    login_manager.login_message_category = 'warning'

    init_oauth(app)

    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.products import products_bp
    from .routes.cart import cart_bp
    from .routes.account import account_bp
    from .routes.seller import seller_bp
    from .routes.admin import admin_bp
    from .routes.delivery import delivery_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(products_bp)
    app.register_blueprint(cart_bp, url_prefix='/cart')
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(seller_bp, url_prefix='/seller')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(delivery_bp)

    with app.app_context():
        db.create_all()
        _run_migrations()

    # Передаём флаг Google OAuth во все шаблоны
    @app.context_processor
    def inject_google_oauth():
        return {
            'google_oauth_enabled': bool(app.config.get('GOOGLE_CLIENT_ID')),
            'yandex_maps_api_key': app.config.get('YANDEX_MAPS_API_KEY', ''),
        }

    return app


def _run_migrations():
    """Добавляет новые колонки, если их ещё нет в БД."""
    with db.engine.connect() as conn:
        migrations = (
            "ALTER TABLE users ADD COLUMN google_id VARCHAR(100)",
            "ALTER TABLE products ADD COLUMN color_options TEXT DEFAULT ''",
            "ALTER TABLE products ADD COLUMN size_options TEXT DEFAULT ''",
            "ALTER TABLE cart_items ADD COLUMN selected_color VARCHAR(80)",
            "ALTER TABLE cart_items ADD COLUMN selected_size VARCHAR(40)",
            "ALTER TABLE order_items ADD COLUMN selected_color VARCHAR(80)",
            "ALTER TABLE order_items ADD COLUMN selected_size VARCHAR(40)",
        )
        for statement in migrations:
            try:
                conn.execute(text(statement))
                conn.commit()
            except Exception:
                pass  # колонка уже есть
        # Give the seeded apparel/electronics catalog useful defaults without
        # overwriting values a seller has already entered.
        for statement in (
            """UPDATE products SET color_options = 'Чёрный, Белый, Синий'
               WHERE (color_options IS NULL OR color_options = '')
                 AND category_id IN (SELECT id FROM categories
                                     WHERE slug IN ('womens-clothing','mens-clothing','shoes'))""",
            """UPDATE products SET size_options = 'S, M, L, XL'
               WHERE (size_options IS NULL OR size_options = '')
                 AND category_id IN (SELECT id FROM categories
                                     WHERE slug IN ('womens-clothing','mens-clothing'))""",
            """UPDATE products SET size_options = '36, 37, 38, 39, 40, 41, 42'
               WHERE (size_options IS NULL OR size_options = '')
                 AND category_id IN (SELECT id FROM categories WHERE slug = 'shoes')""",
            """UPDATE products SET color_options = 'Чёрный, Серебристый'
               WHERE (color_options IS NULL OR color_options = '')
                 AND category_id IN (SELECT id FROM categories
                                     WHERE slug IN ('smartphones','laptops'))""",
        ):
            try:
                conn.execute(text(statement))
                conn.commit()
            except Exception:
                pass


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
