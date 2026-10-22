# -*- encoding: utf-8 -*-
"""Which address the face match route counts and records.

A caller without a device token is throttled by its address, and every
event a match writes records the caller's address. The route took that
address from X-Real-IP or the first X-Forwarded-For entry, which any caller
writes: a tokenless caller named a new address on every request and was
never throttled, and the audit trail recorded what the caller claimed. It
now takes the address Odoo's HTTP layer resolves, the rule
eh_hr_attendance_base writes once for every public route of the suite.
"""
import json

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.eh_hr_attendance_base.tests.common_client_address import ClientAddressMixin

# The route's budget per caller and minute.
MATCH_LIMIT = 60


@tagged('post_install', '-at_install')
class TestFaceMatchClientAddress(ClientAddressMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Address match site',
            'code': 'address-match',
            'company_id': cls.env.company.id,
            'geofence_enabled': True,
            'geofence_lat': -37.8136,
            'geofence_lng': 144.9631,
            'geofence_radius_m': 100,
        })
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Address match kiosk',
            'site_id': cls.site.id,
        })

    def _match(self, headers, token=None):
        if not token:
            # The throttle and the token are checked before the route reads a
            # body, so none is posted: a body the route never reads is still
            # in the socket when the test server closes it, and the client
            # may then see a connection reset instead of the answer.
            return self.url_open('/eh_hr/kiosk/face/match', headers=headers, method='POST')
        return self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': [0.5] * 128}),
            headers={'Content-Type': 'application/json', 'X-EH-Kiosk-Token': token, **headers},
        )

    def _events(self):
        return self.env['eh.hr.kiosk.event'].search(
            [('device_id', '=', self.device.id), ('event_type', '=', 'geofence_fail')], order='id')

    @mute_logger('odoo.http')
    def test_a_forged_address_header_is_not_a_new_caller(self):
        with self.frozen_throttle_clock():
            statuses = [
                self._match(self.forged_headers('203.0.113.%s' % n)).status_code
                for n in range(MATCH_LIMIT + 1)
            ]
            self.assertEqual(statuses, [401] * MATCH_LIMIT + [429])
            # Behind the proxy, the leading hops are the caller's own words.
            with self.behind_proxy():
                statuses = [
                    self._match(self.proxied_headers('198.51.100.%s, 192.0.2.30' % n)).status_code
                    for n in range(MATCH_LIMIT + 1)
                ]
            self.assertEqual(statuses, [401] * MATCH_LIMIT + [429])

    @mute_logger('odoo.http')
    def test_the_audit_trail_records_the_resolved_address(self):
        # The site requires a location and none is sent, so the route logs a
        # geofence failure with the caller's address and stops there.
        response = self._match(self.forged_headers('203.0.113.9'), token=self.device.device_token)
        self.assertEqual(response.json()['reason'], 'geofence_required')
        with self.behind_proxy():
            self._match(self.proxied_headers('203.0.113.9, 192.0.2.31'), token=self.device.device_token)
        self.assertEqual(self._events().mapped('ip_address'), [self.peer, '192.0.2.31'])
