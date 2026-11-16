from datetime import datetime, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_multi_company')
class TestDentalMultiCompany(TransactionCase):
    """Branch B data must stay invisible and unlinkable for users of branch A (see dental_base/SECURITY.md)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Dental Branch B'})
        cls.patient = cls.env['res.partner'].create({'name': 'Shared Patient', 'is_dental_patient': True, 'phone': '9000000001'})
        cls.doctor_a = cls.env['hr.employee'].create({'name': 'Dr. A', 'dental_role': 'dentist', 'company_id': cls.company_a.id})
        cls.doctor_b = cls.env['hr.employee'].create({'name': 'Dr. B', 'dental_role': 'dentist', 'company_id': cls.company_b.id})
        cls.treatment = cls.env.ref('dental_catalog.treatment_crown')

        common = {'company_id': cls.company_a.id, 'company_ids': [cls.company_a.id]}
        cls.manager_a = new_test_user(cls.env, login='mc_manager_a', groups='base.group_user,dental_base.group_dental_manager', **common)
        cls.receptionist_a = new_test_user(cls.env, login='mc_reception_a', groups='base.group_user,dental_base.group_dental_receptionist', **common)
        cls.dentist_a = new_test_user(cls.env, login='mc_dentist_a', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.doctor_a.user_id = cls.dentist_a
        cls.manager_ab = new_test_user(cls.env, login='mc_manager_ab', groups='base.group_user,dental_base.group_dental_manager',
                                       company_id=cls.company_a.id, company_ids=[cls.company_a.id, cls.company_b.id])

        cls.b = cls._create_branch_records(cls.company_b, cls.doctor_b, day=3)
        cls.a = cls._create_branch_records(cls.company_a, cls.doctor_a, day=4)

    @classmethod
    def _create_branch_records(cls, company, doctor, day):
        env = cls.env['dental.case'].with_company(company).env
        start = datetime.now().replace(hour=4, minute=0, second=0, microsecond=0) + timedelta(days=day)
        appt = env['dental.appointment'].create({
            'patient_id': cls.patient.id, 'doctor_id': doctor.id, 'branch_id': company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
        })
        case = env['dental.case'].create({'patient_id': cls.patient.id, 'doctor_id': doctor.id,
                                          'appointment_id': appt.id, 'chief_complaint': 'Pain'})
        plan = env['dental.treatment.plan'].create({
            'patient_id': cls.patient.id, 'case_id': case.id,
            'line_ids': [(0, 0, {'treatment_id': cls.treatment.id, 'unit_price': 100})],
        })
        records = {
            'dental.appointment': appt,
            'dental.case': case,
            'dental.clinical.examination': env['dental.clinical.examination'].create(
                {'patient_id': cls.patient.id, 'case_id': case.id, 'appointment_id': appt.id}),
            'dental.patient.diagnosis': env['dental.patient.diagnosis'].create({
                'patient_id': cls.patient.id, 'case_id': case.id,
                'diagnosis_id': env['dental.diagnosis'].create({'name': 'Caries %s' % company.name}).id}),
            'dental.tooth.finding': env['dental.tooth.finding'].create(
                {'patient_id': cls.patient.id, 'case_id': case.id, 'tooth_number': '36', 'condition': 'caries'}),
            'dental.treatment.plan': plan,
            'dental.treatment.plan.line': plan.line_ids,
            'dental.treatment.session': env['dental.treatment.session'].create(
                {'patient_id': cls.patient.id, 'case_id': case.id, 'plan_id': plan.id, 'plan_line_id': plan.line_ids.id}),
            'dental.follow.up': env['dental.follow.up'].create(
                {'patient_id': cls.patient.id, 'case_id': case.id, 'appointment_id': appt.id}),
            'dental.recall': env['dental.recall'].create(
                {'patient_id': cls.patient.id, 'last_appointment_id': appt.id, 'due_date': start.date()}),
            'dental.waiting.list': env['dental.waiting.list'].create({'patient_id': cls.patient.id}),
        }
        return records

    # ------------------------------------------------------------------
    def test_company_follows_parent(self):
        """Child records inherit the branch of their case/appointment, not the user's current company."""
        for model, record in self.b.items():
            if model == 'dental.waiting.list':
                continue  # no parent: takes the creating company
            self.assertEqual(record.company_id, self.company_b, model)
        self.assertEqual(self.b['dental.waiting.list'].company_id, self.company_b)

    def test_users_of_branch_a_cannot_see_branch_b(self):
        for user in (self.manager_a, self.receptionist_a, self.dentist_a):
            for model, record in self.b.items():
                Model = self.env[model].with_user(user)
                if not Model.has_access('read'):
                    continue  # the group has no access to this model at all
                self.assertFalse(Model.search([('id', '=', record.id)]),
                                 '%s sees branch B %s' % (user.login, model))
                with self.assertRaises(AccessError, msg='%s reads branch B %s' % (user.login, model)):
                    record.with_user(user).read(['company_id'])

    def test_branch_a_records_still_visible(self):
        """Isolation must not break normal access inside the user's own branch."""
        for model in ('dental.appointment', 'dental.case', 'dental.treatment.plan', 'dental.follow.up'):
            self.assertTrue(self.env[model].with_user(self.manager_a).search([('id', '=', self.a[model].id)]), model)

    def test_receptionist_unfiltered_group_row_no_longer_leaks(self):
        """Root cause: the receptionist's unfiltered appointment permission row used to OR away the branch filter."""
        appts = self.env['dental.appointment'].with_user(self.receptionist_a).search([('patient_id', '=', self.patient.id)])
        self.assertIn(self.a['dental.appointment'], appts)
        self.assertNotIn(self.b['dental.appointment'], appts)

    def test_multi_branch_user_sees_selected_branches_only(self):
        Appt = self.env['dental.appointment'].with_user(self.manager_ab)
        both = Appt.with_context(allowed_company_ids=[self.company_a.id, self.company_b.id]).search([('patient_id', '=', self.patient.id)])
        self.assertIn(self.b['dental.appointment'], both)
        only_a = Appt.with_context(allowed_company_ids=[self.company_a.id]).search([('patient_id', '=', self.patient.id)])
        self.assertNotIn(self.b['dental.appointment'], only_a)

    def test_shared_records_stay_shared(self):
        env = self.env(user=self.manager_a)
        self.assertTrue(env['res.partner'].search([('id', '=', self.patient.id)]), 'patients are shared across branches')
        self.assertTrue(env['dental.diagnosis'].search([('id', '=', self.b['dental.patient.diagnosis'].diagnosis_id.id)]),
                        'diagnosis master is shared')

    def test_treatment_history_visible_from_other_branch(self):
        """A returning patient's history from branch B is readable in branch A, the B records themselves are not."""
        patient = self.patient.with_user(self.dentist_a)
        history = patient.dental_history_ids
        for record_type in ('case', 'consultation', 'diagnosis', 'finding', 'plan', 'session'):
            for branch in (self.company_a, self.company_b):
                line = history.filtered(lambda h: h.record_type == record_type and h.branch_name == branch.name)
                self.assertEqual(len(line), 1, '%s of %s missing from history' % (record_type, branch.name))
                self.assertEqual(line.other_branch, branch == self.company_b)
        plan_b = history.filtered(lambda h: h.record_type == 'plan' and h.branch_name == self.company_b.name)
        self.assertIn(self.treatment.name, plan_b.description)
        self.assertEqual(self.a['dental.case'].with_user(self.dentist_a).patient_history_line_ids, history)
        # read-only, and the branch B records stay closed
        with self.assertRaises(AccessError):
            history[:1].write({'description': 'changed'})
        with self.assertRaises(AccessError):
            self.b['dental.case'].with_user(self.dentist_a).read(['chief_complaint'])

    def test_treatment_history_limited_to_clinical_roles(self):
        self.assertFalse(self.env['dental.patient.history'].with_user(self.receptionist_a).has_access('read'))
        self.assertTrue(self.env['dental.patient.history'].with_user(self.manager_a).search_count([('patient_id', '=', self.patient.id)]))

    def test_patient_found_from_any_branch_by_id_or_phone(self):
        Partner = self.env['res.partner'].with_user(self.receptionist_a)
        for term in (self.patient.dental_patient_id, self.patient.phone):
            found = Partner.search([('display_name', 'ilike', term)])
            self.assertIn(self.patient, found, term)
        # a patient is never tied to one branch
        self.patient.company_id = self.company_b
        self.assertFalse(self.patient.company_id)
        new = self.env['res.partner'].with_company(self.company_b).create(
            {'name': 'Walk-in', 'is_dental_patient': True, 'company_id': self.company_b.id})
        self.assertFalse(new.company_id)
        self.assertTrue(Partner.search([('id', '=', new.id)]))

    def test_cross_branch_links_rejected(self):
        """check_company: an A record can never point to a B record, even when created with sudo."""
        env_a = self.env['dental.case'].with_company(self.company_a).env
        with self.assertRaises((UserError, ValidationError)):
            env_a['dental.clinical.examination'].create({
                'patient_id': self.patient.id, 'case_id': self.a['dental.case'].id,
                'appointment_id': self.b['dental.appointment'].id})
        with self.assertRaises((UserError, ValidationError)):
            self.a['dental.treatment.session'].write({'appointment_id': self.b['dental.appointment'].id})
        with self.assertRaises((UserError, ValidationError)):
            self.a['dental.appointment'].write({'case_id': self.b['dental.case'].id})

    def test_booking_cannot_target_foreign_branch(self):
        """The booking engine runs with sudo: an internal user must not book or probe another branch."""
        Appt = self.env['dental.appointment'].with_user(self.receptionist_a)
        with self.assertRaises(AccessError):
            Appt.get_available_slots(branch_id=self.company_b.id)
        with self.assertRaises(AccessError):
            Appt.get_bookable_services(branch_id=self.company_b.id)
        with self.assertRaises(AccessError):
            Appt.create_appointment_booking({
                'patient_type': 'returning', 'patient_id': self.patient.id, 'name': self.patient.name,
                'phone': self.patient.phone, 'branch_id': self.company_b.id,
                'appointment_date': (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d'), 'appointment_time': '10:00'})
        # own branch still works
        self.assertTrue(Appt.get_available_slots(branch_id=self.company_a.id)['success'])

    def test_public_booking_any_branch(self):
        """Public website booking (sudo controllers) may target any branch."""
        public = self.env.ref('base.public_user')
        res = self.env['dental.appointment'].with_user(public).sudo().get_available_slots(branch_id=self.company_b.id)
        self.assertTrue(res['success'])

    def test_dashboards_cannot_target_foreign_branch(self):
        Appt = self.env['dental.appointment'].with_user(self.manager_a)
        for method in ('get_reception_dashboard_data', 'get_waiting_queue_board_data', 'get_admin_dashboard_data'):
            with self.assertRaises(AccessError, msg=method):
                getattr(Appt, method)(branch_id=self.company_b.id)

    def test_sudo_billing_actions_respect_branch(self):
        """Billing actions read the case with sudo; they must refuse records of another branch."""
        with self.assertRaises(AccessError):
            self.b['dental.case'].with_user(self.manager_a).action_create_invoice()
        with self.assertRaises(AccessError):
            self.b['dental.appointment'].with_user(self.manager_a).action_create_invoice()

    def test_ready_for_billing_search_does_not_leak(self):
        self.b['dental.appointment'].write({'state': 'completed'})
        found = self.env['dental.appointment'].with_user(self.manager_a).search([('billing_state', '=', 'to_invoice')])
        self.assertNotIn(self.b['dental.appointment'], found)

    def test_continue_case_never_crosses_branch(self):
        """A returning patient seen in branch A must not continue (and so expose) branch B's open case."""
        self.a['dental.case'].state = 'completed'
        start = datetime.now().replace(hour=5, minute=0, second=0, microsecond=0) + timedelta(days=6)
        visit = self.env['dental.appointment'].with_company(self.company_a).create({
            'patient_id': self.patient.id, 'doctor_id': self.doctor_a.id, 'branch_id': self.company_a.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'checked_in'})
        action = visit.with_user(self.manager_a).action_open_clinical_case()
        case = self.env['dental.case'].browse(action['res_id'])
        self.assertNotEqual(case, self.b['dental.case'])
        self.assertEqual(case.company_id, self.company_a)
