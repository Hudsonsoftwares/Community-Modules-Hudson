from odoo.tests.common import TransactionCase, tagged
from odoo import fields

@tagged('post_install', '-at_install')
class TestTreatmentSessionsInPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.patient = cls.env['res.partner'].create({
            'name': 'Test Treatment Patient',
            'is_dental_patient': True,
        })
        cls.treatment = cls.env['product.template'].create({
            'name': 'RCT Test Treatment',
            'is_dental_treatment': True,
            'list_price': 400.0,
            'number_of_visits': 2,
        })
        cls.stage_prep = cls.env['dental.treatment.stage'].create({
            'name': 'Preparation Stage',
            'sequence': 10,
            'stage_type': 'in_progress',
            'treatment_id': cls.treatment.id,
        })
        cls.stage_comp = cls.env['dental.treatment.stage'].create({
            'name': 'Completion Stage',
            'sequence': 20,
            'stage_type': 'completed',
            'treatment_id': cls.treatment.id,
        })
        cls.case = cls.env['dental.case'].create({
            'patient_id': cls.patient.id,
            'chief_complaint': 'Tooth ache on 36',
        })
        cls.plan = cls.env['dental.treatment.plan'].create({
            'patient_id': cls.patient.id,
            'case_id': cls.case.id,
            'line_ids': [(0, 0, {
                'treatment_id': cls.treatment.id,
                'tooth_reference': '36',
                'number_of_visits': 2,
                'unit_price': 400.0,
            })],
        })
        cls.line = cls.plan.line_ids[0]

    def test_treatment_stages_and_progress(self):
        """Test configurable stages, progress tracking, and Add Session on plan line."""
        line = self.line
        self.assertEqual(line.stage_id, self.stage_prep)
        self.assertEqual(line.progress, 0.0)
        self.assertEqual(line.completed_visits, 0)
        self.assertEqual(self.plan.session_count, 0)

        # Add session
        action = line.action_add_session()
        self.assertEqual(action.get('res_model'), 'dental.treatment.session')
        session_id = action.get('res_id')
        session = self.env['dental.treatment.session'].browse(session_id)

        # Verify links are preserved
        self.assertEqual(session.plan_line_id, line)
        self.assertEqual(session.plan_id, self.plan)
        self.assertEqual(session.case_id, self.case)
        self.assertEqual(session.patient_id, self.patient)
        self.assertEqual(session.tooth_reference, '36')
        self.assertEqual(session.stage_id, self.stage_prep)
        self.assertIn(session, self.plan.session_ids)
        self.assertIn(session, line.session_ids)
        self.assertEqual(self.plan.session_count, 1)

        # Complete first session (Visit 1 of 2 -> 50% progress)
        session.action_complete()
        self.assertEqual(session.state, 'completed')
        self.assertEqual(session.billing_state, 'to_invoice')
        self.assertEqual(line.completed_visits, 1)
        self.assertEqual(line.progress, 50.0)
        self.assertEqual(line.state, 'in_progress')
        self.assertEqual(self.plan.state, 'in_progress')

        # Add second session and complete it -> 100% progress and advances stage
        action2 = line.action_add_session()
        session2 = self.env['dental.treatment.session'].browse(action2.get('res_id'))
        session2.action_complete()
        self.assertEqual(line.completed_visits, 2)
        self.assertEqual(line.progress, 100.0)
        self.assertEqual(line.state, 'completed')
        self.assertEqual(line.stage_id, self.stage_comp)
        self.assertEqual(self.plan.state, 'completed')

    def test_case_billing_and_history_preserved(self):
        """Verify billing and case links remain preserved with sessions inside plan."""
        line = self.line
        line.action_mark_visit_done()
        session = line.session_ids[:1]
        self.assertTrue(session)
        self.assertEqual(session.state, 'completed')
        self.assertEqual(session.case_id, self.case)
        self.assertIn(session, self.case.treatment_session_ids)

        billable_sessions = self.case._get_billable_sessions()
        self.assertIn(session, billable_sessions)

