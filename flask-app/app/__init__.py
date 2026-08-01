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
        return {'google_oauth_enabled': bool(app.config.get('GOOGLE_CLIENT_ID'))}

    return app


def _run_migrations():
    """Добавляет новые колонки, если их ещё нет в БД."""
    with db.engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN google_id VARCHAR(100)"))
            conn.commit()
        except Exception:
            pass  # колонка уже есть


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
