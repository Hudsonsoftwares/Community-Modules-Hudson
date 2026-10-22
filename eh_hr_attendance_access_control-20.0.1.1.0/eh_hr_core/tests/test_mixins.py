# -*- coding: utf-8 -*-
"""The three platform mixins are what every feature module composes, so they
are exercised here through a concrete model and the real ORM entry points,
not through method calls on an abstract recordset."""
from odoo import fields, models
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from odoo.addons.eh_hr_core.tests.common import PlatformModelCase


class PlatformDoc(models.Model):
    """Captures every field by default, which is the platform default."""
    _register = False
    _module = 'eh_hr_core'
    _name = 'eh.hr.test.platform.doc'
    _description = 'EH HR platform mixin probe'
    _inherit = ['eh.hr.platform.mixin', 'eh.hr.audited.mixin',
                'eh.hr.company.aware.mixin']
    _log_access = False

    name = fields.Char(required=True)
    amount = fields.Float()


class NarrowDoc(models.Model):
    """Declares an audit whitelist, which is how a feature module keeps large
    or sensitive columns out of the trail."""
    _register = False
    _module = 'eh_hr_core'
    _name = 'eh.hr.test.narrow.doc'
    _description = 'EH HR audit whitelist probe'
    _inherit = ['eh.hr.audited.mixin']
    _log_access = False
    _audit_fields = ['name']

    name = fields.Char()
    private_note = fields.Char()


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestPlatformMixins(PlatformModelCase):

    test_model_defs = (PlatformDoc, NarrowDoc)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Doc = cls.env['eh.hr.test.platform.doc']
        cls.Narrow = cls.env['eh.hr.test.narrow.doc']
        cls.Audit = cls.env['eh.hr.audit.log']
        cls.company_b = cls.env['res.company'].create({'name': 'EH probe co B'})
        # res.company.create adds the new company to the acting user, which is
        # the opposite of the starting point these tests need: a company the
        # user is not a member of.
        cls.env.user.write({'company_ids': [(3, cls.company_b.id)]})

    def _rows(self, model, record_id=None, action=None):
        domain = [('model', '=', model)]
        if record_id is not None:
            domain.append(('record_id', '=', record_id))
        if action is not None:
            domain.append(('action', '=', action))
        return self.Audit.sudo().search(domain, order='id ASC')

    # -- platform mixin ------------------------------------------------
    def test_create_stamps_a_correlation_id(self):
        doc = self.Doc.create({'name': 'first'})
        self.assertTrue(doc.correlation_id,
                        'Every platform record must carry a trace id.')
        other = self.Doc.create({'name': 'second'})
        self.assertNotEqual(doc.correlation_id, other.correlation_id)
        self.assertEqual(doc.copy().correlation_id and True, True,
                         'A copy gets its own id, never a blank one.')
        self.assertNotEqual(doc.copy().correlation_id, doc.correlation_id)

    def test_explicit_correlation_id_is_kept(self):
        doc = self.Doc.create({'name': 'x', 'correlation_id': 'caller-supplied'})
        self.assertEqual(doc.correlation_id, 'caller-supplied',
                         'A caller passing its own trace id must win.')

    def test_platform_subjects_defaults_to_no_user(self):
        doc = self.Doc.create({'name': 'x'})
        subjects = doc._platform_subjects()
        self.assertEqual(subjects._name, 'res.users')
        self.assertFalse(subjects)

    def test_emit_platform_event_writes_an_audit_row(self):
        doc = self.Doc.create({'name': 'x'})
        doc.emit_platform_event('probe.happened', {'extra': 7})
        row = self._rows(doc._name, doc.id, 'event:probe.happened')
        self.assertEqual(len(row), 1)
        self.assertEqual(row.payload['extra'], 7)
        self.assertEqual(row.payload['model'], doc._name)
        self.assertEqual(row.payload['record_id'], doc.id)
        self.assertEqual(row.payload['correlation_id'], doc.correlation_id)
        self.assertEqual(row.company_id, doc.company_id,
                         'The event must be filed under the record company.')

    def test_emit_platform_event_queues_a_bus_notification(self):
        doc = self.Doc.create({'name': 'x'})
        doc.emit_platform_event('probe.bus', {'v': 1})
        queued = self.env.cr.precommit.data.get('bus.bus.values') or []
        topics = [notification_type for _channel, notification_type, _message
                  in queued]
        self.assertIn('hr.events.probe.bus', topics,
                      'The event must reach the bus, not only the audit log.')

    # -- audited mixin -------------------------------------------------
    def test_create_and_unlink_are_audited(self):
        doc = self.Doc.create({'name': 'audited'})
        created = self._rows(doc._name, doc.id, 'create')
        self.assertEqual(len(created), 1)
        self.assertEqual(created.payload['name'], 'audited')
        self.assertEqual(created.actor_id, self.env.user)
        doc_id = doc.id
        doc.unlink()
        removed = self._rows('eh.hr.test.platform.doc', doc_id, 'unlink')
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed.payload['display_name'], 'audited')

    def test_write_records_the_before_and_after_values(self):
        doc = self.Doc.create({'name': 'before', 'amount': 1})
        doc.write({'name': 'after', 'amount': 2})
        written = self._rows(doc._name, doc.id, 'write')
        self.assertEqual(len(written), 1)
        self.assertEqual(written.payload['before'],
                         {'name': 'before', 'amount': 1})
        self.assertEqual(written.payload['after'],
                         {'name': 'after', 'amount': 2})

    def test_a_write_that_changes_nothing_is_not_audited(self):
        doc = self.Doc.create({'name': 'same'})
        doc.write({'name': 'same'})
        self.assertFalse(self._rows(doc._name, doc.id, 'write'),
                         'Re-writing the same value must not add a row.')

    def test_audit_whitelist_keeps_other_fields_out(self):
        doc = self.Narrow.create({'name': 'n', 'private_note': 'secret'})
        created = self._rows(doc._name, doc.id, 'create')
        self.assertEqual(set(created.payload), {'name'},
                         'Only whitelisted fields may reach the trail.')
        doc.write({'private_note': 'still secret'})
        self.assertFalse(self._rows(doc._name, doc.id, 'write'),
                         'A write outside the whitelist must not be audited.')

    def test_relational_and_date_values_survive_the_json_column(self):
        # The payload is built from raw field reads, so a Many2one arrives as
        # a recordset. It has to be coerced or the jsonb adapter raises.
        doc = self.Doc.create({'name': 'rel'})
        created = self._rows(doc._name, doc.id, 'create')
        self.assertEqual(created.payload['company_id'],
                         [self.env.company.id])

    # -- company aware mixin -------------------------------------------
    def test_company_defaults_to_the_active_company(self):
        doc = self.Doc.create({'name': 'x'})
        self.assertEqual(doc.company_id, self.env.company)

    def test_create_into_a_foreign_company_is_refused(self):
        with self.assertRaises(AccessError):
            self.Doc.create({'name': 'x', 'company_id': self.company_b.id})

    def test_moving_a_record_needs_the_audited_override(self):
        self.env.user.write({'company_ids': [(4, self.company_b.id)]})
        doc = self.Doc.create({'name': 'x'})
        with self.assertRaises(AccessError):
            doc.write({'company_id': self.company_b.id})
        doc.with_context(allow_cross_company=True).write(
            {'company_id': self.company_b.id})
        self.assertEqual(doc.company_id, self.company_b)
        elevation = self._rows(doc._name, doc.id, 'cross_company_write')
        self.assertEqual(len(elevation), 1)
        self.assertEqual(elevation.payload['new_company_id'], self.company_b.id)
        self.assertEqual(elevation.payload['record_ids'], [doc.id])

    def test_restating_the_same_company_is_not_an_elevation(self):
        doc = self.Doc.create({'name': 'x'})
        # A plain form save re-sends every field, company_id included.
        doc.write({'name': 'y', 'company_id': doc.company_id.id})
        self.assertFalse(self._rows(doc._name, doc.id, 'cross_company_write'),
                         'An unchanged company is not a cross-company write.')
