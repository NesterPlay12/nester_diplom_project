"""Country-wide address browsing without weakening checkout point validation."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import render_template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.models import DemoPickupPoint, db
from app.routes.delivery import verify_pickup_point


class PickupCatalogTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'ENVIRONMENT': 'testing',
            'SECRET_KEY': 'pickup-catalog-test-only',
            'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'AUTO_INIT_SCHEMA': True,
            'DELIVERY_DEMO_MODE': True,
        })
        self.client = self.app.test_client()
        self.limit = patch('app.routes.delivery._request_is_within_limit', return_value=True)
        self.limit.start()

    def tearDown(self):
        self.limit.stop()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def all_points(self):
        response = self.client.get('/delivery/pvz?provider=demo')
        self.assertEqual(response.status_code, 200)
        return response.get_json()['pvz']

    def test_city_is_not_required_and_every_added_city_is_returned(self):
        points = self.all_points()
        self.assertEqual(len(points), 33)
        self.assertEqual(len({point['city'] for point in points}), 15)
        self.assertEqual(len({point['id'] for point in points}), 33)
        self.assertTrue(all(point['is_active'] and point['is_demo'] for point in points))
        for point in points:
            self.assertIn(point['city'], point['address'])
            self.assertTrue(-90 <= point['lat'] <= 90)
            self.assertTrue(-180 <= point['lng'] <= 180)

    def test_new_cities_and_edits_appear_without_old_city_filter(self):
        with self.app.app_context():
            db.session.add(DemoPickupPoint(
                id='demo-new-city', city='Тула', name='Новая точка',
                address='Тула, проспект Ленина, 2', lat=54.193, lng=37.617,
                work_time='', is_active=True,
            ))
            db.session.commit()
        point = next(p for p in self.all_points() if p['id'] == 'demo-new-city')
        self.assertEqual(point['city'], 'Тула')
        with self.app.app_context():
            self.assertIsNotNone(verify_pickup_point('demo', point['id'], 'Тула'))
            self.assertIsNone(verify_pickup_point('demo', point['id'], 'Москва'))
            row = db.session.get(DemoPickupPoint, point['id'])
            row.address = 'Тула, проспект Ленина, 4'
            db.session.commit()
        self.assertEqual(next(p for p in self.all_points() if p['id'] == point['id'])['address'],
                         'Тула, проспект Ленина, 4')
        with self.app.app_context():
            db.session.get(DemoPickupPoint, point['id']).is_active = False
            db.session.commit()
        self.assertNotIn(point['id'], {p['id'] for p in self.all_points()})

    def test_catalog_hides_legacy_demo_labels_from_point_name_and_hours(self):
        with self.app.app_context():
            db.session.add(DemoPickupPoint(
                id='demo-legacy-labels', city='Тула', name='Демонстрационный пункт',
                address='Тула, проспект Ленина, 2', lat=54.193, lng=37.617,
                work_time='Только демо', is_active=True,
            ))
            db.session.commit()
        point = next(p for p in self.all_points() if p['id'] == 'demo-legacy-labels')
        self.assertEqual(point['name'], 'Пункт выдачи')
        self.assertEqual(point['work_time'], 'График уточняется')

    def test_disabled_default_is_not_restored_by_all_city_mode(self):
        point = self.all_points()[0]
        with self.app.app_context():
            db.session.add(DemoPickupPoint(**{
                key: point[key] for key in
                ['id', 'city', 'name', 'address', 'lat', 'lng', 'work_time']
            }, is_active=False))
            db.session.commit()
        self.assertEqual(len(self.all_points()), 32)
        self.assertNotIn(point['id'], {p['id'] for p in self.all_points()})

    def test_explicit_city_queries_and_real_carrier_contract_are_preserved(self):
        response = self.client.get('/delivery/pvz?city=Москва&provider=demo')
        self.assertEqual(len(response.json['pvz']), 3)
        self.assertTrue(all(p['city'] == 'Москва' for p in response.json['pvz']))
        self.app.config['DELIVERY_DEMO_MODE'] = False
        with patch('app.routes.delivery._get_cdek_points') as carrier:
            response = self.client.get('/delivery/pvz?provider=all')
            self.assertEqual(response.status_code, 400)
            carrier.assert_not_called()
        self.assertEqual(self.client.get('/delivery/pvz?provider=unknown').status_code, 400)

    def test_checkout_has_global_map_without_city_picker_and_clear_delivery_limit(self):
        with self.app.test_request_context('/cart/checkout'):
            html = render_template('checkout.html', items=[], total=0)
        self.assertIn('data-catalog-scope="all"', html)
        self.assertNotIn('id="pvz-city"', html)
        self.assertNotIn('id="btn-search-pvz"', html)
        self.assertIn('id="btn-reload-pvz"', html)
        self.assertNotIn('Демонстрационный режим', html)
        self.assertNotIn('Демо-пункты', html)
        self.assertNotIn('Получение посылок по этим адресам пока недоступно.', html)
        self.assertNotIn('не действующие пункты выдачи', html)
        self.assertIn('id="pvz-city-selected"', html)


if __name__ == '__main__':
    unittest.main()
