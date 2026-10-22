"""A pending optional PVZ migration must not take the storefront offline."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import _check_schema_readiness, create_app
from app.models import DemoPickupPoint, User, db
from app.services.demo_pickup import demo_points, managed_catalog


class DeploymentReadinessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.uri = 'sqlite:///' + os.path.join(self.directory.name, 'readiness.sqlite')
        self.config = {
            'TESTING': True, 'ENVIRONMENT': 'testing',
            'SECRET_KEY': 'readiness-test-only',
            'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': self.uri,
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'AUTO_INIT_SCHEMA': True,
        }
        self.app = create_app(self.config)
        with self.app.app_context():
            admin = User(username='readiness-admin', email='readiness@example.invalid', role='admin')
            admin.set_password('readiness-test-password')
            db.session.add(admin)
            db.session.commit()
            self.admin_id = admin.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.directory.cleanup()

    def drop_pickup_table(self):
        with self.app.app_context():
            DemoPickupPoint.__table__.drop(db.engine)

    def check_readiness(self):
        with self.app.app_context():
            _check_schema_readiness(self.app)

    def test_replit_domain_redirects_to_custom_domain_preserving_path_and_query(self):
        response = self.app.test_client().get(
            '/catalog?q=shoes&page=2',
            base_url='https://wildmarkettest.replit.app',
        )
        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response.headers['Location'],
            'https://wildmarket.su/catalog?q=shoes&page=2',
        )
        self.assertEqual(
            self.app.test_client().get(
                '/', base_url='https://wildmarket.su',
            ).status_code,
            200,
        )

    def test_missing_optional_table_keeps_homepage_and_default_points_working(self):
        self.drop_pickup_table()
        self.check_readiness()
        self.assertFalse(self.app.config['PICKUP_ADMIN_SCHEMA_READY'])
        self.assertEqual(self.app.test_client().get('/').status_code, 200)
        response = self.app.test_client().get('/delivery/pvz?city=Москва&provider=demo')
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            points = managed_catalog()
            self.assertEqual(len(points), 33)
            self.assertEqual(len(demo_points('Москва')), 3)
            # No failed optional-table query has poisoned the request/session.
            self.assertEqual(db.session.get(User, self.admin_id).role, 'admin')

    def test_actual_app_start_without_optional_table_and_without_ddl(self):
        self.drop_pickup_table()
        config = {**self.config, 'TESTING': False, 'AUTO_INIT_SCHEMA': False}
        with patch.object(db, 'create_all', side_effect=AssertionError('startup DDL forbidden')):
            app = create_app(config)
        self.assertFalse(app.config['PICKUP_ADMIN_SCHEMA_READY'])
        self.assertEqual(app.test_client().get('/').status_code, 200)
        with app.app_context():
            self.assertFalse(inspect(db.engine).has_table('demo_pickup_points'))
            db.session.remove()
            db.engine.dispose()

    def test_admin_get_and_post_are_explicit_503_without_writes(self):
        self.drop_pickup_table()
        self.check_readiness()
        client = self.app.test_client()
        self.assertEqual(client.get('/admin/pickup-points/').status_code, 302)
        with client.session_transaction() as session:
            session['_user_id'] = str(self.admin_id)
            session['_fresh'] = True
        for path in ['/admin/pickup-points/', '/admin/pickup-points/add',
                     '/admin/pickup-points/demo-example/edit']:
            response = client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertIn('Управление ПВЗ временно недоступно', response.get_data(as_text=True))
        response = client.post('/admin/pickup-points/add', data={'city': 'test'})
        self.assertEqual(response.status_code, 503)
        response = client.post('/admin/pickup-points/geocode', json={'address': 'test'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('error', response.get_json())
        with self.app.app_context():
            self.assertEqual(User.query.count(), 1)

    def test_ready_optional_table_keeps_persistent_overrides(self):
        self.check_readiness()
        self.assertTrue(self.app.config['PICKUP_ADMIN_SCHEMA_READY'])
        with self.app.app_context():
            db.session.add(DemoPickupPoint(
                id='demo-readiness', city='Москва', name='Readiness',
                address='Test address', lat=55, lng=37, work_time='Test', is_active=True,
            ))
            db.session.commit()
            self.assertIn('demo-readiness', managed_catalog())

    def test_incomplete_optional_schema_is_explicitly_disabled(self):
        self.drop_pickup_table()
        with self.app.app_context():
            with db.engine.begin() as connection:
                connection.execute(text('CREATE TABLE demo_pickup_points (id VARCHAR(64) PRIMARY KEY)'))
        self.check_readiness()
        self.assertFalse(self.app.config['PICKUP_ADMIN_SCHEMA_READY'])

    def test_required_tables_still_fail_closed(self):
        with self.app.app_context():
            inspector = inspect(db.engine)
            original = inspector.has_table
            inspector.has_table = lambda name: False if name == 'orders' else original(name)
            with patch('app.inspect', return_value=inspector):
                with self.assertRaisesRegex(RuntimeError, 'Required database table is missing: orders'):
                    _check_schema_readiness(self.app)

    def test_outdated_required_table_still_fails_closed(self):
        with self.app.app_context():
            inspector = inspect(db.engine)
            original = inspector.get_columns
            inspector.get_columns = lambda name: (
                [column for column in original(name) if column['name'] != 'role']
                if name == 'users' else original(name)
            )
            with patch('app.inspect', return_value=inspector):
                with self.assertRaisesRegex(RuntimeError, 'Required database table is outdated: users'):
                    _check_schema_readiness(self.app)


if __name__ == '__main__':
    unittest.main()
