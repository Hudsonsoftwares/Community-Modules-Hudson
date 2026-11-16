from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'insurance_base')
class TestInsuranceBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.insurer = Partner.create({'name': 'Star (test)', 'is_company': True,
                                      'insurance_partner_type': 'insurer'})
        cls.tpa = Partner.create({'name': 'MediAssist (test)', 'is_company': True,
                                  'insurance_partner_type': 'tpa'})
        cls.patient = Partner.create({'name': 'Anu (test)'})
        cls.root_categ = cls.env['product.category'].create({'name': 'Clinic (test)'})
        cls.child_categ = cls.env['product.category'].create({'name': 'Imaging (test)',
                                                              'parent_id': cls.root_categ.id})
        Product = cls.env['product.template']
        cls.xray = Product.create({'name': 'X-ray (test)', 'type': 'service', 'categ_id': cls.child_categ.id})
        cls.consult = Product.create({'name': 'Consult (test)', 'type': 'service', 'categ_id': cls.root_categ.id})
        cls.other = Product.create({'name': 'Other (test)', 'type': 'service'})
        cls.plan = cls.env['insurance.plan'].create({
            'name': 'Gold (test)', 'insurer_id': cls.insurer.id, 'tpa_id': cls.tpa.id,
            'coverage_line_ids': [
                fields.Command.create({'applies_to': 'all', 'coverage_percent': 10}),
                fields.Command.create({'applies_to': 'product_category', 'product_categ_id': cls.root_categ.id,
                                       'coverage_percent': 50}),
                fields.Command.create({'applies_to': 'product_category', 'product_categ_id': cls.child_categ.id,
                                       'coverage_percent': 70, 'requires_preauth': True}),
                fields.Command.create({'applies_to': 'product', 'product_tmpl_id': cls.consult.id,
                                       'covered': False}),
            ],
        })

    def _policy(self, **vals):
        return self.env['insurance.policy'].create(dict({
            'partner_id': self.patient.id, 'holder_id': self.patient.id,
            'plan_id': self.plan.id, 'member_id': 'M-%s' % len(self.patient.insurance_policy_ids),
        }, **vals))

    def test_coverage_most_specific_rule_wins(self):
        xray = self.plan._get_coverage(self.xray)
        self.assertEqual(xray['percent'], 70)            # own category beats parent category
        self.assertTrue(xray['requires_preauth'])
        self.assertFalse(self.plan._get_coverage(self.consult)['covered'])   # exact service exclusion
        self.assertEqual(self.plan._get_coverage(self.other)['percent'], 10)  # everything else

    def test_coverage_parent_category(self):
        self.plan.coverage_line_ids.filtered(lambda l: l.product_categ_id == self.child_categ).unlink()
        self.assertEqual(self.plan._get_coverage(self.xray)['percent'], 50)

    def test_rule_needs_target(self):
        with self.assertRaises(ValidationError):
            self.env['insurance.coverage.line'].create({'plan_id': self.plan.id, 'applies_to': 'product'})
        with self.assertRaises(ValidationError):
            self.env['insurance.coverage.line'].create({
                'plan_id': self.plan.id, 'applies_to': 'all', 'coverage_percent': 120})

    def test_policy_defaults_and_status(self):
        today = fields.Date.context_today(self.env['insurance.policy'])
        policy = self._policy()
        self.assertEqual(policy.insurer_id, self.insurer)
        self.assertEqual(policy.tpa_id, self.tpa)
        self.assertEqual(policy.payer_id, self.tpa)
        self.assertEqual(policy.status, 'valid')
        self.assertTrue(self.patient.has_valid_insurance)
        expired = self._policy(date_start=today - timedelta(days=400), date_end=today - timedelta(days=35))
        future = self._policy(date_start=today + timedelta(days=5))
        self.assertEqual(expired.status, 'expired')
        self.assertEqual(future.status, 'not_started')
        Policy = self.env['insurance.policy']
        mine = [('partner_id', '=', self.patient.id)]
        self.assertEqual(Policy.search(mine + [('status', '=', 'valid')]), policy)
        self.assertEqual(Policy.search(mine + [('status', '=', 'expired')]), expired)
        self.assertEqual(Policy.search(mine + [('status', 'in', ['expired', 'not_started'])]), expired | future)
        self.assertEqual(Policy.search(mine + [('status', '!=', 'valid')]), expired | future)
        with self.assertRaises(UserError):
            self._policy(date_start=today, date_end=today - timedelta(days=1))

    def test_manual_eligibility(self):
        policy = self._policy()
        action = policy.action_check_eligibility()
        check = self.env['insurance.eligibility'].browse(action['res_id'])
        self.assertEqual(check.connector, 'manual')
        self.assertEqual(check.payer_id, self.tpa)
        self.assertEqual(check.state, 'draft')
        self.assertTrue(check.name.startswith('ELG/'))
        check.action_send()
        self.assertEqual(check.state, 'waiting')
        check.write({'benefit_line_ids': [fields.Command.create({
            'name': 'OPD', 'allowed_amount': 5000, 'used_amount': 1200})]})
        self.assertEqual(check.benefit_line_ids.remaining_amount, 3800)
        check.action_mark_eligible()
        self.assertEqual(check.state, 'done')
        self.assertEqual(policy.eligibility_status, 'eligible')
        self.assertTrue(policy.last_verified_date)
        self.assertEqual(policy.last_eligibility_id, check)
        with self.assertRaises(UserError):
            check.action_send()
