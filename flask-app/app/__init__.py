from flask import Flask, jsonify, request
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import inspect, text
from .models import db, User
from .config import Config
from .oauth import init_oauth, oauth


login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SESSION_SECRET must be configured outside development.')

    # Корректно обрабатываем HTTPS-заголовки от Replit/nginx-прокси
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    csrf.init_app(app)
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
            'app_base_path': request.script_root.rstrip('/'),
        }

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'geolocation=(self)')
        if request.is_secure and app.config.get('ENVIRONMENT') == 'production':
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Форма устарела. Обновите страницу и повторите действие.'}), 400
        return 'Форма устарела или недействительна. Обновите страницу и повторите действие.', 400

    return app


def _run_migrations():
    """Apply small, idempotent schema upgrades while preserving existing rows."""
    engine = db.engine
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    migrations = {
        'users': {'google_id': 'VARCHAR(100)'},
        'products': {
            'sku': 'VARCHAR(50)',
            'color_options': "TEXT DEFAULT ''",
            'size_options': "TEXT DEFAULT ''",
        },
        'cart_items': {
            'selected_color': 'VARCHAR(80)',
            'selected_size': 'VARCHAR(40)',
        },
        'order_items': {
            'selected_color': 'VARCHAR(80)',
            'selected_size': 'VARCHAR(40)',
        },
    }
    with engine.begin() as conn:
        for table, columns in migrations.items():
            if table not in tables:
                continue
            present = {column['name'] for column in inspect(conn).get_columns(table)}
            for column, column_type in columns.items():
                if column not in present:
                    conn.exec_driver_sql(
                        f'ALTER TABLE {table} ADD COLUMN {column} {column_type}'
                    )

        if 'products' in tables and 'categories' in tables:
            # Fill legacy catalog defaults only when sellers have not supplied variants.
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
                conn.execute(text(statement))

    if 'cart_items' in tables:
        _migrate_cart_variant_constraint(engine)


def _migrate_cart_variant_constraint(engine):
    """Replace the legacy one-line-per-product key with a variant-aware key."""
    inspector = inspect(engine)
    legacy = [
        item for item in inspector.get_unique_constraints('cart_items')
        if set(item.get('column_names') or ()) == {'user_id', 'product_id'}
    ]
    if not legacy:
        return

    dialect = engine.dialect.name
    if dialect == 'sqlite':
        with engine.begin() as conn:
            conn.exec_driver_sql("""
                CREATE TABLE cart_items__new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    created_at DATETIME,
                    selected_color VARCHAR(80) NOT NULL DEFAULT '',
                    selected_size VARCHAR(40) NOT NULL DEFAULT '',
                    CONSTRAINT uq_cart_item_variant
                        UNIQUE (user_id, product_id, selected_color, selected_size),
                    FOREIGN KEY(user_id) REFERENCES users (id),
                    FOREIGN KEY(product_id) REFERENCES products (id)
                )
            """)
            conn.exec_driver_sql("""
                INSERT INTO cart_items__new
                    (id, user_id, product_id, quantity, created_at, selected_color, selected_size)
                SELECT id, user_id, product_id, quantity, created_at,
                       COALESCE(selected_color, ''), COALESCE(selected_size, '')
                FROM cart_items
            """)
            conn.exec_driver_sql('DROP TABLE cart_items')
            conn.exec_driver_sql('ALTER TABLE cart_items__new RENAME TO cart_items')
        return

    preparer = engine.dialect.identifier_preparer
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE cart_items SET selected_color = '' WHERE selected_color IS NULL"
        )
        conn.exec_driver_sql(
            "UPDATE cart_items SET selected_size = '' WHERE selected_size IS NULL"
        )
        for item in legacy:
            name = preparer.quote(item['name'])
            if dialect == 'mysql':
                conn.exec_driver_sql(f'ALTER TABLE cart_items DROP INDEX {name}')
            else:
                conn.exec_driver_sql(f'ALTER TABLE cart_items DROP CONSTRAINT {name}')
        conn.exec_driver_sql(
            'ALTER TABLE cart_items ADD CONSTRAINT uq_cart_item_variant '
            'UNIQUE (user_id, product_id, selected_color, selected_size)'
        )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
