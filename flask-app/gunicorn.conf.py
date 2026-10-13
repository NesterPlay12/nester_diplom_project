"""Production Gunicorn settings; initialize the Flask app before worker forks."""
import os

workers = max(2, int(os.environ.get('WEB_CONCURRENCY', '2')))
preload_app = True
timeout = 60
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
capture_output = True
forwarded_allow_ips = '*'


def post_fork(server, worker):
    # The master performs database initialization once. Each worker starts with
    # a fresh SQLAlchemy connection pool after the fork.
    from run import app as flask_app
    from app.models import db

    with flask_app.app_context():
        db.engine.dispose(close=False)
