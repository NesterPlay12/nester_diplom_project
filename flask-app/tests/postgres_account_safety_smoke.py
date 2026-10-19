"""Explicit check of backup hardening and production startup in an isolated schema.

Run: APP_ENV=development python tests/postgres_account_safety_smoke.py
Never modifies working records or publishes the application.
"""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import requests
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import User, db
from app.services.database_transfer import (
    DEMO_EMAILS, assert_safe_production_accounts, fingerprints,
    require_development, restore_development,
)


def main():
    require_development()
    working = create_app()
    schema = 'account_check_' + secrets.token_hex(8)
    process = None
    with working.app_context():
        engine = db.engine
        with engine.connect() as connection:
            before = fingerprints(connection)
            administrators = list(connection.execute(select(User.__table__).where(
                User.role == 'admin', User.is_active.is_(True),
                ~db.func.lower(db.func.trim(User.email)).in_(DEMO_EMAILS),
            )).mappings())
        assert administrators, 'A real active administrator must already exist.'
        assert_safe_production_accounts()
        if os.environ.get('WILDMARKET_ADMIN_PASSWORD'):
            assert any(
                User.query.filter_by(id=row['id']).one().check_password(
                    os.environ['WILDMARKET_ADMIN_PASSWORD']
                ) for row in administrators
            ), 'Configured owner credential does not match an active real administrator.'
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        isolated = create_app({
            'TESTING': True,
            'SQLALCHEMY_ENGINE_OPTIONS': {
                'connect_args': {'options': f'-csearch_path={schema}'},
            },
        })
        with isolated.app_context():
            db.create_all()
            restore_development(Path(__file__).resolve().parents[1] / 'migration-manifest.json')
            demos = User.query.filter(db.func.lower(User.email).in_(DEMO_EMAILS)).all()
            assert demos and all(not user.is_active and not user.has_local_password for user in demos)
            # The archival snapshot predates the owner's administrator. Copy only
            # that existing account into this disposable schema, never invent one.
            for row in administrators:
                if db.session.get(User, row['id']) is None:
                    db.session.execute(User.__table__.insert().values(**dict(row)))
            db.session.commit()
            assert_safe_production_accounts()
            demo = demos[0]
            demo_id = demo.id
            demo.is_active = True
            demo.has_local_password = True
            db.session.commit()
        env = dict(os.environ, FLASK_DATABASE_SCHEMA=schema, APP_ENV='production')
        failed = subprocess.run(
            [sys.executable, '-c', 'from app import create_app; create_app()'],
            env=env, capture_output=True, text=True, timeout=30,
        )
        assert failed.returncode != 0 and 'Active demo accounts exist' in failed.stderr
        subprocess.run(
            [sys.executable, 'manage.py', 'secure-demo-accounts', '--confirm'],
            env=dict(env, APP_ENV='development'), check=True, timeout=30,
        )
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        output = Path('../generated-artifacts/account-safety')
        output.mkdir(parents=True, exist_ok=True)
        with (output / 'production-start.log').open('w') as log:
            process = subprocess.Popen(
                ['bash', 'start.sh'], env=dict(env, PORT=str(port)),
                stdout=log, stderr=subprocess.STDOUT,
            )
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                assert process.poll() is None, 'Production failed to start; see private test log.'
                try:
                    response = requests.get(base + '/', timeout=2)
                    if response.status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError('Production startup timed out.')
            # Replay the former numeric Flask-Login identity in both cookie types.
            from flask_login.utils import encode_cookie
            with isolated.app_context():
                session_cookie = isolated.session_interface.get_signing_serializer(isolated).dumps({
                    '_user_id': str(demo_id), '_fresh': True,
                })
                remember_cookie = encode_cookie(str(demo_id))
            for cookie in (f'session={session_cookie}', f'remember_token={remember_cookie}'):
                for path in ('/account/', '/seller/', '/admin/'):
                    response = requests.get(
                        base + path, headers={'Cookie': cookie, 'X-Forwarded-Proto': 'https'},
                        allow_redirects=False, timeout=5,
                    )
                    assert response.status_code == 302 and '/auth/login' in response.headers['Location']
        print('PASS: real administrator confirmed, private snapshot restored safely, '
              'unsafe production blocked, secured production started, old cookies rejected.')
        with isolated.app_context():
            db.session.remove()
            db.engine.dispose()
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        with working.app_context():
            with engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            with engine.connect() as connection:
                assert fingerprints(connection) == before, 'Working records unexpectedly changed.'
        print('PASS: isolated schema removed; working database unchanged.')


if __name__ == '__main__':
    main()
