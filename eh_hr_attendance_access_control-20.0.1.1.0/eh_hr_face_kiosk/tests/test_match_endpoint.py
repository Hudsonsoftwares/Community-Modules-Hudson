# -*- encoding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestFaceMatchEndpoint(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Match HTTP Site',
            'code': 'match-http',
            'company_id': company.id,
        })
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Match HTTP device',
            'site_id': cls.site.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Match HTTP employee',
            'company_id': company.id,
        })
        cls.consent = cls.env['eh.hr.consent'].create({
            'employee_id': cls.employee.id,
            'consent_type': 'face',
            'company_id': company.id,
        })
        cls.consent.action_grant()

        # Build a deterministic 128-dim embedding and store the same vector
        # as a template, so a self-match should return distance 0.
        import random
        rng = random.Random(99)
        vec = [rng.uniform(-1.0, 1.0) for _ in range(128)]
        norm = sum(v * v for v in vec) ** 0.5
        cls.embedding = [v / norm for v in vec]

        cls.template = cls.env['eh.hr.face.template'].create({
            'employee_id': cls.employee.id,
            'consent_id': cls.consent.id,
            'embedding': json.dumps(cls.embedding),
            'embedding_dim': 128,
            'company_id': company.id,
        })

    def test_match_without_token_returns_401(self):
        resp = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': [0.0] * 128}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_match_with_self_embedding_returns_match(self):
        resp = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': self.embedding}),
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': self.device.device_token,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['match'])
        self.assertEqual(body['employee_id'], self.employee.id)
        self.assertIn(body['action'], ('check_in', 'check_out'))

    def test_match_with_random_embedding_returns_no_match(self):
        import random
        rng = random.Random(7777)
        random_vec = [rng.uniform(-1.0, 1.0) for _ in range(128)]
        norm = sum(v * v for v in random_vec) ** 0.5
        random_vec = [v / norm for v in random_vec]

        resp = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': random_vec}),
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': self.device.device_token,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['match'])
        self.assertIn('reason', body)

    def test_match_toggles_check_in_then_check_out(self):
        # First match -> check_in
        resp1 = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': self.embedding}),
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': self.device.device_token,
            },
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()['action'], 'check_in')

        # Second match -> check_out
        resp2 = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': self.embedding}),
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': self.device.device_token,
            },
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()['action'], 'check_out')

    def test_match_with_invalid_embedding_returns_400(self):
        resp = self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': 'not-a-list'}),
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': self.device.device_token,
            },
        )
        self.assertEqual(resp.status_code, 400)
