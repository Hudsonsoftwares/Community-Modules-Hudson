from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVisitInterval(TransactionCase):
    """Multi-visit treatments such as braces date the next visit from their visit interval."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env['res.partner'].create({'name': 'Ortho Interval Patient', 'is_dental_patient': True})
        cls.braces = cls.env['product.template'].create({
            'name': 'Braces Interval Test',
            'is_dental_treatment': True,
            'list_price': 1200.0,
            'number_of_visits': 12,
            'visit_interval': '1 Month',
        })
        cls.case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'chief_complaint': 'Crowding'})

    def _new_line(self, **line_vals):
        plan = self.env['dental.treatment.plan'].create({
            'patient_id': self.patient.id,
            'case_id': self.case.id,
            'line_ids': [(0, 0, dict({'treatment_id': self.braces.id, 'number_of_visits': 12, 'unit_price': 1200.0},
                                     **line_vals))],
        })
        return plan.line_ids

    def _next_visit_gap(self, line):
        line.action_mark_visit_done()
        session = line.session_ids.filtered(lambda s: s.state == 'completed')[:1]
        follow_up = session.follow_up_ids.filtered(lambda f: f.state == 'pending')
        self.assertEqual(len(follow_up), 1)
        self.assertEqual(follow_up.follow_up_type, 'next_visit')
        session_day = fields.Datetime.context_timestamp(session, session.session_date).date()
        return follow_up.date - session_day

    def test_treatment_interval_used_when_line_has_none(self):
        line = self._new_line()
        self.assertEqual(self._next_visit_gap(line), timedelta(days=30))
        # Each adjustment visit bills its share of the plan line
        self.assertEqual(line.session_ids[:1]._get_billing_price(), 100.0)

    def test_line_interval_overrides_treatment(self):
        line = self._new_line(visit_interval='6 Weeks')
        self.assertEqual(self._next_visit_gap(line), timedelta(days=42))

    def test_default_one_week_without_interval(self):
        self.braces.visit_interval = False
        line = self._new_line()
        self.assertEqual(self._next_visit_gap(line), timedelta(days=7))
