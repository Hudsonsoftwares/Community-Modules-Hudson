from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, new_test_user, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'dental_orthodontics')
class TestOrthoChart(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.user = new_test_user(cls.env, login='ortho_dentist', groups='base.group_user,dental_base.group_dental_dentist',
                                 company_id=company.id, company_ids=[company.id])
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Ortho', 'dental_role': 'dentist',
                                                    'user_id': cls.user.id, 'company_id': company.id})
        cls.patient = cls.env['res.partner'].create({'name': 'Ortho Patient', 'is_dental_patient': True,
                                                     'date_of_birth': '2010-04-01'})
        category = cls.env['dental.treatment.category'].search([('name', 'ilike', 'Orthodon')], limit=1) or \
            cls.env['dental.treatment.category'].create({'name': 'Orthodontics'})
        cls.braces = cls.env['product.template'].create({
            'name': 'Fixed Braces Test', 'is_dental_treatment': True, 'list_price': 1800.0,
            'number_of_visits': 18, 'visit_interval': '1 Month', 'dental_treatment_category_id': category.id})
        cls.case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id,
                                                  'chief_complaint': 'Crooked front teeth', 'state': 'open'})
        cls.plan = cls.env['dental.treatment.plan'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id,
            'line_ids': [(0, 0, {'treatment_id': cls.braces.id, 'number_of_visits': 18, 'unit_price': 1800.0})]})
        cls.line = cls.plan.line_ids

    def _chart(self):
        action = self.case.action_open_ortho_chart()
        return self.env['dental.ortho.chart'].browse(action['res_id'])

    def test_chart_started_from_case(self):
        chart = self._chart()
        self.assertEqual(chart.patient_id, self.patient)
        self.assertEqual(chart.plan_line_id, self.line, 'The braces line of the case plan is linked')
        self.assertEqual(chart.chief_concern, 'Crooked front teeth')
        self.assertEqual(len(chart.tooth_ids), 32)
        by_tooth = {t.tooth_number: t for t in chart.tooth_ids}
        self.assertEqual((by_tooth['11'].appliance, by_tooth['11'].status), ('bracket', 'planned'))
        self.assertEqual((by_tooth['16'].appliance, by_tooth['46'].appliance), ('tube', 'tube'))
        self.assertEqual(by_tooth['18'].status, 'none', 'Third molars are not included')
        self.assertEqual(chart.tooth_ids.sorted('sequence')[0].tooth_number, '18')
        # Opening again returns the same chart
        self.assertEqual(self._chart(), chart)
        self.assertIn('o_ortho_tooth', chart.chart_html)

    def test_copy_from_examination(self):
        exam = self.env['dental.clinical.examination'].browse(self.case.action_open_examination()['res_id'])
        exam.write({'molar_relation': 'class_2_div1', 'overjet': 7.0, 'overbite': 4.5, 'crossbite': 'anterior'})
        chart = self._chart()
        self.assertEqual(chart.angle_class, 'class_2_div1')
        self.assertEqual(chart.overjet, 7.0)
        self.assertEqual(chart.crossbite, 'anterior')

    def test_assessment_values(self):
        chart = self._chart()
        chart.write({'ceph_sna': 84.0, 'ceph_snb': 78.5, 'iotn_dhc': '4'})
        self.assertAlmostEqual(chart.ceph_anb, 5.5)
        self.assertEqual(chart.treatment_need, 'need')
        with self.assertRaises(ValidationError):
            chart.overjet = 40

    def test_full_course(self):
        chart = self._chart()
        with self.assertRaises(UserError):
            chart.action_confirm_plan()  # appliance required
        chart.appliance_type = 'fixed_metal'
        chart.action_confirm_plan()
        self.assertEqual(chart.state, 'planned')

        # Bonding visit: appliances bonded, first session of the braces line recorded
        bonding = self.env['dental.ortho.visit'].browse(chart.action_new_visit()['res_id'])
        self.assertEqual(bonding.visit_type, 'bonding')
        bonding.write({'upper_wire': 'niti_014', 'lower_wire': 'niti_014', 'next_visit_weeks': 6})
        bonding.action_done()
        self.assertEqual(chart.state, 'active')
        self.assertEqual(chart.phase, 'leveling')
        self.assertEqual(chart.bonded_count, 28, '10 brackets + 4 molar tubes per arch; third molars excluded')
        self.assertTrue(bonding.session_id)
        self.assertEqual(bonding.session_id.state, 'completed')
        self.assertEqual(self.line.completed_visits, 1)
        self.assertEqual(chart.current_upper_wire, '0.014" NiTi')
        follow_up = self.env['dental.follow.up'].search([('case_id', '=', self.case.id), ('state', '=', 'pending')])
        self.assertEqual(len(follow_up), 1, 'Exactly one next-visit follow-up (the chart replaces the session default)')
        self.assertEqual(follow_up.date, fields.Date.to_date(bonding.date) + timedelta(weeks=6))

        # Adjustment visit carries the wires forward; changing the upper wire is flagged
        adjust = self.env['dental.ortho.visit'].browse(chart.action_new_visit()['res_id'])
        self.assertEqual(adjust.visit_type, 'adjustment')
        self.assertEqual(adjust.upper_wire, 'niti_014')
        self.assertEqual(adjust.next_visit_weeks, 6)
        adjust.write({'date': bonding.date + timedelta(days=42), 'upper_wire': 'niti_16x22',
                      'elastics': 'class_2', 'elastic_size': '3/16" 3.5 oz'})
        self.assertTrue(adjust.upper_wire_changed)
        self.assertFalse(adjust.lower_wire_changed)
        adjust.action_done()
        self.assertEqual(self.line.completed_visits, 2)
        self.assertEqual(chart.current_upper_wire, '0.016×0.022" NiTi')
        self.assertEqual(chart.current_elastics, 'Class II')
        self.assertIn('Elastics Class II', adjust.session_id.procedure_notes)
        self.assertEqual(len(self.env['dental.follow.up'].search(
            [('case_id', '=', self.case.id), ('state', '=', 'pending')])), 1, 'The next visit is moved, not duplicated')

        # A loose bracket and its re-bond
        tooth = chart.tooth_ids.filtered(lambda t: t.tooth_number == '12')
        tooth.action_mark_failed()
        self.assertEqual(chart.failed_count, 1)
        tooth.action_bond()
        self.assertEqual((tooth.status, tooth.rebond_count), ('bonded', 1))

        # Emergency visits are not billed as treatment visits
        emergency = self.env['dental.ortho.visit'].browse(chart.action_new_visit()['res_id'])
        emergency.visit_type = 'emergency'
        emergency.action_done()
        self.assertFalse(emergency.session_id)
        self.assertEqual(self.line.completed_visits, 2)

        # Debond: appliances removed, retention review booked
        debond = self.env['dental.ortho.visit'].browse(chart.action_new_visit()['res_id'])
        debond.visit_type = 'debond'
        chart.write({'retainer_upper': 'essix', 'retainer_lower': 'bonded', 'retention_review_months': 3})
        debond.action_done()
        self.assertEqual(chart.state, 'retention')
        self.assertFalse(chart.tooth_ids.filtered(lambda t: t.status == 'bonded'))
        review = self.env['dental.follow.up'].search([('case_id', '=', self.case.id), ('state', '=', 'pending')])
        self.assertEqual(len(review), 1)
        self.assertIn('Retention review', review.reason)
        chart.action_complete()
        self.assertEqual(chart.state, 'completed')
        with self.assertRaises(UserError):
            chart.action_new_visit()

    def test_aligner_chart_has_no_brackets(self):
        chart = self.env['dental.ortho.chart'].create({'patient_id': self.patient.id, 'appliance_type': 'aligners',
                                                       'arches': 'upper'})
        self.assertEqual(len(chart.tooth_ids), 16)
        self.assertFalse(chart.tooth_ids.filtered(lambda t: t.status != 'none'))

    def test_dentist_access_and_form(self):
        chart = self._chart().with_user(self.user)
        with Form(chart) as form:
            form.overjet = 5.0
            form.angle_class = 'class_2_div1'
        self.assertEqual(chart.overjet, 5.0)
        visit = self.env['dental.ortho.visit'].with_user(self.user).browse(chart.action_new_visit()['res_id'])
        self.assertTrue(visit.exists())
