import os
from urllib.parse import quote_plus

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_db_url():
    url = os.environ.get('FLASK_DATABASE_URL') or os.environ.get('MYSQL_URL')
    if not url and os.environ.get('MYSQL_HOST'):
        user = quote_plus(os.environ.get('MYSQL_USER', ''))
        password = quote_plus(os.environ.get('MYSQL_PASSWORD', ''))
        host = os.environ['MYSQL_HOST']
        database = os.environ.get('MYSQL_DB', 'wildmarket')
        credentials = f'{user}:{password}@' if user else ''
        url = f'mysql+pymysql://{credentials}{host}/{database}?charset=utf8mb4'
    if not url:
        url = f'sqlite:///{os.path.join(BASE_DIR, "..", "wildberries.db")}'
    # Normalize provider URL spellings for SQLAlchemy.
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    elif url.startswith('mysql://'):
        url = url.replace('mysql://', 'mysql+pymysql://', 1)
    return url


class Config:
    ENVIRONMENT = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).lower()
    SECRET_KEY = os.environ.get('SESSION_SECRET') or (
        'wildmarket-local-development-key' if ENVIRONMENT == 'development' else None
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _get_db_url()
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = ENVIRONMENT in ('production', 'staging')
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = ENVIRONMENT in ('production', 'staging')
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14

    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    PRODUCTS_PER_PAGE = 20
    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8

    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', '')
    YANDEX_MAPS_API_KEY = os.environ.get('YANDEX_MAPS_API_KEY', '')
