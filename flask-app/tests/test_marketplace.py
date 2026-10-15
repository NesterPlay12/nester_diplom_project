import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, inspect

from app import create_app
from app import _migrate_cart_variant_constraint
from app.config import _get_db_url
from app.models import CartItem, Category, Order, OrderItem, Product, User, db
from app.services.product_input import parse_product_form


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

    def test_csrf_rejects_post_without_token(self):
        secure_app = create_app({
            'TESTING': True,
            'WTF_CSRF_ENABLED': True,
            'ENVIRONMENT': 'testing',
            'SECRET_KEY': 'csrf-test-secret',
            'SQLALCHEMY_DATABASE_URI': f"sqlite:///{os.path.join(self.temp_dir.name, 'csrf.sqlite')}",
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

    def test_mysql_urls_select_the_installed_pymysql_driver(self):
        with patch.dict(os.environ, {
            'FLASK_DATABASE_URL': 'mysql://test-user:test-password@db.example.test/wildmarket',
        }):
            self.assertEqual(
                _get_db_url(),
                'mysql+pymysql://test-user:test-password@db.example.test/wildmarket',
            )

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


if __name__ == '__main__':
    unittest.main()
