import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SESSION_SECRET', 'wildberries-dev-secret-2024')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'wildberries')

    MYSQL_URL = os.environ.get(
        'MYSQL_URL',
        f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}?charset=utf8mb4'
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'FLASK_DATABASE_URL',
        os.environ.get(
            'MYSQL_URL',
            f'sqlite:///{os.path.join(BASE_DIR, "..", "wildberries.db")}'
        )
    )

    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    PRODUCTS_PER_PAGE = 20
