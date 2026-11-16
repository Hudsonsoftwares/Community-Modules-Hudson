from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_subscription')
class TestDentalSubscription(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Membership Branch B'})
        cls.patient = cls.env['res.partner'].create({
            'name': 'Member Patient', 'is_dental_patient': True, 'phone': '9100000001', 'email': 'm@example.com'})
        cls.patient_2 = cls.env['res.partner'].create({
            'name': 'Second Patient', 'is_dental_patient': True, 'phone': '9100000002'})
        cls.consultation = cls.env.ref('dental_catalog.treatment_consultation')
        cls.scaling = cls.env.ref('dental_catalog.treatment_scaling')
        cls.crown = cls.env.ref('dental_catalog.treatment_crown')
        cls.monthly = cls.env.ref('hudson_subscriptions.subscription_plan_monthly')
        cls.membership_product = cls.env.ref('dental_subscription.product_membership_individual').product_variant_id
        cls.installment_product = cls.env.ref('dental_subscription.product_ortho_installment').product_variant_id
        cls.receptionist_a = new_test_user(
            cls.env, login='sub_reception_a', groups='base.group_user,dental_base.group_dental_receptionist,account.group_account_invoice',
            company_id=cls.company_a.id, company_ids=[cls.company_a.id])
        cls.dentist_a = new_test_user(
            cls.env, login='sub_dentist_a', groups='base.group_user,dental_base.group_dental_dentist',
            company_id=cls.company_a.id, company_ids=[cls.company_a.id])
        cls.manager_a = new_test_user(
            cls.env, login='sub_manager_a', groups='base.group_user,dental_base.group_dental_manager',
            company_id=cls.company_a.id, company_ids=[cls.company_a.id])

    def _subscription(self, product=None, members=None, company=None, partner=None, confirm=True):
        company = company or self.company_a
        order = self.env['sale.order'].with_company(company).create({
            'partner_id': (partner or self.patient).id,
            'company_id': company.id,
            'is_subscription': True,
            'plan_id': self.monthly.id,
            'start_date': fields.Date.today(),
            'dental_member_ids': [(6, 0, (members or self.patient).ids)],
            'order_line': [(0, 0, {'product_id': (product or self.membership_product).id, 'product_uom_qty': 1})],
        })
        if confirm:
            order.action_confirm()
        return order

    def _bill(self, product_tmpl, company=None, partner=None, qty=1.0, price=100.0):
        company = company or self.company_a
        line = {'product_id': product_tmpl.product_variant_id.id, 'name': product_tmpl.name,
                'quantity': qty, 'price_unit': price}
        invoice, _extended = self.env['account.move'].sudo()._dental_create_or_extend_invoice(
            partner or self.patient, company, [line], origin='TEST')
        return invoice

    # ------------------------------------------------------------------
    def test_type_members_and_benefits_copied(self):
        order = self._subscription()
        self.assertTrue(order.is_dental_subscription)
        self.assertEqual(order.dental_subscription_type, 'membership')
        self.assertEqual(order.subscription_state, '3_progress')
        self.assertEqual(order.dental_member_ids, self.patient)
        rules = self.membership_product.product_tmpl_id.dental_benefit_rule_ids
        self.assertEqual(len(order.dental_benefit_ids), len(rules))
        self.assertTrue(order.dental_benefits_active)

    def test_covered_benefit_applied_limited_and_released(self):
        order = self._subscription()
        consult_benefit = order.dental_benefit_ids.filtered(lambda b: b.treatment_id == self.consultation)
        inv1 = self._bill(self.consultation)
        line = inv1.invoice_line_ids
        self.assertEqual(line.discount, 100.0)
        self.assertEqual(line.dental_subscription_benefit_id, consult_benefit)
        self.assertEqual(inv1.amount_untaxed, 0.0)
        self._bill(self.consultation)
        consult_benefit.invalidate_recordset()
        self.assertEqual(consult_benefit.remaining_qty, 0.0)
        # Third consultation: covered uses exhausted, the 15% catch-all discount applies instead
        inv3 = self._bill(self.consultation)
        self.assertEqual(inv3.invoice_line_ids.discount, 15.0)
        # Cancelling an invoice gives the use back
        inv1.button_cancel()
        consult_benefit.invalidate_recordset()
        self.assertEqual(consult_benefit.remaining_qty, 1.0)

    def test_discount_rule_on_other_treatment(self):
        self._subscription()
        invoice = self._bill(self.crown, price=500.0)
        self.assertEqual(invoice.invoice_line_ids.discount, 15.0)
        self.assertAlmostEqual(invoice.amount_untaxed, 425.0)

    def test_no_benefit_for_non_member_or_other_branch(self):
        self._subscription()
        self.assertFalse(self._bill(self.consultation, partner=self.patient_2).invoice_line_ids.discount)
        vals = [{'product_id': self.consultation.product_variant_id.id, 'quantity': 1, 'price_unit': 50}]
        res_b = self.env['sale.order']._dental_apply_membership_benefits(self.patient, self.company_b, vals)
        self.assertFalse(res_b[0].get('discount'), "A membership of branch A gives nothing at branch B")

    def test_paused_or_expired_membership_gives_nothing(self):
        order = self._subscription()
        order.action_pause_subscription()
        self.assertFalse(self._bill(self.consultation).invoice_line_ids.discount)
        order.action_resume_subscription()
        order.end_date = fields.Date.today() - timedelta(days=1)
        self.assertFalse(self._bill(self.consultation).invoice_line_ids.discount)

    def test_duplicate_membership_blocked(self):
        self._subscription()
        with self.assertRaises(ValidationError):
            self._subscription()
        # Same patient at another branch is a separate contract
        self._subscription(company=self.company_b)

    def test_member_limit_and_patients_only(self):
        with self.assertRaises(ValidationError):
            self._subscription(members=self.patient | self.patient_2, confirm=False)
        not_patient = self.env['res.partner'].create({'name': 'Company Contact'})
        family = self.env.ref('dental_subscription.product_membership_family').product_variant_id
        # Odoo 20 enforces the field domain (patients only) on write; the constraint backs it up
        with self.assertRaises((ValidationError, ValueError)):
            self._subscription(product=family, members=self.patient | not_patient, confirm=False)
        order = self._subscription(product=family, members=self.patient | self.patient_2)
        self.assertEqual(order.dental_member_count, 2)
        # The family benefit is shared: the second member uses it too
        self.assertEqual(self._bill(self.consultation, partner=self.patient_2).invoice_line_ids.discount, 100.0)

    def test_installment_plan_covers_sessions_and_closes(self):
        doctor = self.env['hr.employee'].create({'name': 'Dr. Ortho', 'dental_role': 'dentist', 'company_id': self.company_a.id})
        appt = self.env['dental.appointment'].create({
            'patient_id': self.patient.id, 'doctor_id': doctor.id, 'branch_id': self.company_a.id, 'state': 'confirmed',
            'date_start': fields.Datetime.now(), 'date_end': fields.Datetime.now() + timedelta(minutes=30)})
        plan = self.env['dental.treatment.plan'].create({
            'patient_id': self.patient.id, 'appointment_id': appt.id, 'state': 'approved',
            'line_ids': [(0, 0, {'treatment_id': self.crown.id, 'unit_price': 1200})]})
        wizard = self.env['dental.installment.wizard'].with_context(default_treatment_plan_id=plan.id).create({
            'product_id': self.installment_product.id, 'plan_id': self.monthly.id,
            'installment_count': 3, 'amount_financed': 1200})
        order = self.env['sale.order'].browse(wizard.action_create_installment_plan()['res_id'])
        self.assertEqual(order.order_line.price_unit, 400.0)
        order.action_confirm()
        self.assertEqual(order.end_date, fields.Date.today() + relativedelta(months=3, days=-1))
        # Financing twice is refused
        with self.assertRaises(UserError):
            self.env['dental.installment.wizard'].with_context(default_treatment_plan_id=plan.id).create({
                'product_id': self.installment_product.id, 'plan_id': self.monthly.id,
                'installment_count': 3, 'amount_financed': 1200}).action_create_installment_plan()
        # A session of the plan is billed at zero
        session = self.env['dental.treatment.session'].create({
            'patient_id': self.patient.id, 'plan_id': plan.id, 'plan_line_id': plan.line_ids.id})
        vals = session._prepare_invoice_line_vals()
        invoice, _ext = self.env['account.move'].sudo()._dental_create_or_extend_invoice(
            self.patient, self.company_a, [vals], origin='TEST')
        self.assertEqual(invoice.invoice_line_ids.discount, 100.0)
        # Three installments, then the contract closes itself and refuses a fourth
        for _i in range(3):
            order._create_subscription_invoice()
        self.assertEqual(order.subscription_state, '6_churn')
        self.assertEqual(order.close_reason_id, self.env.ref('dental_subscription.close_reason_installments_completed'))
        with self.assertRaises(UserError):
            order._create_subscription_invoice()
        # Sessions stay covered after completion
        self.assertTrue(order._dental_benefits_usable_on(fields.Date.today())[0])

    def test_overdue_suspends_benefits_and_reminds(self):
        order = self._subscription()
        invoice = order._create_subscription_invoice()
        invoice.invoice_date = fields.Date.today() - timedelta(days=60)
        invoice.invoice_date_due = fields.Date.today() - timedelta(days=45)
        invoice.action_post()
        invoice.invoice_date_due = fields.Date.today() - timedelta(days=45)
        order.invalidate_recordset()
        self.assertEqual(order.dental_payment_status, 'overdue')
        self.assertFalse(order.dental_benefits_active, "45 days overdue exceeds the 15-day grace of the monthly plan")
        self.env['sale.order']._cron_dental_subscription_lifecycle()
        self.assertEqual(order.dental_overdue_reminder_date, fields.Date.today())

    def test_branch_isolation_of_benefits(self):
        order_b = self._subscription(company=self.company_b)
        Benefit = self.env['dental.subscription.benefit'].with_user(self.receptionist_a)
        self.assertFalse(Benefit.search([('id', 'in', order_b.dental_benefit_ids.ids)]))
        with self.assertRaises(AccessError):
            order_b.dental_benefit_ids.with_user(self.receptionist_a).read(['name'])
        with self.assertRaises(AccessError):
            self.env['sale.order'].with_user(self.receptionist_a).browse(order_b.id).read(['name'])

    def test_dashboard_access_and_branch(self):
        self._subscription()
        data = self.env['sale.order'].with_user(self.manager_a).get_dental_subscription_dashboard(self.company_a.id)
        self.assertEqual(data['kpis']['active']['value'], 1)
        with self.assertRaises(AccessError):
            self.env['sale.order'].with_user(self.manager_a).get_dental_subscription_dashboard(self.company_b.id)
        with self.assertRaises(AccessError):
            self.env['sale.order'].with_user(self.dentist_a).get_dental_subscription_dashboard(self.company_a.id)

    def test_receptionist_can_sell_membership(self):
        order = self.env['sale.order'].with_user(self.receptionist_a).create({
            'partner_id': self.patient.id, 'is_subscription': True, 'plan_id': self.monthly.id,
            'order_line': [(0, 0, {'product_id': self.membership_product.id})],
        })
        order._onchange_dental_members()
        order.dental_member_ids = self.patient
        order.action_confirm()
        self.assertTrue(order.dental_benefit_ids)
