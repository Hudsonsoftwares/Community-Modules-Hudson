# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_second_opinion')
class SecondOpinionCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Second Opinion Branch B'})
        common = {'company_id': cls.company_a.id, 'company_ids': [cls.company_a.id]}
        cls.dentist = new_test_user(cls.env, login='so_dentist', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.other_dentist = new_test_user(cls.env, login='so_other', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.specialist = new_test_user(cls.env, login='so_specialist', groups='base.group_user,dental_second_opinion.group_dental_specialist', **common)
        cls.manager = new_test_user(cls.env, login='so_manager', groups='base.group_user,dental_base.group_dental_manager', **common)
        Employee = cls.env['hr.employee']
        cls.dentist_emp = Employee.create({'name': 'Dr. Requester', 'dental_role': 'dentist', 'user_id': cls.dentist.id,
                                           'company_id': cls.company_a.id})
        cls.specialist_emp = Employee.create({'name': 'Dr. Endo Specialist', 'dental_role': 'dentist', 'user_id': cls.specialist.id,
                                              'specialization': 'Endodontics', 'company_id': cls.company_a.id})
        cls.patient = cls.env['res.partner'].create({'name': 'SO Patient', 'is_dental_patient': True})
        cls.case = cls.env['dental.case'].create({
            'patient_id': cls.patient.id, 'doctor_id': cls.dentist_emp.id, 'company_id': cls.company_a.id,
            'chief_complaint': 'Pain on 36', 'allergies': 'Penicillin'})
        cls.exam = cls.env['dental.clinical.examination'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id, 'doctor_id': cls.dentist_emp.id,
            'clinical_findings': 'Deep distal caries 36'})
        cls.plan = cls.env['dental.treatment.plan'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id, 'doctor_id': cls.dentist_emp.id})
        cls.document = cls.env['dental.patient.document'].create({
            'patient_id': cls.patient.id, 'name': 'IOPA 36', 'document_type': 'xray',
            'file': 'aGVsbG8=', 'file_name': 'iopa36.png', 'company_id': cls.company_a.id})

    def _new_request(self, user=None, **vals):
        return self.env['dental.second.opinion'].with_user(user or self.dentist).create(dict({
            'case_id': self.case.id,
            'specialist_id': self.specialist_emp.id,
            'clinical_question': 'Restore or extract 36?',
            'examination_ids': [(6, 0, self.exam.ids)],
            'document_ids': [(6, 0, self.document.ids)],
            'treatment_plan_id': self.plan.id,
        }, **vals))

    def _opinion(self, request):
        request.with_user(self.specialist).write({
            'findings': '<p>Caries reaches the pulp; roots are sound.</p>',
            'recommendations': '<p>Root canal treatment then crown.</p>',
            'recommended_action': 'modify',
        })


class TestSecondOpinionWorkflow(SecondOpinionCommon):

    def test_full_workflow(self):
        request = self._new_request()
        self.assertEqual(request.state, 'draft')
        self.assertEqual(request.requesting_user_id, self.dentist)
        self.assertEqual(request.company_id, self.company_a)
        self.assertEqual(request.requesting_doctor_id.id, self.dentist_emp.id)
        self.assertTrue(request.name.startswith('SOP/'))

        # A draft is invisible to the specialist
        self.assertFalse(self.env['dental.second.opinion'].with_user(self.specialist).search([('id', '=', request.id)]))

        request.with_user(self.dentist).action_submit()
        self.assertEqual(request.state, 'submitted')
        activity = request.activity_ids
        self.assertEqual(activity.user_id, self.specialist, 'The specialist gets a review to-do')
        self.assertIn(self.specialist.partner_id, request.message_partner_ids)

        as_specialist = request.with_user(self.specialist)
        as_specialist.action_start_review()
        self.assertEqual(request.state, 'in_review')
        # The specialist reads the referred case and its shared clinical records, read only
        self.case.with_user(self.specialist).read(['chief_complaint'])
        self.exam.with_user(self.specialist).read(['clinical_findings'])
        self.plan.with_user(self.specialist).read(['name'])
        self.document.with_user(self.specialist).read(['name'])
        self.assertEqual(as_specialist.allergies, 'Penicillin')
        with self.assertRaises(AccessError):
            self.case.with_user(self.specialist).write({'clinical_notes': 'edited by specialist'})

        self._opinion(request)
        as_specialist.action_submit_opinion()
        self.assertEqual(request.state, 'opinion_submitted')
        self.assertEqual(request.opinion_revision, 1)
        self.assertTrue(request.opinion_date)
        self.assertEqual(request.activity_ids.user_id, self.dentist, 'The requesting dentist is asked to decide')

        request.with_user(self.dentist).action_request_clarification('Is the crown mandatory?')
        self.assertEqual(request.state, 'clarification')
        self.assertEqual(request.activity_ids.user_id, self.specialist)
        as_specialist.write({'recommendations': '<p>RCT, then a full-coverage crown (cusp protection).</p>'})
        as_specialist.action_submit_opinion()
        self.assertEqual(request.opinion_revision, 2)

        plan_before = self.plan.read(['state', 'line_ids', 'write_date'])[0]
        wizard = self.env['dental.second.opinion.wizard'].with_user(self.dentist).create({
            'request_id': request.id, 'action': 'decision', 'decision': 'accepted', 'note': 'Will plan RCT + crown.'})
        wizard.action_confirm()
        self.assertEqual(request.state, 'closed')
        self.assertEqual(request.decision, 'accepted')
        self.assertEqual(request.decided_by_id, self.dentist)
        self.assertFalse(request.activity_ids)
        self.assertEqual(self.plan.read(['state', 'line_ids', 'write_date'])[0], plan_before,
                         'Recording a decision must never change the treatment plan')

        events = request.log_ids.sorted('id').mapped('event')
        self.assertEqual(events, ['created', 'submitted', 'review_started', 'opinion_submitted',
                                  'clarification_requested', 'opinion_revised', 'decision_recorded'])
        revision_1 = request.log_ids.filtered(lambda l: l.event == 'opinion_submitted')
        self.assertIn('Root canal treatment then crown.', revision_1.note, 'Each submitted opinion is snapshotted')

    def test_information_request_and_decline(self):
        request = self._new_request()
        request.with_user(self.dentist).action_submit()
        as_specialist = request.with_user(self.specialist)
        as_specialist.action_start_review()
        as_specialist.action_request_info('Please share a CBCT.')
        self.assertEqual(request.state, 'info_requested')
        # The requester may add records while information is requested
        request.with_user(self.dentist).write({'clinical_summary': 'CBCT attached'})
        request.with_user(self.dentist).action_provide_info('CBCT uploaded.')
        self.assertEqual(request.state, 'in_review')

        as_specialist.action_decline('Outside my specialty.')
        self.assertEqual(request.state, 'declined')
        self.assertEqual(request.activity_ids.user_id, self.dentist)
        request.with_user(self.dentist).action_reset_to_draft()
        self.assertEqual(request.state, 'draft')
        self.assertFalse(request.submitted_date)
        self.assertFalse(self.env['dental.second.opinion'].with_user(self.specialist).search([('id', '=', request.id)]),
                         'A reset request is hidden from the previous specialist until it is sent again')
        with self.assertRaises(AccessError):
            self.case.with_user(self.specialist).read(['chief_complaint'])

    def test_opinion_requires_content(self):
        request = self._new_request()
        request.with_user(self.dentist).action_submit()
        request.with_user(self.specialist).action_start_review()
        with self.assertRaises(UserError):
            request.with_user(self.specialist).action_submit_opinion()

    def test_case_smart_button(self):
        self._new_request()
        self.assertEqual(self.case.with_user(self.dentist).second_opinion_count, 1)

    def _run_case_menu_action(self, xmlid, user):
        """Run a case form Actions (cog) menu entry the way the web client does."""
        server_action = self.env.ref(xmlid).with_user(user).with_context(
            active_model='dental.case', active_id=self.case.id, active_ids=self.case.ids)
        return server_action.run()

    def test_request_from_case_actions_menu(self):
        xmlid = 'dental_second_opinion.action_server_dental_case_request_second_opinion'
        menu = self.env['ir.actions.actions'].with_user(self.dentist).get_bindings('dental.case')['action']
        self.assertIn('Request Second Opinion', [a['name'] for a in menu])
        action = self._run_case_menu_action(xmlid, self.dentist)
        self.assertEqual(action['res_model'], 'dental.second.opinion')
        self.assertEqual(action['context']['default_case_id'], self.case.id)
        # Same audience as the former header button (Dentist / Clinic Manager): hidden and refused for others
        clerk = new_test_user(self.env, login='so_clerk', groups='base.group_user')
        clerk_menu = self.env['ir.actions.actions'].with_user(clerk).get_bindings('dental.case').get('action', ())
        self.assertNotIn('Request Second Opinion', [a['name'] for a in clerk_menu])
        with self.assertRaises(AccessError):
            self._run_case_menu_action(xmlid, clerk)

    def test_no_second_opinion_on_cancelled_case(self):
        self.case.state = 'cancelled'
        with self.assertRaises(UserError):
            self.case.with_user(self.dentist).action_request_second_opinion()


class TestSecondOpinionSecurity(SecondOpinionCommon):

    def test_roles_are_separated(self):
        request = self._new_request()
        # Nobody changes the status or decision directly
        with self.assertRaises(UserError):
            request.with_user(self.dentist).write({'state': 'closed'})
        with self.assertRaises(UserError):
            request.with_user(self.manager).write({'decision': 'accepted'})
        # Only the specialist acts as specialist, only the requester as requester
        with self.assertRaises(AccessError):
            request.with_user(self.specialist).action_submit()
        request.with_user(self.dentist).action_submit()
        with self.assertRaises(AccessError):
            request.with_user(self.dentist).action_start_review()
        request.with_user(self.specialist).action_start_review()
        with self.assertRaises(AccessError):
            request.with_user(self.dentist).write({'findings': '<p>self-review</p>'})
        with self.assertRaises(AccessError):
            request.with_user(self.specialist).write({'clinical_question': 'changed'})
        with self.assertRaises(UserError):
            request.with_user(self.dentist).write({'clinical_question': 'changed while under review'})
        with self.assertRaises(UserError):
            request.with_user(self.dentist).unlink()

    def test_unrelated_dentist_cannot_see_request(self):
        request = self._new_request()
        request.with_user(self.dentist).action_submit()
        self.assertFalse(self.env['dental.second.opinion'].with_user(self.other_dentist).search([('id', '=', request.id)]))
        with self.assertRaises(AccessError):
            request.with_user(self.other_dentist).read(['name'])
        self.assertTrue(self.env['dental.second.opinion'].with_user(self.manager).search([('id', '=', request.id)]))

    def test_specialist_only_sees_referred_cases(self):
        other_case = self.env['dental.case'].create({
            'patient_id': self.patient.id, 'doctor_id': self.dentist_emp.id, 'company_id': self.company_a.id})
        request = self._new_request()
        request.with_user(self.dentist).action_submit()
        self.case.with_user(self.specialist).read(['name'])
        with self.assertRaises(AccessError):
            other_case.with_user(self.specialist).read(['name'])
        request.with_user(self.dentist).action_cancel()
        with self.assertRaises(AccessError):
            self.case.with_user(self.specialist).read(['name'])

    def test_specialist_must_be_eligible(self):
        other_emp = self.env['hr.employee'].create({
            'name': 'Dr. Not Specialist', 'dental_role': 'dentist', 'user_id': self.other_dentist.id})
        with self.assertRaises(ValidationError):
            self._new_request(specialist_id=other_emp.id)
        with self.assertRaises(ValidationError):  # nobody reviews their own request
            self.env['dental.second.opinion'].create({
                'case_id': self.case.id, 'specialist_id': self.specialist_emp.id,
                'requesting_user_id': self.specialist.id, 'clinical_question': 'x'})
        request = self._new_request()
        self.assertIn(self.specialist_emp.id, request.eligible_specialist_ids.ids)
        self.assertNotIn(other_emp.id, request.eligible_specialist_ids.ids)

    def test_shared_records_must_belong_to_case(self):
        other_case = self.env['dental.case'].create({
            'patient_id': self.patient.id, 'doctor_id': self.dentist_emp.id, 'company_id': self.company_a.id})
        other_exam = self.env['dental.clinical.examination'].create({
            'patient_id': self.patient.id, 'case_id': other_case.id, 'doctor_id': self.dentist_emp.id})
        with self.assertRaises(ValidationError):
            self._new_request(examination_ids=[(6, 0, other_exam.ids)])

    def test_audit_log_is_immutable(self):
        request = self._new_request()
        log = request.log_ids
        with self.assertRaises((UserError, AccessError)):
            log.with_user(self.manager).write({'note': 'tampered'})
        with self.assertRaises(UserError):
            log.sudo().write({'note': 'tampered'})
        with self.assertRaises(UserError):
            log.sudo().unlink()
        self.assertTrue(log.with_user(self.dentist).read(['event']))
        with self.assertRaises(AccessError):
            log.with_user(self.other_dentist).read(['event'])


@tagged('post_install', '-at_install', 'dental_multi_company', 'dental_second_opinion')
class TestSecondOpinionMultiCompany(SecondOpinionCommon):
    """Requests and their audit history stay inside their branch (see dental_base/SECURITY.md)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.case_b = cls.env['dental.case'].with_company(cls.company_b).create({
            'patient_id': cls.patient.id, 'company_id': cls.company_b.id, 'chief_complaint': 'Branch B'})
        cls.specialist.write({'company_ids': [(4, cls.company_b.id)]})
        cls.dentist_b = new_test_user(cls.env, login='so_dentist_b', groups='base.group_user,dental_base.group_dental_dentist',
                                      company_id=cls.company_b.id, company_ids=[cls.company_b.id])
        cls.request_b = cls.env['dental.second.opinion'].with_company(cls.company_b).create({
            'case_id': cls.case_b.id, 'specialist_id': cls.specialist_emp.id,
            'requesting_user_id': cls.dentist_b.id, 'clinical_question': 'Branch B question'})

    def test_branch_a_users_cannot_read_branch_b(self):
        self.assertEqual(self.request_b.company_id, self.company_b)
        for user in (self.manager, self.dentist):
            self.assertFalse(self.env['dental.second.opinion'].with_user(user).search([('id', '=', self.request_b.id)]), user.login)
            self.assertFalse(self.env['dental.second.opinion.log'].with_user(user).search([('request_id', '=', self.request_b.id)]), user.login)
            with self.assertRaises(AccessError):
                self.request_b.with_user(user).read(['name'])

    def test_cannot_link_foreign_branch_records(self):
        with self.assertRaises((UserError, ValidationError)):
            self.env['dental.second.opinion'].create({
                'case_id': self.case_b.id, 'company_id': self.company_a.id,
                'specialist_id': self.specialist_emp.id, 'clinical_question': 'x'})
        with self.assertRaises((UserError, ValidationError)):
            self.env['dental.second.opinion'].create({
                'case_id': self.case.id, 'examination_ids': [(6, 0, self.exam.ids)],
                'treatment_plan_id': self.env['dental.treatment.plan'].create({
                    'patient_id': self.patient.id, 'case_id': self.case_b.id, 'company_id': self.company_b.id}).id,
                'specialist_id': self.specialist_emp.id, 'clinical_question': 'x'})

    def test_branch_a_dentist_cannot_refer_branch_b_case(self):
        with self.assertRaises(AccessError):
            self._new_request(case_id=self.case_b.id)

    def test_specialist_needs_branch_access(self):
        specialist_a_only = new_test_user(self.env, login='so_spec_a_only', groups='base.group_user,dental_second_opinion.group_dental_specialist',
                                          company_id=self.company_a.id, company_ids=[self.company_a.id])
        emp = self.env['hr.employee'].create({'name': 'Dr. A Only', 'dental_role': 'dentist', 'user_id': specialist_a_only.id})
        with self.assertRaises(ValidationError):
            self.env['dental.second.opinion'].with_company(self.company_b).create({
                'case_id': self.case_b.id, 'specialist_id': emp.id, 'requesting_user_id': self.dentist_b.id,
                'clinical_question': 'x'})

    def test_specialist_works_within_selected_branch(self):
        self.request_b.with_user(self.dentist_b).with_context(allowed_company_ids=[self.company_b.id]).action_submit()
        as_specialist = self.request_b.with_user(self.specialist).with_context(allowed_company_ids=[self.company_b.id])
        as_specialist.action_start_review()
        self.case_b.with_user(self.specialist).with_context(allowed_company_ids=[self.company_b.id]).read(['chief_complaint'])
        # With only branch A selected, the branch B referral is out of reach
        self.assertFalse(self.env['dental.second.opinion'].with_user(self.specialist).with_context(
            allowed_company_ids=[self.company_a.id]).search([('id', '=', self.request_b.id)]))
