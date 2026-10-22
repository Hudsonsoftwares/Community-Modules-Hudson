# -*- encoding: utf-8 -*-
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.eh_hr_attendance_base.controllers.kiosk import issue_pairing_pin


@tagged('post_install', '-at_install')
class TestKioskHttpEndpoints(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'HTTP Test Site',
            'code': 'http-test',
            'company_id': cls.env.company.id,
        })

    def test_pair_with_valid_pin_returns_token(self):
        pin = issue_pairing_pin(self.site.code)
        body = json.dumps({
            'site_code': self.site.code,
            'pin': pin,
            'device_name': 'Test device',
        })
        response = self.url_open(
            '/eh_hr/kiosk/pair',
            data=body,
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('device_token', payload)
        self.assertEqual(payload['site_code'], self.site.code)

        Device = self.env['eh.hr.kiosk.terminal'].sudo()
        device = Device.search([('device_token', '=', payload['device_token'])], limit=1)
        self.assertTrue(device)
        self.assertEqual(device.site_id, self.site)

    def test_pair_with_wrong_site_code_rejects(self):
        pin = issue_pairing_pin(self.site.code)
        response = self.url_open(
            '/eh_hr/kiosk/pair',
            data=json.dumps({'site_code': 'no-such-site', 'pin': pin}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 403)

    def test_pair_missing_pin_returns_400(self):
        response = self.url_open(
            '/eh_hr/kiosk/pair',
            data=json.dumps({'site_code': self.site.code}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 400)

    def test_heartbeat_without_token_returns_401(self):
        response = self.url_open(
            '/eh_hr/kiosk/heartbeat',
            data='{}',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 401)

    def test_heartbeat_with_valid_token_returns_site_config(self):
        """The heartbeat leg is what the kiosk shell polls: it must touch the
        device, log the event and hand back the site configuration.
        """
        device = self.env['eh.hr.kiosk.terminal'].sudo().create({
            'name': 'Heartbeat test',
            'site_id': self.site.id,
        })
        self.site.write({
            'geofence_enabled': True,
            'geofence_lat': -37.8136,
            'geofence_lng': 144.9631,
            'geofence_radius_m': 75,
        })
        # Age the last heartbeat so the burst guard does not answer instead.
        device.last_seen = fields.Datetime.now() - timedelta(minutes=5)
        self.env.flush_all()

        response = self.url_open(
            '/eh_hr/kiosk/heartbeat',
            data='{}',
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': device.device_token,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['site_code'], self.site.code)
        self.assertEqual(payload['idle_seconds'], self.env.company.eh_hr_kiosk_idle_seconds)
        self.assertEqual(payload['geofence']['enabled'], True)
        self.assertEqual(payload['geofence']['radius_m'], 75)

        device.invalidate_recordset()
        self.assertGreater(device.last_seen, fields.Datetime.now() - timedelta(minutes=1))
        events = self.env['eh.hr.kiosk.event'].sudo().search([
            ('event_type', '=', 'device_heartbeat'),
            ('device_id', '=', device.id),
        ])
        self.assertTrue(events)

    def test_heartbeat_burst_is_rate_limited(self):
        """A heartbeat within the minimum interval of the previous one is
        refused. Nothing exercised the soft burst guard before.
        """
        device = self.env['eh.hr.kiosk.terminal'].sudo().create({
            'name': 'Burst test',
            'site_id': self.site.id,
        })
        device.last_seen = fields.Datetime.now()
        self.env.flush_all()

        response = self.url_open(
            '/eh_hr/kiosk/heartbeat',
            data='{}',
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': device.device_token,
            },
        )
        self.assertEqual(response.status_code, 429)

    def test_heartbeat_with_revoked_token_returns_401(self):
        device = self.env['eh.hr.kiosk.terminal'].sudo().create({
            'name': 'Revoked test',
            'site_id': self.site.id,
        })
        token = device.device_token
        device.action_revoke()
        self.env.flush_all()

        response = self.url_open(
            '/eh_hr/kiosk/heartbeat',
            data='{}',
            headers={
                'Content-Type': 'application/json',
                'X-EH-Kiosk-Token': token,
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_whoami_with_valid_token(self):
        device = self.env['eh.hr.kiosk.terminal'].sudo().create({
            'name': 'Whoami test',
            'site_id': self.site.id,
        })
        response = self.url_open(
            '/eh_hr/kiosk/whoami',
            headers={'X-EH-Kiosk-Token': device.device_token},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['site_code'], self.site.code)
        self.assertEqual(payload['device_id'], device.id)
