# -*- encoding: utf-8 -*-
"""Which address the door trigger route counts.

A caller without a device token is throttled by its address. The route took
that address from X-Real-IP or the first X-Forwarded-For entry, which any
caller writes, so a tokenless caller named a new address on every request
and was never throttled. It now takes the address Odoo's HTTP layer
resolves, the rule eh_hr_attendance_base writes once for every public route
of the suite.
"""
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.eh_hr_attendance_base.tests.common_client_address import ClientAddressMixin

# The route's budget per caller and minute.
TRIGGER_LIMIT = 60


@tagged('post_install', '-at_install')
class TestAccessTriggerClientAddress(ClientAddressMixin, HttpCase):

    def _trigger(self, headers):
        # The throttle and the token are checked before the route reads a
        # body, so none is posted: a body the route never reads is still in
        # the socket when the test server closes it, and the client may then
        # see a connection reset instead of the answer.
        return self.url_open('/eh_hr/kiosk/access/trigger', headers=headers, method='POST')

    @mute_logger('odoo.http')
    def test_a_forged_address_header_is_not_a_new_caller(self):
        with self.frozen_throttle_clock():
            statuses = [
                self._trigger(self.forged_headers('203.0.113.%s' % n)).status_code
                for n in range(TRIGGER_LIMIT + 1)
            ]
            self.assertEqual(statuses, [401] * TRIGGER_LIMIT + [429])
            # Behind the proxy, the leading hops are the caller's own words.
            with self.behind_proxy():
                statuses = [
                    self._trigger(self.proxied_headers('198.51.100.%s, 192.0.2.70' % n)).status_code
                    for n in range(TRIGGER_LIMIT + 1)
                ]
            self.assertEqual(statuses, [401] * TRIGGER_LIMIT + [429])
