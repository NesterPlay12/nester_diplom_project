import os
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import requests

from sqlalchemy import create_engine, inspect

from app import create_app
from app import _migrate_cart_variant_constraint
from app.config import _get_db_url
from app.models import CartItem, Category, Order, OrderItem, Product, User, db
from app.services.product_input import parse_product_form
from app.routes import delivery


class MarketplaceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, 'test.sqlite')
        self.app = create_app({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'ENVIRONMENT': 'testing',
            'SECRET_KEY': 'test-only-session-secret',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'AUTO_INIT_SCHEMA': True,
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            self.category = Category(name='Техника', slug='tech-test')
            self.user = User(username='buyer', email='buyer@example.test', role='user')
            self.user.set_password('a-long-test-password')
            self.seller = User(username='seller', email='seller@example.test', role='seller')
            self.seller.set_password('a-long-test-password')
            db.session.add_all([self.category, self.user, self.seller])
            db.session.flush()
            self.product = Product(
                name='Наушники',
                description='Тестовый товар',
                price=100,
                category_id=self.category.id,
                seller_id=self.seller.id,
                stock=3,
                color_options='Чёрный, Белый',
                size_options='S, M',
                is_active=True,
                is_approved=True,
            )
            self.moderator = User(
                username='moderator',
                email='moderator@example.test',
                role='moderator',
            )
            self.moderator.set_password('a-long-test-password')
            db.session.add_all([self.product, self.moderator])
            db.session.commit()
            self.user_id = self.user.id
            self.category_id = self.category.id
            self.seller_id = self.seller.id
            self.product_id = self.product.id
            self.moderator_id = self.moderator.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def login(self, email='buyer@example.test'):
        return self.client.post('/auth/login', data={
            'email': email,
            'password': 'a-long-test-password',
        })

    def test_authenticated_session_survives_proxy_address_changes(self):
        self.login()
        for address in ('192.0.2.10', '192.0.2.11'):
            response = self.client.get('/account/', headers={'X-Forwarded-For': address})
            self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session['_user_id'], str(self.user_id))
            self.assertFalse(session['_fresh'])

    def test_blocked_account_cannot_keep_using_an_existing_session(self):
        self.login()
        with self.app.app_context():
            db.session.get(User, self.user_id).is_active = False
            db.session.commit()
        response = self.client.get('/account/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.location)
        response = self.client.post(f'/cart/add/{self.product_id}', data={'quantity': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.location)
        with self.app.app_context():
            self.assertEqual(CartItem.query.filter_by(user_id=self.user_id).count(), 0)

    def test_password_change_preserves_intended_spaces(self):
        self.login()
        password = '  a new exact password  '
        response = self.client.post('/account/settings', data={
            'username': 'buyer',
            'old_password': 'a-long-test-password',
            'new_password': password,
            'confirm_password': password,
        })
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertTrue(user.check_password(password))
            self.assertFalse(user.check_password(password.strip()))

    def test_product_validation_rejects_values_that_cannot_be_ordered(self):
        with self.app.app_context():
            valid = {
                'name': 'Тестовый товар', 'price': '100', 'stock': '2',
                'category_id': str(self.category_id),
            }
            cases = (
                {'old_price': 'NaN'},
                {'old_price': 'не число'},
                {'stock': str(2 ** 63)},
                {'category_id': str(2 ** 63)},
                {'color_options': 'а' * 81},
                {'size_options': 'а' * 41},
            )
            for invalid in cases:
                with self.subTest(invalid=invalid):
                    values, errors = parse_product_form({**valid, **invalid})
                    self.assertIsNone(values)
                    self.assertTrue(errors)
            values, errors = parse_product_form(valid)
            self.assertFalse(errors)
            self.assertEqual(values['stock'], 2)

    def test_checkout_shares_contact_fields_between_delivery_methods(self):
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={'quantity': '1'})
        response = self.client.get('/cart/checkout')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        contact_start = html.index('id="checkout-contact"')
        self.assertGreater(contact_start, html.index('id="section-pickup"'))
        self.assertGreater(html.index('id="courier-phone"'), contact_start)
        self.assertGreater(html.index('id="courier-comment"'), contact_start)
        self.assertEqual(html.count('id="courier-phone"'), 1)

    def test_variant_items_can_coexist_and_cannot_oversell(self):
        self.login()
        first = self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '1', 'color': 'Чёрный', 'size': 'S',
        })
        second = self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '2', 'color': 'Белый', 'size': 'M',
        })
        rejected = self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '1', 'color': 'Чёрный', 'size': 'M',
        })
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(rejected.status_code, 302)
        with self.app.app_context():
            rows = CartItem.query.filter_by(user_id=self.user_id).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(row.quantity for row in rows), 3)

    def test_checkout_decrements_stock_and_persists_order(self):
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '2', 'color': 'Чёрный', 'size': 'S',
        })
        response = self.client.post('/cart/checkout', data={
            'delivery_type': 'courier',
            'address': 'Казань, улица Тестовая, 1',
            'phone': '+70000000000',
            'comment': '',
            'payment_method': 'cash_on_delivery',
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Product, self.product_id).stock, 1)
            order = Order.query.one()
            self.assertEqual(order.total, 200)
            self.assertEqual(order.payment_method, 'cash_on_delivery')
            self.assertEqual(order.items[0].selected_color, 'Чёрный')
            self.assertEqual(CartItem.query.filter_by(user_id=self.user_id).count(), 0)

    def test_checkout_requires_a_usable_contact_phone(self):
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '1', 'color': 'Чёрный', 'size': 'S',
        })
        response = self.client.post('/cart/checkout', data={
            'delivery_type': 'courier',
            'address': 'Казань, улица Тестовая, 1',
            'phone': 'abc 1234567',
            'payment_method': 'cash_on_delivery',
        })
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(Order.query.count(), 0)
            self.assertEqual(db.session.get(Product, self.product_id).stock, 3)
            self.assertEqual(CartItem.query.filter_by(user_id=self.user_id).count(), 1)

    def test_pickup_checkout_rejects_unverified_point(self):
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '1', 'color': 'Чёрный', 'size': 'S',
        })
        with patch.dict(os.environ, {
            'CDEK_CLIENT_ID': '',
            'CDEK_CLIENT_SECRET': '',
            'POCHTA_API_TOKEN': '',
        }):
            response = self.client.post('/cart/checkout', data={
                'delivery_type': 'pickup',
                'pvz_provider': 'cdek',
                'pvz_id': 'invented-point',
                'pvz_city': 'Тула',
                'address': 'Invented address',
                'payment_method': 'cash_on_delivery',
            })
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(Order.query.count(), 0)
            self.assertEqual(db.session.get(Product, self.product_id).stock, 3)
            self.assertEqual(CartItem.query.filter_by(user_id=self.user_id).count(), 1)

    def test_pickup_checkout_saves_only_fresh_official_address(self):
        self.app.config['DELIVERY_DEMO_MODE'] = False
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={'quantity': '1'})
        official = DeliveryCatalogTestCase.point()
        with patch.dict(os.environ, {
            'CDEK_CLIENT_ID': 'test-client', 'CDEK_CLIENT_SECRET': 'test-secret',
        }), patch.object(delivery, '_cdek_token', return_value='test-token'), patch.object(
            delivery, '_cdek_city_code', return_value=1,
        ), patch.object(delivery.requests, 'get', return_value=DeliveryCatalogTestCase.response([official])) as get:
            response = self.client.post('/cart/checkout', data={
                'delivery_type': 'pickup', 'pvz_provider': 'cdek', 'pvz_id': 'TEST1',
                'pvz_city': 'Тула', 'phone': '+79990000000',
                'address': 'Подменённый адрес', 'payment_method': 'cash_on_delivery',
            })
        self.assertEqual(response.status_code, 302)
        get.assert_called_once()
        with self.app.app_context():
            order = Order.query.one()
            self.assertIn('Тула, Тестовая улица, 1', order.address)
            self.assertNotIn('Подменённый', order.address)
            self.assertEqual(order.status, 'pending')
            self.assertEqual(db.session.get(Product, self.product_id).stock, 2)
            self.assertEqual(CartItem.query.filter_by(user_id=self.user_id).count(), 0)

    def test_pickup_checkout_api_outage_does_not_accept_cached_point_or_change_cart(self):
        self.app.config['DELIVERY_DEMO_MODE'] = False
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={'quantity': '1'})
        with patch.dict(os.environ, {
            'CDEK_CLIENT_ID': 'test-client', 'CDEK_CLIENT_SECRET': 'test-secret',
        }), patch.object(delivery, '_cdek_token', return_value='test-token'), patch.object(
            delivery, '_cdek_city_code', return_value=1,
        ), patch.object(delivery.requests, 'get', side_effect=requests.Timeout()), patch.object(
            delivery, '_get_cdek_points', return_value=([{'id': 'TEST1'}], None),
        ) as cached:
            response = self.client.post('/cart/checkout', data={
                'delivery_type': 'pickup', 'pvz_provider': 'cdek', 'pvz_id': 'TEST1',
                'pvz_city': 'Тула', 'phone': '+79990000000', 'payment_method': 'cash_on_delivery',
            })
        self.assertEqual(response.status_code, 400)
        cached.assert_not_called()
        with self.app.app_context():
            self.assertEqual(Order.query.count(), 0)
            self.assertEqual(db.session.get(Product, self.product_id).stock, 3)
            self.assertEqual(CartItem.query.filter_by(user_id=self.user_id).count(), 1)

    def test_cancelling_order_restores_stock_once(self):
        with self.app.app_context():
            order = Order(
                user_id=self.user_id,
                status='pending',
                total=200,
                address='Test address',
            )
            db.session.add(order)
            db.session.flush()
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=self.product_id,
                product_name='Наушники',
                quantity=2,
                price=100,
            ))
            db.session.get(Product, self.product_id).stock = 1
            db.session.commit()
            order_id = order.id

        self.login()
        self.assertEqual(self.client.post(f'/account/orders/{order_id}/cancel').status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Product, self.product_id).stock, 3)
        self.assertEqual(self.client.post(f'/account/orders/{order_id}/cancel').status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Product, self.product_id).stock, 3)
            self.assertEqual(db.session.get(Order, order_id).status, 'cancelled')

    def test_moderator_cannot_grant_admin_role(self):
        self.client.post('/auth/login', data={
            'email': 'moderator@example.test',
            'password': 'a-long-test-password',
        })
        response = self.client.post(f'/admin/users/{self.user_id}/role', data={'role': 'admin'})
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, self.user_id).role, 'user')

    def test_login_rejects_external_next_redirect(self):
        response = self.client.post('/auth/login?next=%2F%2Fevil.example', data={
            'email': 'buyer@example.test',
            'password': 'a-long-test-password',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/')

    def test_register_validates_and_normalizes_account_identifiers(self):
        invalid = self.client.post('/auth/register', data={
            'username': 'new-user',
            'email': 'not-an-email',
            'password': 'a-long-test-password',
            'confirm_password': 'a-long-test-password',
        })
        self.assertEqual(invalid.status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(username='new-user').count(), 0)

        valid = self.client.post('/auth/register', data={
            'username': 'New-User',
            'email': 'NEW-USER@example.test',
            'phone': '',
            'password': 'a-long-test-password',
            'confirm_password': 'a-long-test-password',
        })
        self.assertEqual(valid.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(username='new-user').one()
            self.assertEqual(user.email, 'new-user@example.test')

    def test_google_only_account_can_set_password_but_linked_account_needs_current_one(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            user.google_id = 'google-only-test'
            user.has_local_password = False
            db.session.commit()

        self.login()
        response = self.client.post('/account/settings', data={
            'username': 'buyer',
            'phone': '',
            'address': '',
            'new_password': 'new-long-test-password',
            'confirm_password': 'new-long-test-password',
        })
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertTrue(user.has_local_password)
            self.assertTrue(user.check_password('new-long-test-password'))
            user.set_password('a-long-test-password')
            user.has_local_password = True
            db.session.commit()

        response = self.client.post('/account/settings', data={
            'username': 'buyer',
            'phone': '',
            'address': '',
            'new_password': 'another-long-password',
            'confirm_password': 'another-long-password',
        })
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertTrue(user.check_password('a-long-test-password'))

    def test_delivery_endpoint_never_fabricates_points(self):
        self.app.config['DELIVERY_DEMO_MODE'] = False
        with patch.dict(os.environ, {
            'CDEK_CLIENT_ID': '',
            'CDEK_CLIENT_SECRET': '',
            'POCHTA_API_TOKEN': '',
        }):
            response = self.client.get('/delivery/pvz?city=Тула')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['pvz'], [])
        self.assertIn('cdek', data['unavailable'])
        self.assertIn('pochta', data['unavailable'])

    def test_demo_points_have_stable_address_coordinates_in_all_supported_cities(self):
        from app.services.demo_pickup import demo_points, supported_cities
        self.assertEqual(len(supported_cities()), 15)
        for city in supported_cities():
            first = {p['id']: p for p in demo_points(city)}
            second = {p['id']: p for p in demo_points(city)}
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 2)
            for point in first.values():
                self.assertTrue(point['address'].startswith(city + ', '))
                self.assertTrue(point['is_demo'])
                self.assertEqual(point['provider'], 'demo')
                self.assertTrue(-90 <= point['lat'] <= 90)
                self.assertTrue(-180 <= point['lng'] <= 180)
        self.assertEqual(demo_points('Несуществующий город'), [])

    def test_demo_catalog_does_not_call_carrier_apis(self):
        with patch('app.routes.delivery._get_cdek_points', side_effect=AssertionError):
            response = self.client.get('/delivery/pvz?city=Казань')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['mode'], 'demo')
        self.assertGreater(len(response.json['pvz']), 0)
        self.assertTrue(all(p['is_demo'] for p in response.json['pvz']))

    def test_demo_selection_is_verified_and_saved_as_demo_order(self):
        self.login()
        self.client.post(f'/cart/add/{self.product_id}', data={
            'quantity': '1', 'color': 'Чёрный', 'size': 'S',
        })
        point = self.client.get('/delivery/pvz?city=Казань').json['pvz'][0]
        form = {
            'delivery_type': 'pickup', 'pvz_provider': 'demo',
            'pvz_id': point['id'], 'pvz_city': 'Москва',
            'address': 'forged address', 'phone': '+70000000000',
            'payment_method': 'cash_on_delivery',
        }
        self.assertEqual(self.client.post('/cart/checkout', data=form).status_code, 400)
        form['pvz_city'] = 'Казань'
        self.assertEqual(self.client.post('/cart/checkout', data=form).status_code, 302)
        with self.app.app_context():
            order = Order.query.one()
            self.assertIn('ДЕМО — не для реальной доставки', order.address)
            self.assertIn(point['address'], order.address)
            self.assertNotIn('forged address', order.address)

    def test_google_oauth_is_not_advertised_until_explicitly_enabled(self):
        self.app.config.update(
            GOOGLE_OAUTH_ENABLED=False,
            GOOGLE_CLIENT_ID='configured-test-client',
            GOOGLE_CLIENT_SECRET='configured-test-secret',
        )
        page = self.client.get('/auth/register')
        self.assertNotIn('Зарегистрироваться через Google', page.get_data(as_text=True))
        response = self.client.get('/auth/google')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/auth/login'))

    def test_admin_cleanup_deletes_only_cancelled_legacy_test_order(self):
        with self.app.app_context():
            db.session.get(User, self.user_id).role = 'admin'
            order = Order(
                user_id=self.user_id, total=2468, status='cancelled',
                address='Казань, Тестовая улица, 1',
            )
            db.session.add(order)
            db.session.flush()
            order.items.append(OrderItem(
                product_id=self.product_id,
                product_name='WildMarket Test Product bda3c2452be62a',
                quantity=2, price=1234,
            ))
            db.session.commit()
            order_id = order.id
            stock = db.session.get(Product, self.product_id).stock
        self.login()
        response = self.client.post(f'/admin/orders/{order_id}/delete-test', data={
            'confirm_order_id': str(order_id),
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Order, order_id))
            self.assertEqual(OrderItem.query.filter_by(order_id=order_id).count(), 0)
            self.assertEqual(db.session.get(Product, self.product_id).stock, stock)

    def test_admin_cleanup_cannot_delete_real_order(self):
        with self.app.app_context():
            db.session.get(User, self.user_id).role = 'admin'
            order = Order(
                user_id=self.user_id, total=2468, status='cancelled',
                address='Настоящий заказ покупателя',
            )
            db.session.add(order)
            db.session.commit()
            order_id = order.id
        self.login()
        response = self.client.post(f'/admin/orders/{order_id}/delete-test', data={
            'confirm_order_id': str(order_id),
        })
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Order, order_id))

    def test_csrf_rejects_post_without_token(self):
        secure_app = create_app({
            'TESTING': True,
            'WTF_CSRF_ENABLED': True,
            'ENVIRONMENT': 'testing',
            'SECRET_KEY': 'csrf-test-secret',
            'SQLALCHEMY_DATABASE_URI': f"sqlite:///{os.path.join(self.temp_dir.name, 'csrf.sqlite')}",
            'SQLALCHEMY_ENGINE_OPTIONS': {},
        })
        response = secure_app.test_client().post('/auth/login', data={
            'email': 'buyer@example.test',
            'password': 'a-long-test-password',
        })
        self.assertEqual(response.status_code, 400)

    def test_production_rejects_local_sqlite(self):
        with self.assertRaisesRegex(RuntimeError, 'persistent external database'):
            create_app({
                'ENVIRONMENT': 'production',
                'SECRET_KEY': 'test-only-session-secret',
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            })

    def test_legacy_databases_are_rejected(self):
        for url in ('mysql://db.example.test/wildmarket', 'sqlite:///:memory:'):
            with patch.dict(os.environ, {'FLASK_DATABASE_URL': url}):
                with self.assertRaisesRegex(RuntimeError, 'requires PostgreSQL'):
                    _get_db_url()

    def test_managed_database_requires_explicit_opt_in(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://example.test/db'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'Configure FLASK_DATABASE_URL'):
                _get_db_url()
        with patch.dict(os.environ, {
            'DATABASE_URL': 'postgresql://example.test/db',
            'FLASK_DATABASE_SOURCE': 'replit',
        }, clear=True):
            self.assertEqual(_get_db_url(), 'postgresql://example.test/db')

    def test_explicit_flask_url_takes_priority(self):
        with patch.dict(os.environ, {
            'FLASK_DATABASE_URL': 'postgres://flask.example.test/db',
            'DATABASE_URL': 'postgresql://node.example.test/db',
        }):
            self.assertEqual(_get_db_url(), 'postgresql://flask.example.test/db')

    def test_legacy_user_rows_survive_schema_upgrade(self):
        database_path = os.path.join(self.temp_dir.name, 'legacy.sqlite')
        connection = sqlite3.connect(database_path)
        connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                email VARCHAR(120) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20),
                phone VARCHAR(20),
                address TEXT,
                avatar_url VARCHAR(255),
                is_active BOOLEAN,
                created_at DATETIME
            );
            INSERT INTO users (id, username, email, password_hash, role, is_active)
            VALUES (44, 'legacy-user', 'legacy@example.test', 'hash-preserved', 'user', 1);
        """)
        connection.commit()
        connection.close()

        legacy_app = create_app({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'ENVIRONMENT': 'testing',
            'SECRET_KEY': 'migration-test-secret',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'AUTO_INIT_SCHEMA': True,
        })
        with legacy_app.app_context():
            migrated = db.session.get(User, 44)
            self.assertIsNotNone(migrated)
            self.assertEqual(migrated.username, 'legacy-user')
            self.assertEqual(migrated.password_hash, 'hash-preserved')
            self.assertTrue(migrated.has_local_password)

    def test_legacy_cart_migration_preserves_rows_and_adds_variant_key(self):
        database_path = os.path.join(self.temp_dir.name, 'legacy-cart.sqlite')
        engine = create_engine(f'sqlite:///{database_path}')
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql('CREATE TABLE products (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql("""
                CREATE TABLE cart_items (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    created_at DATETIME,
                    selected_color VARCHAR(80),
                    selected_size VARCHAR(40),
                    CONSTRAINT cart_items_user_id_product_id_key UNIQUE (user_id, product_id),
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(product_id) REFERENCES products(id)
                )
            """)
            connection.exec_driver_sql('INSERT INTO users (id) VALUES (7)')
            connection.exec_driver_sql('INSERT INTO products (id) VALUES (9)')
            connection.exec_driver_sql("""
                INSERT INTO cart_items (id, user_id, product_id, quantity, selected_color, selected_size)
                VALUES (15, 7, 9, 2, NULL, NULL)
            """)

        _migrate_cart_variant_constraint(engine)
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                'SELECT id, user_id, product_id, quantity, selected_color, selected_size FROM cart_items'
            ).one()
            self.assertEqual(tuple(row), (15, 7, 9, 2, '', ''))
        unique_constraints = inspect(engine).get_unique_constraints('cart_items')
        self.assertTrue(any(
            set(item['column_names']) == {
                'user_id', 'product_id', 'selected_color', 'selected_size',
            }
            for item in unique_constraints
        ))
        engine.dispose()


class DeliveryCatalogTestCase(unittest.TestCase):
    """Synthetic HTTP fixtures only: never used by the application or live catalog."""

    def setUp(self):
        from flask import Flask
        app = Flask(__name__)
        app.config['DELIVERY_DEMO_MODE'] = False
        context = app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.env = patch.dict(os.environ, {
            'CDEK_CLIENT_ID': 'test-client', 'CDEK_CLIENT_SECRET': 'test-secret',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        delivery._points_cache.clear()
        delivery._token_cache.update(token=None, expires_at=0, credentials=None)
        self.addCleanup(delivery._points_cache.clear)
        self.addCleanup(lambda: delivery._token_cache.update(
            token=None, expires_at=0, credentials=None))

    @staticmethod
    def response(payload):
        return Mock(json=Mock(return_value=payload), raise_for_status=Mock(), headers={})

    @staticmethod
    def city(code=1, name='Тула', region='Тульская область', country='RU'):
        return {'code': code, 'city': name, 'region': region, 'country_code': country}

    @staticmethod
    def point(code='TEST1'):
        return {
            'code': code, 'name': 'Тестовый пункт', 'type': 'PVZ', 'is_handout': True, 'status': 'ACTIVE',
            'location': {'latitude': 54.2, 'longitude': 37.6, 'city_code': 1,
                         'country_code': 'RU', 'city': 'Тула', 'region': 'Тульская область',
                         'address': 'Тестовая улица, 1',
                         'address_full': 'Тула, Тестовая улица, 1'},
        }

    def test_city_search_reads_all_pages_before_deciding(self):
        with patch.object(delivery, '_CITY_PAGE_SIZE', 1), patch.object(
            delivery.requests, 'get', side_effect=[
                self.response([self.city(2, 'Тула-2')]),
                self.response([self.city()]), self.response([]),
            ],
        ) as get:
            self.assertEqual(delivery._cdek_city_code(' ТУЛА ', 'test-token'), 1)
        self.assertEqual([c.kwargs['params']['page'] for c in get.call_args_list], [0, 1, 2])
        self.assertTrue(all(c.kwargs['params']['country_codes'] == 'RU' for c in get.call_args_list))

    def test_city_search_never_selects_first_partial_or_foreign_match(self):
        for rows in ([self.city(name='Тула-2')], [self.city(country='BY')], []):
            with self.subTest(rows=rows), patch.object(
                delivery.requests, 'get', return_value=self.response(rows),
            ):
                self.assertIsNone(delivery._cdek_city_code('Тула', 'test-token'))

    def test_same_name_cities_require_exact_region(self):
        rows = [self.city(1, 'Мирный', 'Архангельская область'),
                self.city(2, 'Мирный', 'Республика Саха (Якутия)')]
        with patch.object(delivery.requests, 'get', return_value=self.response(rows)):
            self.assertIsNone(delivery._cdek_city_code('Мирный', 'test-token'))
            self.assertEqual(delivery._cdek_city_code('мирный, Архангельская область', 'test-token'), 1)
            self.assertEqual(delivery._cdek_city_code('Мирный, Республика Саха (Якутия)', 'test-token'), 2)
            self.assertIsNone(delivery._cdek_city_code('Мирный, неизвестный регион', 'test-token'))

    def test_city_later_page_failure_and_repeated_pages_fail_closed(self):
        for second in (requests.Timeout(), self.response([self.city()])):
            with self.subTest(second=type(second).__name__), patch.object(
                delivery, '_CITY_PAGE_SIZE', 1,
            ), patch.object(delivery.requests, 'get', side_effect=[self.response([self.city()]), second]):
                self.assertIsNone(delivery._cdek_city_code('Тула', 'test-token'))

    def test_city_page_limit_and_malformed_payload_fail_closed(self):
        for payload in ({'errors': []}, [None], None):
            with self.subTest(payload=payload), patch.object(
                delivery.requests, 'get', return_value=self.response(payload),
            ):
                self.assertIsNone(delivery._cdek_city_code('Тула', 'test-token'))
        with patch.object(delivery, '_CITY_PAGE_SIZE', 1), patch.object(
            delivery, '_CATALOG_MAX_PAGES', 1,
        ), patch.object(delivery.requests, 'get', return_value=self.response([self.city()])):
            self.assertIsNone(delivery._cdek_city_code('Тула', 'test-token'))

    def fetch_points(self, pages, page_size=1000, limit=100):
        with patch.object(delivery, '_cdek_token', return_value='test-token'), patch.object(
            delivery, '_cdek_city_code', return_value=1,
        ), patch.object(delivery, '_POINT_PAGE_SIZE', page_size), patch.object(
            delivery, '_CATALOG_MAX_PAGES', limit,
        ), patch.object(delivery.requests, 'get', side_effect=pages) as get:
            result = delivery._fetch_cdek('Тула')
        return result, get.call_args_list

    def test_points_all_pages_and_full_address_coordinates(self):
        (points, reason), calls = self.fetch_points([
            self.response([self.point('A')]), self.response([self.point('B')]), self.response([]),
        ], page_size=1)
        self.assertIsNone(reason)
        self.assertEqual([p['id'] for p in points], ['A', 'B'])
        self.assertEqual(points[0]['address'], 'Тула, Тестовая улица, 1')
        self.assertEqual((points[0]['lat'], points[0]['lng']), (54.2, 37.6))
        self.assertEqual([c.kwargs['params']['page'] for c in calls], [0, 1, 2])

    def test_points_reject_invalid_coordinates_addresses_and_wrong_city(self):
        invalid = []
        for key, value in [('latitude', 'NaN'), ('latitude', 91), ('longitude', -181),
                           ('longitude', None), ('city_code', 2), ('country_code', 'BY')]:
            point = deepcopy(self.point())
            point['location'][key] = value
            invalid.append(point)
        for key, value in [('code', ''), ('is_handout', False), ('type', 'POSTAMAT'),
                           ('status', 'CLOSED'), ('status', None)]:
            point = deepcopy(self.point())
            point[key] = value
            invalid.append(point)
        point = deepcopy(self.point())
        point['location'].update(address='', address_full='')
        invalid.extend([point, None, {'location': 'invalid'}])
        (points, reason), _ = self.fetch_points([self.response(invalid + [self.point('GOOD')])])
        self.assertIsNone(reason)
        self.assertEqual([p['id'] for p in points], ['GOOD'])

    def test_points_error_or_unknown_format_never_returns_partial_catalog(self):
        for second in (requests.Timeout(), requests.HTTPError(), self.response({}),
                       self.response({'errors': []}), self.response(None),
                       self.response([self.point('A')])):
            with self.subTest(second=type(second).__name__):
                (points, reason), _ = self.fetch_points([
                    self.response([self.point('A')]), second,
                ], page_size=1)
                self.assertEqual(points, [])
                self.assertTrue(reason)
        (points, reason), _ = self.fetch_points([self.response([self.point()])], page_size=1, limit=1)
        self.assertEqual(points, [])
        self.assertTrue(reason)

    def test_token_errors_and_official_authorization_parameters(self):
        for payload in ({}, [], {'access_token': ''}):
            with self.subTest(payload=payload), patch.object(
                delivery.requests, 'post', return_value=self.response(payload),
            ):
                self.assertIsNone(delivery._cdek_token(('test-client', 'test-secret')))
        with patch.object(delivery.requests, 'post', return_value=self.response({
            'access_token': 'test-token', 'expires_in': 3600,
        })) as post:
            self.assertEqual(delivery._cdek_token(('test-client', 'test-secret')), 'test-token')
            self.assertEqual(delivery._cdek_token(('test-client', 'test-secret')), 'test-token')
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs['params']['grant_type'], 'client_credentials')

    def test_official_point_without_name_uses_code_not_invented_name(self):
        point = self.point()
        del point['name']
        (points, reason), _ = self.fetch_points([self.response([point])])
        self.assertIsNone(reason)
        self.assertEqual(points[0]['name'], 'СДЭК TEST1')

    def test_pagination_respects_total_pages_even_if_server_caps_page_size(self):
        first, second = self.response([self.point('A')]), self.response([self.point('B')])
        first.headers = second.headers = {'X-Total-Pages': '2'}
        (points, reason), calls = self.fetch_points([first, second])
        self.assertIsNone(reason)
        self.assertEqual([p['id'] for p in points], ['A', 'B'])
        self.assertEqual(len(calls), 2)

    def test_invalid_pagination_headers_fail_closed(self):
        for value in ('bad', '-1', '101'):
            response = self.response([self.point()])
            response.headers = {'X-Total-Pages': value}
            (points, reason), _ = self.fetch_points([response])
            self.assertEqual(points, [])
            self.assertTrue(reason)

    def test_cache_never_survives_removal_or_rotation_of_credentials(self):
        with patch.object(delivery, '_fetch_cdek', return_value=([{'id': 'A'}], None)) as fetch:
            self.assertTrue(delivery._get_cdek_points('Тула')[0])
            self.assertTrue(delivery._get_cdek_points('ТУЛА')[0])
            self.assertEqual(fetch.call_count, 1)
            with patch.dict(os.environ, {'CDEK_CLIENT_SECRET': ''}):
                self.assertEqual(delivery._get_cdek_points('Тула')[0], [])
            with patch.dict(os.environ, {'CDEK_CLIENT_SECRET': 'rotated-test-secret'}):
                delivery._get_cdek_points('Тула')
            self.assertEqual(fetch.call_count, 2)

    def test_checkout_verification_bypasses_browsing_cache(self):
        with patch.object(delivery, '_get_cdek_points', return_value=([{'id': 'A'}], None)) as cached:
            for points, reason in (([], 'API unavailable'), ([], None)):
                with patch.object(delivery, '_fetch_cdek', return_value=(points, reason)):
                    self.assertIsNone(delivery.verify_pickup_point('cdek', 'A', 'Тула'))
            with patch.object(delivery, '_fetch_cdek', return_value=([{'id': 'A'}], None)):
                self.assertEqual(delivery.verify_pickup_point('cdek', 'A', 'Тула'), {'id': 'A'})
            cached.assert_not_called()

    def test_russian_post_never_uses_unconfirmed_catalog(self):
        with patch.dict(os.environ, {'POCHTA_API_TOKEN': 'test-only'}), patch.object(
            delivery.requests, 'get',
        ) as get:
            points, reason = delivery._fetch_pochta('Тула')
            self.assertEqual(points, [])
            self.assertTrue(reason)
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
