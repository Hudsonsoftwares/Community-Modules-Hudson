# -*- encoding: utf-8 -*-
import json
from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged

from odoo.addons.eh_hr_attendance_base.tests.common import EhHrTestCommon


class TestAccessModels(EhHrTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.zone = cls.env['eh.hr.access.zone'].create({
            'name': 'Front door',
            'code': 'front-door',
            'site_ids': [(6, 0, [cls.site.id])],
            'company_id': cls.company.id,
        })
        cls.reader = cls.env['eh.hr.access.reader'].create({
            'name': 'Front door relay',
            'zone_id': cls.zone.id,
            'webhook_url': 'http://localhost:9999/unlock',
            'auto_relock_seconds': 5,
            'timeout_seconds': 2,
        })

    def test_zone_code_format_validation(self):
        with self.assertRaises(ValidationError):
            self.env['eh.hr.access.zone'].create({
                'name': 'Bad code',
                'code': 'has spaces',
                'company_id': self.company.id,
            })

    def test_reader_url_validation(self):
        with self.assertRaises(ValidationError):
            self.env['eh.hr.access.reader'].create({
                'name': 'Bad url',
                'zone_id': self.zone.id,
                'webhook_url': 'not-a-url',
            })

    def test_permission_unique_per_employee_and_zone(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        Permission = self.env['eh.hr.access.permission']
        Permission.create({
            'employee_id': self.employee_alice.id,
            'zone_id': self.zone.id,
        })
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                Permission.create({
                    'employee_id': self.employee_alice.id,
                    'zone_id': self.zone.id,
                })

    def test_permission_valid_window(self):
        Permission = self.env['eh.hr.access.permission']
        p = Permission.create({
            'employee_id': self.employee_alice.id,
            'zone_id': self.zone.id,
            'valid_from': date.today() - timedelta(days=1),
            'valid_to': date.today() + timedelta(days=1),
        })
        self.assertTrue(p.is_currently_valid())

        p_past = Permission.create({
            'employee_id': self.employee_bob.id,
            'zone_id': self.zone.id,
            'valid_to': date.today() - timedelta(days=1),
        })
        self.assertFalse(p_past.is_currently_valid())

    def test_reader_call_webhook_handles_2xx(self):
        class MockResp:
            status_code = 200
            text = 'ok'
        with patch('requests.post', return_value=MockResp()):
            status, response = self.reader._call_webhook({'action': 'unlock'})
        self.assertEqual(status, 'ok')
        self.assertEqual(response, 'ok')

    def test_reader_call_webhook_handles_4xx(self):
        class MockResp:
            status_code = 403
            text = 'forbidden'
        with patch('requests.post', return_value=MockResp()):
            status, _ = self.reader._call_webhook({'action': 'unlock'})
        self.assertEqual(status, 'denied')

    def test_reader_call_webhook_handles_network_error(self):
        # The operator notice is part of the contract: a door that cannot be
        # reached must say so in the log with the reader named. assertLogs both
        # asserts that and keeps the deliberate warning out of the run's output.
        logger = 'odoo.addons.eh_hr_attendance_access_control.models.eh_hr_access_reader'
        with patch('requests.post', side_effect=Exception('connection refused')):
            with self.assertLogs(logger, 'WARNING') as captured:
                status, response = self.reader._call_webhook({'action': 'unlock'})
        self.assertEqual(status, 'error')
        self.assertIn('connection refused', response)
        self.assertTrue(any(self.reader.name in line for line in captured.output))


@tagged('post_install', '-at_install')
class TestAccessHttpEndpoint(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Access http site',
            'code': 'access-http',
            'company_id': company.id,
        })
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Access http device',
            'site_id': cls.site.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Access http employee',
            'company_id': company.id,
        })
        cls.zone = cls.env['eh.hr.access.zone'].create({
            'name': 'Door',
            'code': 'door',
            'site_ids': [(6, 0, [cls.site.id])],
            'company_id': company.id,
        })
        cls.reader = cls.env['eh.hr.access.reader'].create({
            'name': 'Door relay',
            'zone_id': cls.zone.id,
            'webhook_url': 'http://localhost:9999/unlock',
        })
        cls.env['eh.hr.access.permission'].create({
            'employee_id': cls.employee.id,
            'zone_id': cls.zone.id,
        })

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'X-EH-Kiosk-Token': self.device.device_token,
        }

    def test_trigger_unauthorized_without_token(self):
        resp = self.url_open(
            '/eh_hr/kiosk/access/trigger',
            data=json.dumps({'employee_id': self.employee.id}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_trigger_with_permission_calls_reader(self):
        class MockResp:
            status_code = 200
            text = '{"ok": true}'
        with patch('requests.post', return_value=MockResp()):
            resp = self.url_open(
                '/eh_hr/kiosk/access/trigger',
                data=json.dumps({'employee_id': self.employee.id}),
                headers=self._headers(),
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['outcome'], 'allowed')

    def test_trigger_without_permission_returns_denied(self):
        bob = self.env['hr.employee'].create({
            'name': 'No permission',
            'company_id': self.env.company.id,
        })
        resp = self.url_open(
            '/eh_hr/kiosk/access/trigger',
            data=json.dumps({'employee_id': bob.id}),
            headers=self._headers(),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['ok'])
        self.assertEqual(body['reason'], 'denied')

    def test_trigger_records_event_on_each_path(self):
        class MockResp:
            status_code = 200
            text = 'ok'
        with patch('requests.post', return_value=MockResp()):
            self.url_open(
                '/eh_hr/kiosk/access/trigger',
                data=json.dumps({'employee_id': self.employee.id}),
                headers=self._headers(),
            )
        events = self.env['eh.hr.access.event'].sudo().search([
            ('employee_id', '=', self.employee.id),
        ])
        self.assertTrue(events)
        self.assertEqual(events[0].outcome, 'allowed')

    def test_trigger_invalid_employee_returns_404(self):
        resp = self.url_open(
            '/eh_hr/kiosk/access/trigger',
            data=json.dumps({'employee_id': 999999}),
            headers=self._headers(),
        )
        self.assertEqual(resp.status_code, 404)
