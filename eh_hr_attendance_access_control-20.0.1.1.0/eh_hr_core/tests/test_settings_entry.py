# -*- coding: utf-8 -*-
"""Typed, per-company, versioned settings. Every engine reads its knobs
through get() and set(), so the casting rules and the versioning are part of
the platform contract."""
import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestSettingsEntry(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Entry = cls.env['eh.hr.settings.entry']

    def test_typed_reads_cast_the_stored_string(self):
        cases = [
            ('str', 'hello', 'hello'),
            ('int', '42', 42),
            ('float', '1.5', 1.5),
            ('bool', 'yes', True),
            ('bool', 'off', False),
            ('json', '{"a": [1, 2]}', {'a': [1, 2]}),
        ]
        for value_type, raw, expected in cases:
            entry = self.Entry.create({
                'key': 'probe.%s.%s' % (value_type, raw[:4]),
                'value': raw, 'value_type': value_type})
            self.assertEqual(entry.typed(), expected,
                             'A %s value must read back typed.' % value_type)

    def test_an_uncastable_value_is_refused_loudly(self):
        entry = self.Entry.create({
            'key': 'probe.bad', 'value': 'not-a-number', 'value_type': 'int'})
        with self.assertRaises(ValidationError):
            entry.typed()

    def test_get_returns_the_default_when_the_key_is_absent(self):
        self.assertEqual(self.Entry.get('probe.absent', default=7), 7)
        self.assertIsNone(self.Entry.get('probe.absent'))

    def test_set_then_get_round_trips_per_company(self):
        other = self.env['res.company'].create({'name': 'EH settings co B'})
        self.Entry.set('probe.round', 10, 'int')
        self.Entry.set('probe.round', 20, 'int', company=other)
        self.assertEqual(self.Entry.get('probe.round'), 10)
        self.assertEqual(self.Entry.get('probe.round', company=other), 20,
                         'Each company keeps its own value for one key.')

    def test_set_archives_the_previous_revision(self):
        first = self.Entry.set('probe.version', 'a')
        second = self.Entry.set('probe.version', 'b')
        self.assertFalse(first.active,
                         'The superseded revision must be archived, not lost.')
        self.assertEqual(first.superseded_by, second)
        self.assertEqual(self.Entry.get('probe.version'), 'b')
        history = self.Entry.with_context(active_test=False).search(
            [('key', '=', 'probe.version')])
        self.assertEqual(len(history), 2,
                         'A rewrite keeps the audit trail of old values.')

    def test_a_key_can_be_superseded_many_times(self):
        revisions = [self.Entry.set('probe.many', letter)
                     for letter in ('a', 'b', 'c', 'd')]
        self.assertEqual(self.Entry.get('probe.many'), 'd')
        self.assertEqual(
            self.Entry.with_context(active_test=False).search_count(
                [('key', '=', 'probe.many')]), 4,
            'Every revision of a key stays on file.')
        self.assertEqual([r.active for r in revisions],
                         [False, False, False, True])
        self.assertEqual(revisions[0].superseded_by, revisions[1],
                         'Each archived revision points at its successor.')
        self.assertEqual(revisions[2].superseded_by, revisions[3])

    @mute_logger('odoo.sql_db')
    def test_only_one_active_entry_per_company_and_key(self):
        self.Entry.create({'key': 'probe.unique', 'value': 'a'})
        with self.assertRaises(psycopg2.IntegrityError):
            self.Entry.create({'key': 'probe.unique', 'value': 'b'})
            self.env.flush_all()
