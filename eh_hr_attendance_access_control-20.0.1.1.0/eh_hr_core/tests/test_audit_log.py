# -*- coding: utf-8 -*-
"""The audit log is the platform's evidence store: append only, hash chained
and readable only inside the reader's companies. Every one of those three
promises is checked here."""
import hashlib

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.eh_hr_compat import groups_field


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_security')
class TestAuditLog(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Audit = cls.env['eh.hr.audit.log'].sudo()

    def test_append_chains_each_row_to_the_previous_one(self):
        first = self.Audit.write_event(
            'res.partner', 1, 'probe.one', self.env.user, {'a': 1})
        second = self.Audit.write_event(
            'res.partner', 2, 'probe.two', self.env.user, {'b': 2})
        self.assertEqual(second.prev_hash, first.row_hash,
                         'Each row must carry the hash of its predecessor.')
        material = self.Audit._chain_material(
            first.row_hash, 'res.partner', 2, 'probe.two',
            self.env.user.id, {'b': 2})
        self.assertEqual(
            second.row_hash,
            hashlib.sha256(material.encode('utf-8')).hexdigest(),
            'The stored hash must be the sha256 of the canonical material.')

    def test_verify_chain_accepts_an_untouched_chain(self):
        for index in range(3):
            self.Audit.write_event('res.partner', index, 'probe',
                                   self.env.user, {'i': index})
        self.assertFalse(self.Audit.verify_chain(),
                         'An untouched chain must report no broken row.')

    def test_verify_chain_finds_an_edited_row(self):
        self.Audit.write_event('res.partner', 1, 'probe', self.env.user)
        victim = self.Audit.write_event(
            'res.partner', 2, 'probe', self.env.user, {'amount': 100})
        self.Audit.write_event('res.partner', 3, 'probe', self.env.user)
        # Rewrite history the way an attacker with table access would.
        self.env.cr.execute(
            'UPDATE eh_hr_audit_log SET payload = %s WHERE id = %s',
            ('{"amount": 1}', victim.id))
        self.env.invalidate_all()
        self.assertEqual(self.Audit.verify_chain(), victim.id,
                         'The edited row must be reported by id.')

    def test_an_actorless_row_verifies(self):
        # A cron or a public endpoint has no user; the append and the verify
        # paths have to hash the missing actor the same way.
        self.Audit.write_event('res.partner', 1, 'cron.probe', None, {'x': 1})
        self.assertFalse(self.Audit.verify_chain())

    def test_recordsets_and_dates_are_stored_as_json(self):
        row = self.Audit.write_event(
            'res.partner', 1, 'probe', self.env.user,
            {'company': self.env.company,
             'when': self.env.company.create_date,
             'nested': {'users': [self.env.user]}})
        self.assertEqual(row.payload['company'], [self.env.company.id])
        self.assertIsInstance(row.payload['when'], str)
        self.assertEqual(row.payload['nested']['users'],
                         [[self.env.user.id]],
                         'A recordset inside a list keeps its own id list.')
        self.assertFalse(self.Audit.verify_chain(),
                         'The coerced payload must hash the same on verify.')

    def test_company_defaults_to_the_actor_company(self):
        row = self.Audit.write_event('res.partner', 1, 'probe', self.env.user)
        self.assertEqual(row.company_id, self.env.user.company_id)
        system = self.Audit.write_event('res.partner', 1, 'probe', None)
        self.assertFalse(system.company_id,
                         'A system event belongs to no single company.')

    def test_an_officer_reads_only_their_own_company_rows(self):
        other = self.env['res.company'].create({'name': 'EH audit co B'})
        officer = self.env['res.users'].create({
            'name': 'EH audit officer', 'login': 'eh_audit_officer',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            groups_field(self.env): [
                (4, self.env.ref('eh_hr_core.group_hr_officer').id)],
        })
        mine = self.Audit.write_event('res.partner', 1, 'probe',
                                      self.env.user, {},
                                      company_id=self.env.company.id)
        theirs = self.Audit.write_event('res.partner', 2, 'probe',
                                        self.env.user, {},
                                        company_id=other.id)
        system = self.Audit.write_event('res.partner', 3, 'probe', None)
        visible = self.env['eh.hr.audit.log'].with_user(officer).search([])
        self.assertIn(mine, visible)
        self.assertIn(system, visible,
                      'System-wide rows belong to no company and stay visible.')
        self.assertNotIn(theirs, visible,
                         'Another company audit trail must stay invisible.')

    def test_the_log_is_read_only_for_its_readers(self):
        auditor = self.env['res.users'].create({
            'name': 'EH auditor', 'login': 'eh_audit_auditor',
            groups_field(self.env): [
                (4, self.env.ref('eh_hr_core.group_hr_auditor').id)],
        })
        row = self.Audit.write_event('res.partner', 1, 'probe', self.env.user)
        self.assertTrue(row.with_user(auditor).has_access('read'))
        self.assertFalse(row.with_user(auditor).has_access('write'),
                         'Nobody edits the audit log through the ORM.')
        self.assertFalse(row.with_user(auditor).has_access('unlink'))
        self.assertFalse(
            self.env['eh.hr.audit.log'].with_user(auditor).has_access('create'))
