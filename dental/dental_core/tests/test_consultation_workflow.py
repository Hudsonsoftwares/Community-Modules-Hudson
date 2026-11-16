from datetime import datetime, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


class ConsultationCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Employee = cls.env['hr.employee']
        # Unrelated add-on hooks (DMS folders) must not interfere with these clinical tests
        if hasattr(type(Employee), '_setup_dms_folder_and_permissions'):
            cls.startClassPatcher(__import__('unittest.mock').mock.patch.object(
                type(Employee), '_setup_dms_folder_and_permissions', lambda self: None))
        cls.dentist_user = new_test_user(cls.env, login='cw_dentist', groups='base.group_user,dental_base.group_dental_dentist',
                                         company_id=cls.company.id, company_ids=[cls.company.id])
        cls.doctor = Employee.create({'name': 'Dr. Workflow CW', 'dental_role': 'dentist', 'user_id': cls.dentist_user.id,
                                      'company_id': cls.company.id})
        cls.patient = cls.env['res.partner'].create({'name': 'CW Patient', 'is_dental_patient': True, 'phone': '9000012345'})
        cls.treatment = cls.env['product.template'].create({
            'name': 'CW Composite Filling', 'is_dental_treatment': True, 'list_price': 100.0, 'number_of_visits': 1, 'type': 'service'})
        cls.treatment_2 = cls.env['product.template'].create({
            'name': 'CW Root Canal', 'is_dental_treatment': True, 'list_price': 300.0, 'number_of_visits': 2, 'type': 'service'})
        cls.diagnosis = cls.env['dental.diagnosis'].create({'name': 'CW Caries', 'code': 'K02.1'})

    def _visit(self, case=None, hours=1):
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours)
        vals = {'patient_id': self.patient.id, 'doctor_id': self.doctor.id, 'branch_id': self.company.id,
                'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed', 'reason': 'Pain'}
        if case:
            vals['case_id'] = case.id
        appt = self.env['dental.appointment'].create(vals)
        appt.action_check_in()
        appt.action_start_consultation()
        return appt


@tagged('post_install', '-at_install', 'dental_consultation_workflow')
class TestAllergyAlerts(ConsultationCommon):

    def test_allergy_status_derived_and_validated(self):
        self.assertEqual(self.patient.allergy_status, 'unknown', "An empty allergy field is 'not recorded', not 'none'")
        self.patient.allergies = '<p>Penicillin</p>'
        self.assertEqual(self.patient.allergy_status, 'known')
        self.assertTrue(self.patient.allergy_verified_date)
        with self.assertRaises(ValidationError):
            self.patient.allergy_status = 'none'
        self.patient.write({'allergies': '<p>NKDA</p>'})
        self.assertEqual(self.patient.allergy_status, 'none')
        with self.assertRaises(ValidationError):
            self.patient.write({'allergy_status': 'known', 'allergies': False})
        self.patient.write({'allergies': False})
        self.assertEqual(self.patient.allergy_status, 'unknown')
        self.assertFalse(self.patient.allergy_verified_by)

    def test_case_alert_is_live(self):
        case = self._visit().case_id
        self.assertEqual(case.patient_allergy_status, 'unknown')
        # Allergy recorded on the patient file after the case was opened
        self.patient.write({'allergies': '<p>Latex</p>'})
        case.invalidate_recordset()
        self.assertEqual(case.patient_allergy_status, 'known')
        self.assertIn('Latex', case.patient_allergies)
        self.assertFalse(case.allergies, "The case snapshot is kept as it was when the case opened")
        self.patient.write({'clinical_alerts': '<p>On anticoagulants</p>'})
        case.invalidate_recordset()
        self.assertTrue(case.has_clinical_alert)


@tagged('post_install', '-at_install', 'dental_consultation_workflow')
class TestExaminationChain(ConsultationCommon):

    def test_inline_exam_is_per_visit_and_keeps_history(self):
        first = self._visit()
        case = first.case_id
        case.write({'exam_clinical_findings': 'Deep caries 36', 'exam_pulse_rate': 72})
        exam_1 = case.current_examination_id
        self.assertEqual(case.exam_clinical_findings, 'Deep caries 36', "Inline field reads back the saved value")
        self.assertEqual(exam_1.appointment_id, first)
        self.assertEqual(exam_1.clinical_findings, 'Deep caries 36')
        case.action_complete_consultation()

        # Follow-up visit of the same case
        case.action_reopen_case()
        second = self._visit(case=case, hours=3)
        self.assertEqual(second.case_id, case)
        case.invalidate_recordset()
        self.assertNotEqual(case.current_examination_id, exam_1, "A new visit must not reuse the previous visit's examination")
        self.assertFalse(case.exam_clinical_findings)
        case.write({'exam_clinical_findings': 'Restoration intact'})
        exam_2 = case.current_examination_id
        self.assertNotEqual(exam_1, exam_2)
        self.assertEqual(exam_2.appointment_id, second)
        self.assertEqual(exam_1.clinical_findings, 'Deep caries 36', "History of the first visit is untouched")

    def test_finding_and_diagnosis_link_to_visit_exam(self):
        case = self._visit().case_id
        res = case.with_user(self.dentist_user).save_tooth_finding({
            'tooth_number': '36', 'condition': 'caries', 'surfaces': 'O', 'diagnosis_id': self.diagnosis.id})
        finding = self.env['dental.tooth.finding'].browse(res['finding_id'])
        exam = case.current_examination_id
        self.assertTrue(exam)
        self.assertEqual(finding.examination_id, exam)
        diag = case.diagnosis_ids.filtered(lambda d: d.tooth_reference == '36')
        self.assertEqual(len(diag), 1)
        self.assertEqual(diag.examination_id, exam)
        # Same diagnosis again from the chart: no duplicate entry
        case.with_user(self.dentist_user).save_tooth_finding({
            'tooth_number': '36', 'condition': 'caries', 'surfaces': 'O', 'diagnosis_id': self.diagnosis.id})
        self.assertEqual(len(case.diagnosis_ids.filtered(lambda d: d.tooth_reference == '36')), 1)
        # Diagnosis typed in the Clinical Chart list shows on the odontogram
        case.write({'diagnosis_ids': [(0, 0, {'patient_id': self.patient.id, 'diagnosis_id': self.diagnosis.id, 'tooth_reference': '46'})]})
        new_diag = case.diagnosis_ids.filtered(lambda d: d.tooth_reference == '46')
        self.assertEqual(new_diag.examination_id, exam)
        chart = case.get_odontogram_data()
        self.assertIn(new_diag.id, [d['id'] for d in chart['teeth']['46']['diagnoses']])

    def test_diagnosis_carries_over_to_next_case(self):
        first_case = self._visit().case_id
        first_case.with_user(self.dentist_user).save_tooth_finding({
            'tooth_number': '36', 'condition': 'caries', 'surfaces': 'O', 'diagnosis_id': self.diagnosis.id})
        diag = first_case.diagnosis_ids.filtered(lambda d: d.tooth_reference == '36')
        self.assertEqual(diag.status, 'confirmed')
        first_case.action_complete_consultation()

        # The patient comes back for an unrelated problem: a new case
        appt = self._visit(hours=4)
        if appt.case_id == first_case:
            appt.action_new_clinical_case()
        second_case = appt.case_id
        self.assertNotEqual(second_case, first_case)
        self.assertIn(diag, second_case.patient_diagnosis_ids, "Open diagnoses of earlier visits are listed")
        chart = second_case.get_odontogram_data()
        self.assertEqual(chart['teeth']['36']['condition'], 'caries', "Tooth markings carry over")
        self.assertIn(diag.id, [d['id'] for d in chart['teeth']['36']['diagnoses']])

        # Diagnosing the same tooth again on the later visit does not duplicate the open diagnosis
        second_case.with_user(self.dentist_user).save_tooth_finding({
            'tooth_number': '36', 'condition': 'caries', 'surfaces': 'MO', 'diagnosis_id': self.diagnosis.id})
        self.assertEqual(self.env['dental.patient.diagnosis'].search_count([
            ('patient_id', '=', self.patient.id), ('tooth_reference', '=', '36')]), 1)

        # Tooth charted healthy again: its diagnosis is resolved, still shown in this case's list
        second_case.with_user(self.dentist_user).clear_tooth_finding('36')
        self.assertEqual(diag.status, 'resolved')
        second_case.invalidate_recordset(['patient_diagnosis_ids'])
        self.assertNotIn(diag, second_case.patient_diagnosis_ids,
                         "Resolved in another case: no longer listed as open")
        diag.action_reopen()
        self.assertEqual(diag.status, 'confirmed')

    def test_invalid_tooth_rejected(self):
        case = self._visit().case_id
        with self.assertRaises(ValidationError):
            self.env['dental.patient.diagnosis'].create({
                'patient_id': self.patient.id, 'case_id': case.id, 'diagnosis_id': self.diagnosis.id, 'tooth_reference': '99'})

    def test_closed_case_exam_not_editable(self):
        case = self._visit().case_id
        case.action_complete_consultation()
        self.assertEqual(case.state, 'completed')
        with self.assertRaises(UserError):
            case.write({'exam_clinical_findings': 'late edit'})


@tagged('post_install', '-at_install', 'dental_consultation_workflow')
class TestTreatmentWorkflow(ConsultationCommon):

    def _plan(self, case):
        return self.env['dental.treatment.plan'].create({
            'patient_id': self.patient.id, 'case_id': case.id, 'doctor_id': self.doctor.id,
            'line_ids': [(0, 0, {'treatment_id': self.treatment.id, 'tooth_reference': '36', 'unit_price': 100, 'phase': '2', 'priority': '2'}),
                         (0, 0, {'treatment_id': self.treatment_2.id, 'tooth_reference': '46', 'unit_price': 300, 'number_of_visits': 2, 'phase': '3'})],
        })

    def test_acceptance_partial_and_decline(self):
        case = self._visit().case_id
        plan = self._plan(case)
        filling, rct = plan.line_ids.sorted('phase')
        plan.action_propose()
        self.assertEqual(plan.state, 'proposed')
        rct.action_decline_line()
        plan.action_accept()
        self.assertEqual(plan.state, 'approved')
        self.assertEqual(filling.acceptance, 'accepted')
        self.assertEqual(rct.acceptance, 'declined')
        self.assertTrue(plan.accepted_date)
        self.assertEqual(plan.accepted_amount, filling.estimated_amount)
        with self.assertRaises(UserError):
            rct.action_mark_visit_done()
        filling.action_mark_visit_done()
        self.assertEqual(filling.state, 'completed')
        self.assertEqual(plan.state, 'completed', "Declined treatment does not keep the plan open")
        self.assertEqual(plan.progress, 100.0)

    def test_partial_progress(self):
        case = self._visit().case_id
        plan = self._plan(case)
        plan.action_accept()
        rct = plan.line_ids.filtered(lambda l: l.treatment_id == self.treatment_2)
        rct.action_mark_visit_done()
        self.assertEqual(rct.state, 'in_progress')
        self.assertEqual(rct.completed_visits, 1)
        # 1 of 3 planned visits done (filling 1 + RCT 2)
        self.assertAlmostEqual(plan.progress, 33.3, places=1)
        self.assertEqual(plan.state, 'in_progress')

    def test_performed_differs_from_plan_needs_reason(self):
        case = self._visit().case_id
        plan = self._plan(case)
        line = plan.line_ids.filtered(lambda l: l.treatment_id == self.treatment)
        session = self.env['dental.treatment.session'].create({'plan_line_id': line.id})
        self.assertEqual(session.planned_treatment_id, self.treatment)
        session.performed_tooth_reference = '37'
        self.assertTrue(session.deviates_from_plan)
        with self.assertRaises(ValidationError):
            session.action_complete()
        session.deviation_reason = '36 was already restored; 37 had the active lesion'
        session.action_complete()
        self.assertEqual(session.state, 'completed')
        self.assertEqual(line.acceptance, 'accepted', "Performing pending treatment records it as accepted")

    def test_decline_whole_plan_blocked_after_work(self):
        case = self._visit().case_id
        plan = self._plan(case)
        plan.line_ids[0].action_mark_visit_done()
        with self.assertRaises(UserError):
            plan.action_decline()


@tagged('post_install', '-at_install', 'dental_consultation_workflow')
class TestFollowUpBooking(ConsultationCommon):

    def _follow_up(self, case):
        return self.env['dental.follow.up'].create({
            'patient_id': self.patient.id, 'case_id': case.id, 'doctor_id': self.doctor.id,
            'date': datetime.now().date() + timedelta(days=7), 'reason': 'Review'})

    def _book(self, follow_up):
        action = follow_up.action_book_followup_appointment()
        self.assertEqual(follow_up.state, 'pending', "Opening the booking form must not change the follow-up")
        ctx = {k[len('default_'):]: v for k, v in action['context'].items() if k.startswith('default_')}
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=7)
        vals = dict(ctx, date_start=start, date_end=start + timedelta(minutes=30), branch_id=self.company.id, state='confirmed')
        return self.env['dental.appointment'].with_context(action['context']).create(vals)

    def test_booked_only_after_appointment_created(self):
        case = self._visit().case_id
        follow_up = self._follow_up(case)
        appt = self._book(follow_up)
        self.assertEqual(follow_up.state, 'booked')
        self.assertEqual(follow_up.booked_appointment_id, appt)
        self.assertEqual(appt.case_id, case, "The booked visit continues the same case")
        with self.assertRaises(UserError):
            follow_up.action_book_followup_appointment()

    def test_cancelled_booking_reopens_follow_up(self):
        follow_up = self._follow_up(self._visit().case_id)
        appt = self._book(follow_up)
        appt.action_cancel()
        self.assertEqual(follow_up.state, 'pending')
        self.assertFalse(follow_up.booked_appointment_id)

    def test_attended_booking_completes_follow_up(self):
        follow_up = self._follow_up(self._visit().case_id)
        appt = self._book(follow_up)
        appt.write({'state': 'completed'})
        self.assertEqual(follow_up.state, 'done')

    def test_failed_creation_leaves_follow_up_pending(self):
        follow_up = self._follow_up(self._visit().case_id)
        action = follow_up.action_book_followup_appointment()
        other = self.env['res.partner'].create({'name': 'CW Other Patient', 'is_dental_patient': True, 'phone': '9000012399'})
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=8)
        Appt = self.env['dental.appointment'].with_context(action['context'])
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                # Booked for the wrong patient: rejected, so no appointment and no booking
                Appt.create({'patient_id': other.id, 'doctor_id': self.doctor.id, 'branch_id': self.company.id,
                             'date_start': start, 'date_end': start + timedelta(minutes=30)})
        self.assertEqual(follow_up.state, 'pending')
        self.assertFalse(self.env['dental.appointment'].search_count([('patient_id', '=', other.id)]))


@tagged('post_install', '-at_install', 'dental_consultation_workflow')
class TestClinicalTimeline(ConsultationCommon):

    def test_timeline_contains_visits_notes_and_is_chronological(self):
        case = self._visit().case_id
        case.write({'clinical_notes': 'CW timeline note', 'exam_clinical_findings': 'CW finding'})
        self.env.flush_all()
        rows = self.env['dental.patient.history'].search([('patient_id', '=', self.patient.id)])
        types = set(rows.mapped('record_type'))
        self.assertTrue({'visit', 'case', 'consultation'} <= types, types)
        case_row = rows.filtered(lambda r: r.record_type == 'case')
        self.assertIn('CW timeline note', case_row.description)
        times = [r.event_time for r in rows if r.event_time]
        self.assertEqual(times, sorted(times, reverse=True), "Most recent first")
        action = case.action_open_patient_timeline()
        self.assertEqual(action['domain'], [('patient_id', '=', self.patient.id)])
