"""Account hardening tests; all records live in a disposable database."""
import os
import tempfile
import unittest
from unittest.mock import patch

from flask_login.utils import encode_cookie
from sqlalchemy import select

from app import create_app
from app.models import Category, Order, OrderItem, Product, User, db
from app.services.database_transfer import (
    DEMO_EMAILS, assert_safe_production_accounts, deactivate_demo_accounts, fingerprints,
)


class AccountSafetyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = create_app({
            'TESTING': True, 'ENVIRONMENT': 'testing', 'AUTO_INIT_SCHEMA': True,
            'WTF_CSRF_ENABLED': False, 'SECRET_KEY': 'account-safety-test-key',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{directory.name}/accounts.sqlite',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'SESSION_COOKIE_SECURE': False, 'REMEMBER_COOKIE_SECURE': False,
        })
        with self.app.app_context():
            for index, email in enumerate(DEMO_EMAILS):
                user = User(
                    username=f'demo{index}', email=email, role='seller',
                    google_id=f'demo-google-{index}',
                )
                user.set_password('old-demo-test-password')
                db.session.add(user)
            self.admin = User(username='owner', email='owner@example.test', role='admin')
            self.admin.set_password('real-admin-test-password')
            category = Category(name='Test', slug='test')
            db.session.add_all([self.admin, category])
            db.session.flush()
            demo = User.query.filter_by(email=DEMO_EMAILS[0]).one()
            self.demo_id, self.admin_id = demo.id, self.admin.id
            product = Product(
                name='Test', price=10, category_id=category.id,
                seller_id=demo.id, stock=2, is_approved=True,
            )
            order = Order(user_id=demo.id, total=10, address='Test')
            db.session.add_all([product, order])
            db.session.flush()
            db.session.add(OrderItem(
                order_id=order.id, product_id=product.id, product_name='Test',
                quantity=1, price=10,
            ))
            db.session.commit()

    def secure(self):
        with db.engine.begin() as connection:
            count = deactivate_demo_accounts(connection)
        db.session.expire_all()
        return count

    @staticmethod
    def preserved_users():
        columns = [
            c for c in User.__table__.c
            if c.name not in ('password_hash', 'is_active', 'has_local_password')
        ]
        return list(db.session.execute(select(*columns).order_by(User.id)))

    def test_hardening_preserves_every_record_and_relationship_and_is_idempotent(self):
        with self.app.app_context():
            with db.engine.connect() as connection:
                before = fingerprints(connection)
            preserved = self.preserved_users()
            admin_hash = db.session.get(User, self.admin_id).password_hash
            self.assertEqual(self.secure(), 5)
            self.assertEqual(preserved, self.preserved_users())
            self.assertEqual(admin_hash, db.session.get(User, self.admin_id).password_hash)
            for email in DEMO_EMAILS:
                user = User.query.filter_by(email=email).one()
                self.assertFalse(user.is_active)
                self.assertFalse(user.has_local_password)
                self.assertFalse(user.check_password('old-demo-test-password'))
            with db.engine.connect() as connection:
                after = fingerprints(connection)
            for name in before:
                self.assertEqual(before[name]['rows'], after[name]['rows'])
                if name != 'users':
                    self.assertEqual(before[name], after[name])
            self.assertEqual(self.secure(), 0)
            with db.engine.connect() as connection:
                self.assertEqual(after, fingerprints(connection))

    def test_hardening_rolls_back_with_callers_transaction(self):
        with self.app.app_context():
            with self.assertRaisesRegex(RuntimeError, 'abort'):
                with db.engine.begin() as connection:
                    deactivate_demo_accounts(connection)
                    raise RuntimeError('abort')
            self.assertTrue(db.session.get(User, self.demo_id).is_active)
            self.assertTrue(db.session.get(User, self.demo_id).check_password('old-demo-test-password'))

    def test_old_session_and_remember_cookies_cannot_access_protected_pages(self):
        session_client = self.app.test_client()
        remember_client = self.app.test_client()
        with session_client.session_transaction() as session:
            session['_user_id'] = str(self.demo_id)
            session['_fresh'] = True
        with self.app.app_context():
            remember_client.set_cookie('remember_token', encode_cookie(str(self.demo_id)))
            self.secure()
        admin_client = self.app.test_client()
        with admin_client.session_transaction() as session:
            session['_user_id'] = str(self.admin_id)
        response = admin_client.post(f'/admin/users/{self.demo_id}/toggle')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            demo = db.session.get(User, self.demo_id)
            self.assertFalse(demo.is_active)
            self.assertEqual(demo.google_id, 'demo-google-0')
        self.assertIn('Доступ отключён', admin_client.get('/admin/users').get_data(as_text=True))
        self.assertNotIn('Демо-доступ', admin_client.get('/admin/users').get_data(as_text=True))
        for client in (session_client, remember_client):
            for path in ('/account/', '/seller/', '/admin/', '/cart/checkout'):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 302)
                    self.assertIn('/auth/login', response.location)
        login_client = self.app.test_client()
        response = login_client.post('/auth/login', data={
            'email': DEMO_EMAILS[0], 'password': 'old-demo-test-password',
        })
        self.assertEqual(response.status_code, 200)
        with login_client.session_transaction() as session:
            self.assertNotIn('_user_id', session)

    def test_guard_requires_disabled_demos_and_a_real_active_administrator(self):
        with self.app.app_context():
            with self.assertRaisesRegex(RuntimeError, 'Active demo'):
                assert_safe_production_accounts()
            self.secure()
            assert_safe_production_accounts()
            self.admin = db.session.get(User, self.admin_id)
            self.admin.is_active = False
            db.session.commit()
            with self.assertRaisesRegex(RuntimeError, 'non-demo administrator'):
                assert_safe_production_accounts()

    def test_guard_recognizes_demo_email_case_and_whitespace(self):
        with self.app.app_context():
            self.secure()
            demo = db.session.get(User, self.demo_id)
            demo.email = f' {DEMO_EMAILS[0].upper()} '
            demo.is_active = True
            db.session.commit()
            with self.assertRaisesRegex(RuntimeError, 'Active demo'):
                assert_safe_production_accounts()

    def test_create_admin_rejects_demo_identity_and_production_mutation(self):
        import manage
        with patch('builtins.input', side_effect=['new-owner', DEMO_EMAILS[0]]):
            with patch('manage.create_app', return_value=self.app):
                with self.assertRaisesRegex(SystemExit, 'known demo'):
                    manage.create_admin()
        with patch.dict(os.environ, {'APP_ENV': 'production'}):
            with self.assertRaisesRegex(RuntimeError, 'development database'):
                manage.create_admin()


if __name__ == '__main__':
    unittest.main()
