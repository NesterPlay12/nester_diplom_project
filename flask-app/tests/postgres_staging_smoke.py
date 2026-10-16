"""Run once explicitly: APP_ENV=development python tests/postgres_staging_smoke.py.

Uses an isolated PostgreSQL clone; never places test orders in the working DB.
Exercises actual Gunicorn HTTP, CSRF, secure sessions, registration and checkout.
"""
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from sqlalchemy import select, text

from app import create_app
from app.models import db, Product, User, Order, OrderItem, CartItem
from app.services.database_transfer import copy_rows, fingerprints, require_development


def main():
    require_development()
    app = create_app()
    schema = 'staging_' + secrets.token_hex(8)
    output = Path('../generated-artifacts/staging-check')
    output.mkdir(parents=True, exist_ok=True)
    process = None
    with app.app_context():
        engine = db.engine
        with engine.connect() as source:
            baseline = fingerprints(source)
            with engine.begin() as target:
                target.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                target.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                db.metadata.create_all(target)
                copy_rows(source, target)
        try:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            env = dict(
                os.environ, APP_ENV='staging', FLASK_ENV='staging',
                FLASK_DATABASE_SCHEMA=schema, PORT=str(port),
            )
            base = f'http://127.0.0.1:{port}'
            log_path = output / 'gunicorn.log'
            with log_path.open('w') as log:
                process = subprocess.Popen(
                    ['bash', 'start.sh'], env=env, stdout=log, stderr=log,
                )
            session = requests.Session()
            session.headers['X-Forwarded-Proto'] = 'https'
            session.headers['Referer'] = f'https://127.0.0.1:{port}/'

            def request(method, path, **kwargs):
                # Local HTTP test transport represents HTTPS terminated by proxy.
                # Assert Secure on responses before relaxing client transport only.
                response = session.request(method, base + path, timeout=15, **kwargs)
                if 'session=' in response.headers.get('Set-Cookie', ''):
                    assert 'Secure;' in response.headers['Set-Cookie']
                    assert 'HttpOnly;' in response.headers['Set-Cookie']
                for cookie in session.cookies:
                    cookie.secure = False
                return response

            for _ in range(80):
                if process.poll() is not None:
                    raise RuntimeError('Gunicorn exited; see generated staging log.')
                try:
                    response = request('GET', '/auth/register')
                    if response.status_code == 200:
                        break
                except requests.ConnectionError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError('Gunicorn did not start in time.')

            def token(path):
                response = request('GET', path)
                assert response.status_code == 200, (path, response.status_code)
                return re.search(r'name="csrf-token" content="([^"]+)"', response.text)[1]

            name = 'pgcheck_' + secrets.token_hex(5)
            email = name + '@example.test'
            password = secrets.token_urlsafe(24)
            assert request('POST', '/auth/register', data={}).status_code == 400
            response = request('POST', '/auth/register', data={
                'csrf_token': token('/auth/register'), 'username': name,
                'email': email, 'password': password,
                'confirm_password': password, 'phone': '+79990000001',
            }, allow_redirects=False)
            assert response.status_code == 302
            assert request('GET', '/account/').status_code == 200
            with engine.connect() as connection:
                connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                buyer_id = connection.execute(
                    select(User.id).where(User.email == email)
                ).scalar_one()
                product = connection.execute(select(Product).where(
                    Product.is_active.is_(True), Product.is_approved.is_(True),
                    Product.stock > 0,
                ).order_by(Product.id)).mappings().first()
                assert product is not None
            response = request('POST', f'/cart/add/{product["id"]}', data={
                'csrf_token': token('/'), 'quantity': '1',
            }, allow_redirects=False)
            assert response.status_code == 302
            response = request('POST', '/cart/checkout', data={
                'csrf_token': token('/cart/checkout'),
                'delivery_type': 'courier', 'address': 'Тестовый адрес staging',
                'phone': '+79990000001', 'payment_method': 'cash_on_delivery',
            }, allow_redirects=False)
            assert response.status_code == 302
            assert '/account/orders/' in response.headers['Location']
            assert request('GET', response.headers['Location']).status_code == 200
            with engine.connect() as connection:
                connection.exec_driver_sql(f'SET search_path TO "{schema}"')
                order = connection.execute(select(Order).where(
                    Order.user_id == buyer_id,
                )).mappings().one()
                assert order['id'] > max(
                    [row[0] for row in db.session.execute(select(Order.id))] or [0]
                )
                item = connection.execute(select(OrderItem).where(
                    OrderItem.order_id == order['id'],
                )).mappings().one()
                assert item['product_id'] == product['id']
                assert order['total'] == product['price']
                assert connection.execute(select(Product.stock).where(
                    Product.id == product['id'],
                )).scalar_one() == product['stock'] - 1
                assert not connection.execute(select(CartItem.id).where(
                    CartItem.user_id == buyer_id,
                )).first()
            # Verify persisted account also works in a fresh session.
            session.cookies.clear()
            response = request('POST', '/auth/login', data={
                'csrf_token': token('/auth/login'),
                'email': email, 'password': password,
            }, allow_redirects=False)
            assert response.status_code == 302
            assert request('GET', '/account/orders').status_code in (200, 308)
            with engine.connect() as source:
                assert fingerprints(source) == baseline, 'Working database changed during staging check.'
            report = {
                'gunicorn_staging': True, 'csrf_enforced': True,
                'registration': True, 'fresh_session_login': True,
                'checkout_persisted': True, 'stock_decremented_once': True,
                'sequence_ids_after_import': True, 'working_database_unchanged': True,
            }
            (output / 'report.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            db.session.remove()
            with engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


if __name__ == '__main__':
    main()
