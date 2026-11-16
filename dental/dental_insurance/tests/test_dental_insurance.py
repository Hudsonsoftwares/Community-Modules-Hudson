from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dental_insurance')
class TestDentalInsurance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.insurer = cls.env['res.partner'].create({
            'name': 'Dental Insurer', 'is_company': True, 'insurance_partner_type': 'insurer'})
        cls.endo = cls.env['dental.treatment.category'].create({'name': 'Endodontics (test)'})
        cls.cosmetic = cls.env['dental.treatment.category'].create({'name': 'Cosmetic (test)'})
        cls.product_categ = cls.env['product.category'].create({'name': 'Dental Services (test)'})
        Product = cls.env['product.template']
        cls.rct = Product.create({'name': 'RCT (test)', 'type': 'service', 'is_dental_treatment': True,
                                  'dental_treatment_category_id': cls.endo.id, 'categ_id': cls.product_categ.id})
        cls.retreat = Product.create({'name': 'Re-RCT (test)', 'type': 'service', 'is_dental_treatment': True,
                                      'dental_treatment_category_id': cls.endo.id, 'categ_id': cls.product_categ.id})
        cls.veneer = Product.create({'name': 'Veneer (test)', 'type': 'service', 'is_dental_treatment': True,
                                     'dental_treatment_category_id': cls.cosmetic.id, 'categ_id': cls.product_categ.id})
        cls.plan = cls.env['insurance.plan'].create({
            'name': 'Dental Gold',
            'insurer_id': cls.insurer.id,
            'coverage_line_ids': [
                fields.Command.create({'applies_to': 'product_category', 'product_categ_id': cls.product_categ.id,
                                       'coverage_percent': 40}),
                fields.Command.create({'applies_to': 'dental_category',
                                       'dental_treatment_category_id': cls.endo.id, 'coverage_percent': 80}),
                fields.Command.create({'applies_to': 'product', 'product_tmpl_id': cls.retreat.id,
                                       'coverage_percent': 60}),
                fields.Command.create({'applies_to': 'dental_category',
                                       'dental_treatment_category_id': cls.cosmetic.id, 'covered': False}),
            ],
        })

    def test_dental_category_between_service_and_product_category(self):
        self.assertEqual(self.plan._get_coverage(self.rct)['percent'], 80)       # dental category
        self.assertEqual(self.plan._get_coverage(self.retreat)['percent'], 60)   # exact service wins
        self.assertFalse(self.plan._get_coverage(self.veneer)['covered'])        # cosmetic excluded
        no_dental_categ = self.env['product.template'].create({
            'name': 'X-ray (test)', 'type': 'service', 'categ_id': self.product_categ.id})
        self.assertEqual(self.plan._get_coverage(no_dental_categ)['percent'], 40)

    def test_dental_category_rule_needs_category(self):
        with self.assertRaises(ValidationError):
            self.env['insurance.coverage.line'].create({'plan_id': self.plan.id, 'applies_to': 'dental_category'})

    def test_patient_policy_from_patient_form(self):
        patient = self.env['res.partner'].create({'name': 'Riya (test)', 'is_dental_patient': True})
        patient.write({'insurance_policy_ids': [fields.Command.create({
            'plan_id': self.plan.id, 'member_id': 'RIYA-1', 'holder_id': patient.id})]})
        self.assertEqual(patient.insurance_policy_count, 1)
        self.assertTrue(patient.has_valid_insurance)
        self.assertEqual(patient.insurance_policy_ids.insurer_id, self.insurer)

    def test_dental_roles_get_insurance_rights(self):
        receptionist = self.env.ref('dental_base.group_dental_receptionist')
        manager = self.env.ref('dental_base.group_dental_manager')
        self.assertIn(self.env.ref('insurance_base.group_insurance_user'), receptionist.all_implied_ids)
        self.assertIn(self.env.ref('insurance_base.group_insurance_manager'), manager.all_implied_ids)
