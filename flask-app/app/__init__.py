from flask import Flask
from flask_login import LoginManager
from .models import db, User
from .config import Config


login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Пожалуйста, войдите в аккаунт'
    login_manager.login_message_category = 'warning'

    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.products import products_bp
    from .routes.cart import cart_bp
    from .routes.account import account_bp
    from .routes.seller import seller_bp
    from .routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(products_bp)
    app.register_blueprint(cart_bp, url_prefix='/cart')
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(seller_bp, url_prefix='/seller')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    with app.app_context():
        db.create_all()

    return app


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
