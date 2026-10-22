# -*- coding: utf-8 -*-
"""The service registry is how every engine is reached from a cron, a
controller, a wizard or another engine, so the lookup contract is pinned
here."""
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.eh_hr_core.services import (
    AuditService,
    HrService,
    TimezoneService,
    locate_service,
    register_service,
)


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestServiceRegistry(TransactionCase):

    def test_the_platform_services_resolve_by_code(self):
        tz = locate_service('eh.hr.tz.service', self.env)
        self.assertIsInstance(tz, TimezoneService)
        self.assertEqual(tz.env, self.env,
                         'A service is bound to the caller transaction.')
        self.assertEqual(tz._service_code, 'eh.hr.tz.service')
        self.assertIsInstance(
            locate_service('eh.hr.audit.service', self.env), AuditService)

    def test_an_unknown_code_is_refused(self):
        with self.assertRaises(KeyError):
            locate_service('eh.hr.no.such.service', self.env)

    def test_a_service_locates_its_peers(self):
        audit = locate_service('eh.hr.audit.service', self.env)
        self.assertIsInstance(audit.locate('eh.hr.tz.service'),
                              TimezoneService)

    def test_a_code_cannot_be_registered_twice(self):
        with self.assertRaises(RuntimeError):
            @register_service('eh.hr.tz.service')
            class Duplicate(HrService):
                pass

    def test_the_audit_service_writes_a_row_without_a_recordset(self):
        audit = locate_service('eh.hr.audit.service', self.env)
        audit.emit('res.partner', 7, 'service.probe', {'reason': 'probe'})
        row = self.env['eh.hr.audit.log'].sudo().search(
            [('model', '=', 'res.partner'), ('action', '=', 'service.probe')])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.record_id, 7)
        self.assertEqual(row.payload['reason'], 'probe')
        self.assertEqual(row.actor_id, self.env.user,
                         'The acting user is recorded when none is passed.')
