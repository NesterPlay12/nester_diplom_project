import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_db_url():
    url = (
        os.environ.get('FLASK_DATABASE_URL') or
        f'sqlite:///{os.path.join(BASE_DIR, "..", "wildberries.db")}'
    )
    # Render выдаёт postgres://, SQLAlchemy 2.x требует postgresql://
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


class Config:
    SECRET_KEY = os.environ.get('SESSION_SECRET', 'wildberries-dev-secret-2024')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = _get_db_url()

    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    PRODUCTS_PER_PAGE = 20
