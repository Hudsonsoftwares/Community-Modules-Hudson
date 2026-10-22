# -*- encoding: utf-8 -*-
"""Guard paths of the match endpoint: geofence, throttle, and the low
confidence exception.

These branches read fields that belong to the attendance base module
(site geofence columns, the rate limit counter, the exception API), so
they are the part of the controller a framework or platform change can
break without any other test noticing.
"""
import json
import random
import time

from odoo.tests import HttpCase, tagged

# Melbourne, and a point about 1.1 km north of it.
SITE_LAT = -37.813600
SITE_LNG = 144.963100
NEAR_LAT = -37.813700
FAR_LAT = -37.803600


def _unit_vector(seed):
    rng = random.Random(seed)
    vec = [rng.uniform(-1.0, 1.0) for _ in range(128)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


@tagged('post_install', '-at_install')
class TestFaceMatchGuards(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Guarded HTTP Site',
            'code': 'guard-http',
            'company_id': company.id,
            'geofence_enabled': True,
            'geofence_lat': SITE_LAT,
            'geofence_lng': SITE_LNG,
            'geofence_radius_m': 100,
        })
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Guarded HTTP device',
            'site_id': cls.site.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Guarded HTTP employee',
            'company_id': company.id,
        })
        cls.consent = cls.env['eh.hr.consent'].create({
            'employee_id': cls.employee.id,
            'consent_type': 'face',
            'company_id': company.id,
        })
        cls.consent.action_grant()
        cls.embedding = _unit_vector(4242)
        cls.template = cls.env['eh.hr.face.template'].create({
            'employee_id': cls.employee.id,
            'consent_id': cls.consent.id,
            'embedding': json.dumps(cls.embedding),
            'embedding_dim': 128,
            'company_id': company.id,
        })
        cls.Event = cls.env['eh.hr.kiosk.event']

    def _post(self, payload, token=None):
        resp = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps(payload),
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': token or self.device.device_token,
            },
        )
        return resp

    def _events(self, event_type):
        return self.Event.search([
            ('event_type', '=', event_type),
            ('device_id', '=', self.device.id),
        ])

    def test_geofence_without_coordinates_is_refused(self):
        resp = self._post({'embedding': self.embedding})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'match': False, 'reason': 'geofence_required'})
        self.assertTrue(self._events('geofence_fail'))

    def test_geofence_outside_radius_is_refused(self):
        resp = self._post({
            'embedding': self.embedding,
            'geofence': {'lat': FAR_LAT, 'lng': SITE_LNG, 'accuracy': 5},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['reason'], 'geofence_violation')
        failures = self._events('geofence_fail')
        self.assertTrue(failures.filtered(lambda e: 'exceeds radius' in (e.notes or '')))

    def test_geofence_inside_radius_matches(self):
        resp = self._post({
            'embedding': self.embedding,
            'geofence': {'lat': NEAR_LAT, 'lng': SITE_LNG, 'accuracy': 5},
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['match'], body)
        self.assertEqual(body['employee_id'], self.employee.id)
        self.assertEqual(body['site_code'], 'guard-http')
        self.assertTrue(self._events('geofence_pass'))

    def test_low_confidence_match_raises_an_attendance_exception(self):
        before = self.env['eh.hr.attendance.exception'].search_count([
            ('employee_id', '=', self.employee.id),
            ('exception_type', '=', 'identity_low_confidence'),
        ])
        resp = self._post({
            'embedding': _unit_vector(7),
            'geofence': {'lat': NEAR_LAT, 'lng': SITE_LNG},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['match'])
        self.assertEqual(resp.json()['reason'], 'below_threshold')
        after = self.env['eh.hr.attendance.exception'].search_count([
            ('employee_id', '=', self.employee.id),
            ('exception_type', '=', 'identity_low_confidence'),
        ])
        self.assertEqual(after, before + 1)

    def test_endpoint_is_rate_limited_per_device_token(self):
        # Fill the counter for the current window and the next one, so the
        # request cannot slip into a fresh window and pass.
        now = int(time.time())
        starts = (now - (now % 60), now - (now % 60) + 60)
        for window_start in starts:
            self.env.cr.execute(
                """
                INSERT INTO eh_hr_rate_limit (scope, key, window_start, hits)
                VALUES ('face.match', %s, %s, 1000)
                ON CONFLICT (scope, key, window_start)
                DO UPDATE SET hits = 1000
                """,
                (self.device.device_token, window_start),
            )
        resp = self._post({'embedding': self.embedding})
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json(), {'error': 'rate_limited'})
