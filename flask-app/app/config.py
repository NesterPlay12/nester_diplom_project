import os
import re

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_db_url():
    url = os.environ.get('FLASK_DATABASE_URL')
    # Explicit owner-approved bridge to the managed database. Never change the
    # Node service's DATABASE_URL or copy its credential into another secret.
    if not url and os.environ.get('FLASK_DATABASE_SOURCE') == 'replit':
        url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('Configure FLASK_DATABASE_URL or FLASK_DATABASE_SOURCE=replit.')
    # Normalize provider URL spellings for SQLAlchemy.
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    if not url.startswith(('postgresql://', 'postgresql+psycopg2://')):
        raise RuntimeError('WildMarket requires PostgreSQL. SQLite and MySQL are disabled.')
    return url


def _engine_options():
    schema = os.environ.get('FLASK_DATABASE_SCHEMA', 'wildmarket')
    if not re.fullmatch(r'[a-z_][a-z0-9_]*', schema):
        raise RuntimeError('Invalid FLASK_DATABASE_SCHEMA.')
    return {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'connect_args': {'options': f'-csearch_path={schema}'},
    }


class Config:
    ENVIRONMENT = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).lower()
    SECRET_KEY = os.environ.get('SESSION_SECRET') or (
        'wildmarket-local-development-key' if ENVIRONMENT == 'development' else None
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _get_db_url()
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options()
    # Managed production schema is applied by Publish, never by web workers.
    AUTO_INIT_SCHEMA = False
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
