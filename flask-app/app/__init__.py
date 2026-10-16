import fcntl
import os
import threading
from flask import Flask, jsonify, request
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import event, inspect, text
from datetime import datetime, timezone
from contextlib import contextmanager
from .models import db, User
from .config import Config
from .oauth import init_oauth, oauth


login_manager = LoginManager()
# Proxy hops and mobile networks can change the observed address between requests.
# Basic protection marks such sessions non-fresh without silently signing users out.
login_manager.session_protection = 'basic'
csrf = CSRFProtect()
_schema_init_lock = threading.RLock()


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SESSION_SECRET must be configured outside development.')
    if (
        app.config.get('ENVIRONMENT') in ('production', 'staging')
        and app.config.get('SQLALCHEMY_DATABASE_URI', '').lower().startswith('sqlite')
    ):
        raise RuntimeError(
            'Production requires a persistent external database; SQLite is only for local development.'
        )

    # Корректно обрабатываем HTTPS-заголовки от Replit/nginx-прокси
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    with app.app_context():
        if db.engine.dialect.name == 'sqlite':
            @event.listens_for(db.engine, 'connect')
            def enable_sqlite_foreign_keys(connection, _record):
                cursor = connection.cursor()
                cursor.execute('PRAGMA foreign_keys=ON')
                cursor.close()
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

    if app.config.get('AUTO_INIT_SCHEMA'):
        if app.config.get('ENVIRONMENT') in ('production', 'staging'):
            raise RuntimeError('Schema initialization is disabled in production and staging.')
        with app.app_context():
            with _database_initialization_lock():
                db.create_all()
                _run_migrations()
    elif not app.config.get('TESTING'):
        with app.app_context():
            inspector = inspect(db.engine)
            for table in db.metadata.sorted_tables:
                if not inspector.has_table(table.name):
                    raise RuntimeError(
                        'Database schema is not initialized. Initialize development '
                        'with manage.py init-schema; managed production uses Publish.'
                    )
                present = {column['name'] for column in inspector.get_columns(table.name)}
                if not set(table.c.keys()).issubset(present):
                    raise RuntimeError('Database schema is outdated; apply the approved schema update.')

    if app.config.get('ENVIRONMENT') == 'production':
        # Preserve imported demo records, but never publish usable demo logins.
        from .services.database_transfer import DEMO_EMAILS
        with app.app_context():
            if User.query.filter(
                db.func.lower(User.email).in_(DEMO_EMAILS),
                User.is_active.is_(True),
            ).first():
                raise RuntimeError(
                    'Active demo accounts exist. Secure or deactivate them before production.'
                )

    # Передаём флаг Google OAuth во все шаблоны
    @app.context_processor
    def inject_google_oauth():
        return {
            'google_oauth_enabled': bool(
                app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET')
            ),
            'yandex_maps_api_key': app.config.get('YANDEX_MAPS_API_KEY', ''),
            'app_base_path': request.script_root.rstrip('/'),
            'current_year': datetime.now(timezone.utc).year,
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


@contextmanager
def _database_initialization_lock():
    """Serialize schema setup across local workflows and production workers."""
    engine = db.engine
    with _schema_init_lock:
        if engine.dialect.name == 'sqlite':
            database_path = engine.url.database
            if not database_path or database_path == ':memory:':
                yield
                return
            lock_path = os.path.abspath(database_path) + '.schema.lock'
            os.makedirs(os.path.dirname(lock_path), exist_ok=True)
            with open(lock_path, 'a', encoding='utf-8') as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            return

        with engine.connect() as connection:
            dialect = engine.dialect.name
            if dialect == 'postgresql':
                connection.execute(text('SELECT pg_advisory_lock(740345611)'))
                connection.commit()
            elif dialect == 'mysql':
                acquired = connection.execute(
                    text("SELECT GET_LOCK('wildmarket_schema_init', 30)")
                ).scalar()
                connection.commit()
                if acquired != 1:
                    raise RuntimeError('Could not acquire the database schema lock.')
            try:
                yield
            finally:
                if dialect == 'postgresql':
                    connection.execute(text('SELECT pg_advisory_unlock(740345611)'))
                    connection.commit()
                elif dialect == 'mysql':
                    connection.execute(text("SELECT RELEASE_LOCK('wildmarket_schema_init')"))
                    connection.commit()


def _run_migrations():
    """Apply small, idempotent schema upgrades while preserving existing rows."""
    engine = db.engine
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    migrations = {
        'users': {
            'google_id': 'VARCHAR(100)',
            'has_local_password': 'BOOLEAN NOT NULL DEFAULT TRUE',
        },
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
        'orders': {
            'payment_method': "VARCHAR(30) NOT NULL DEFAULT 'cash_on_delivery'",
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
            conn.execute(text(
                'UPDATE products SET stock = 0 WHERE stock IS NULL OR stock < 0'
            ))
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
            conn.execute(text(
                'UPDATE cart_items SET quantity = 1 WHERE quantity IS NULL OR quantity < 1'
            ))

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
                    quantity INTEGER NOT NULL DEFAULT 1,
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
                SELECT id, user_id, product_id, COALESCE(quantity, 1), created_at,
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
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    return user if user and user.is_active else None
