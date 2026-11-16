from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .test_consultation_workflow import ConsultationCommon


@tagged('post_install', '-at_install', 'dental_clinical_examination')
class TestClinicalExamination(ConsultationCommon):

    def _exam(self, visit=None):
        case = (visit or self._visit()).case_id
        action = case.with_user(self.dentist_user).action_open_examination()
        self.assertEqual(action['res_model'], 'dental.clinical.examination')
        return case, self.env['dental.clinical.examination'].browse(action['res_id'])

    def test_examination_linked_to_patient_case_and_visit(self):
        visit = self._visit()
        case, exam = self._exam(visit)
        self.assertEqual(exam.patient_id, self.patient)
        self.assertEqual(exam.case_id, case)
        self.assertEqual(exam.appointment_id, visit)
        self.assertEqual(exam.state, 'draft')
        self.assertEqual(case.current_examination_id, exam)
        # Opening it again continues the same examination
        again = case.with_user(self.dentist_user).action_open_examination()
        self.assertEqual(again['res_id'], exam.id)

    def test_structured_sections_saved_and_summarised(self):
        case, exam = self._exam()
        exam_as_dentist = exam.with_user(self.dentist_user)
        self.assertEqual(exam.sections_progress, 0.0)
        exam_as_dentist.write({
            'eo_facial_symmetry': 'symmetrical', 'eo_tmj_status': 'abnormal', 'eo_tmj_clicking': True, 'eo_mouth_opening': 42,
            'io_tongue': 'abnormal', 'io_lips': 'normal', 'oral_hygiene': 'fair', 'io_calculus': 'moderate',
            'dentition': 'permanent', 'molar_relation': 'class_1', 'overjet': 3, 'overbite': 2,
            'perio_status': 'periodontitis', 'perio_stage': '2', 'perio_grade': 'b', 'bpe_ur': '3', 'bpe_ll': 'star',
            'perio_chart_ids': [(0, 0, {'tooth_number': '36', 'pd_b': 6, 'pd_mb': 4, 'recession': 1, 'mobility': '1'})],
            'clinical_findings': 'Deep distal caries 36',
            'radiographs_taken': 'IOPA 36',
            'diagnosis_ids': [(0, 0, {'patient_id': self.patient.id, 'diagnosis_id': self.diagnosis.id, 'tooth_reference': '36'})],
            'clinical_impression': 'Localised active disease',
            'caries_risk': 'high', 'treatment_urgency': 'urgent',
            'referral_required': True, 'referral_to': 'Periodontist',
        })
        self.assertTrue(all([exam.extraoral_recorded, exam.intraoral_recorded, exam.dental_recorded, exam.periodontal_recorded,
                             exam.findings_recorded, exam.diagnosis_recorded, exam.assessment_recorded]))
        self.assertEqual(exam.sections_progress, 100.0)
        self.assertEqual(exam.bpe_max, '3*')
        self.assertEqual(exam.perio_max_depth, 6)
        self.assertEqual(exam.perio_chart_ids.clinical_attachment_loss, 7)
        diag = exam.diagnosis_ids
        self.assertEqual(diag.case_id, case, "Diagnosis recorded in the examination belongs to its case")
        self.assertIn(diag, case.diagnosis_ids)
        summary = exam.examination_summary
        for expected in ('Extraoral:', 'TMJ Abnormal (clicking)', 'Mouth opening 42 mm', 'Abnormal: Tongue', 'Class I',
                         'Periodontitis Stage II Grade B', 'BPE 3/-/-/-/-/*', 'Deepest pocket 6 mm at 36',
                         'Deep distal caries 36', 'K02.1 CW Caries (36)', 'Caries risk high', 'Refer to Periodontist'):
            self.assertIn(expected, summary)
        self.assertEqual(case.current_exam_summary, summary)
        self.assertTrue(case.current_exam_periodontal)

    def test_odontogram_findings_appear_in_examination(self):
        case, exam = self._exam()
        case.with_user(self.dentist_user).save_tooth_finding({'tooth_number': '46', 'condition': 'caries', 'surfaces': 'MO'})
        self.assertEqual(exam.tooth_finding_ids.tooth_number, '46')
        self.assertIn('46 Caries / Cavity (MO)', exam.examination_summary)
        self.assertEqual(exam.dmft_decayed, 1)
        self.assertEqual(exam.dmft_index, 1)
        # A later "sound" finding on the same tooth clears it from the DMFT count
        case.with_user(self.dentist_user).clear_tooth_finding('46')
        exam.invalidate_recordset(['dmft_decayed', 'dmft_index'])
        self.assertEqual(exam.dmft_index, 0)

    def test_timeline_shows_structured_examination(self):
        case, exam = self._exam()
        exam.write({'clinical_findings': 'CE timeline finding', 'io_lesion_present': True,
                    'io_lesion_description': 'White patch left lateral tongue',
                    'perio_chart_ids': [(0, 0, {'tooth_number': '16', 'pd_mb': 5})]})
        self.env.flush_all()
        row = self.env['dental.patient.history'].search([
            ('patient_id', '=', self.patient.id), ('record_type', '=', 'consultation'), ('reference', '=', exam.name)])
        self.assertEqual(len(row), 1)
        self.assertIn('CE timeline finding', row.description)
        self.assertIn('Lesion: White patch left lateral tongue', row.description)
        self.assertEqual(row.tooth, '16')
        self.assertEqual(row.status, 'in_progress')
        self.assertEqual(row.case_reference, case.name)

        case.action_complete_consultation()
        self.assertEqual(exam.state, 'done', "Completing the consultation signs off today's examination")
        self.assertTrue(exam.completed_date)
        self.env.flush_all()
        row.invalidate_recordset()
        self.assertEqual(row.status, 'completed')

    def test_complete_and_reopen_examination(self):
        case, exam = self._exam()
        exam.chief_complaint = False
        with self.assertRaises(ValidationError):
            exam.action_complete_examination()
        exam.chief_complaint = 'Sensitivity to cold'
        exam.with_user(self.dentist_user).action_complete_examination()
        self.assertEqual(exam.state, 'done')
        self.assertEqual(exam.completed_by_id, self.dentist_user)
        exam.action_reopen_examination()
        self.assertEqual(exam.state, 'draft')
        self.assertFalse(exam.completed_by_id)
        # A closed case keeps its examination signed off
        exam.action_complete_examination()
        case.action_complete_consultation()
        with self.assertRaises(ValidationError):
            exam.action_reopen_examination()

    def test_follow_up_visit_gets_its_own_examination(self):
        first = self._visit()
        case, exam_1 = self._exam(first)
        exam_1.clinical_findings = 'First visit'
        case.action_complete_consultation()
        self.assertEqual(exam_1.state, 'done')
        case.action_reopen_case()
        second = self._visit(case=case, hours=3)
        case.invalidate_recordset()
        _case, exam_2 = self._exam(second)
        self.assertNotEqual(exam_1, exam_2)
        self.assertEqual(exam_2.appointment_id, second)
        self.assertEqual(exam_2.state, 'draft')
        case.with_context(dental_current_visit_id=second.id).action_complete_consultation()
        self.assertEqual(exam_2.state, 'done')
        self.assertEqual(exam_1.clinical_findings, 'First visit')

    def test_previous_examinations_and_continue(self):
        first = self._visit()
        case, exam_1 = self._exam(first)
        exam_1.write({
            'molar_relation': 'class_2_div1', 'crowding': 'moderate', 'overjet': 6,
            'clinical_findings': 'Upper incisors proclined', 'blood_pressure': '120/80',
            'perio_chart_ids': [(0, 0, {'tooth_number': '11', 'pd_b': 3})],
        })
        case.action_complete_consultation()
        case.action_reopen_case()
        second = self._visit(case=case, hours=3)
        case = case.with_context(dental_current_visit_id=second.id)
        case.invalidate_recordset()
        # Starting the consultation opens an empty examination for the new visit
        today = case.current_examination_id
        self.assertEqual(today.appointment_id, second)
        self.assertFalse(today.sections_progress)
        self.assertEqual(case.previous_examination_ids, exam_1, "Earlier examination is listed on the Examination tab")

        action = exam_1.with_user(self.dentist_user).with_context(dental_case_id=case.id).action_continue_examination()
        exam_2 = self.env['dental.clinical.examination'].browse(action['res_id'])
        self.assertEqual(exam_2, today, "Today's empty examination is filled, not duplicated")
        self.assertNotEqual(exam_2, exam_1, "The earlier examination is kept as the record of its own visit")
        self.assertEqual(exam_2.appointment_id, second)
        self.assertEqual(exam_2.continued_from_id, exam_1)
        self.assertEqual(exam_2.state, 'draft')
        self.assertEqual((exam_2.molar_relation, exam_2.crowding, exam_2.overjet),
                         ('class_2_div1', 'moderate', 6))
        self.assertEqual(exam_2.clinical_findings, 'Upper incisors proclined')
        self.assertFalse(exam_2.blood_pressure, "Vitals are recorded fresh at every visit")
        self.assertEqual(exam_2.perio_chart_ids.tooth_number, '11')
        self.assertNotEqual(exam_2.perio_chart_ids, exam_1.perio_chart_ids)
        self.assertEqual(exam_1.state, 'done')
        self.assertEqual(len(exam_1.perio_chart_ids), 1)

        case.invalidate_recordset()
        self.assertEqual(case.current_examination_id, exam_2)
        self.assertEqual(case.previous_examination_ids, exam_1)
        # Today's examination now has findings: continuing again must not overwrite it
        with self.assertRaises(UserError):
            exam_1.with_context(dental_case_id=case.id).action_continue_examination()
        # The earlier examination opens on its own page
        self.assertEqual(exam_1.action_open_examination_form()['res_id'], exam_1.id)

    def test_continue_fills_empty_examination_of_today(self):
        first = self._visit()
        case, exam_1 = self._exam(first)
        exam_1.clinical_findings = 'Baseline'
        case.action_complete_consultation()
        case.action_reopen_case()
        second = self._visit(case=case, hours=3)
        case = case.with_context(dental_current_visit_id=second.id)
        case.invalidate_recordset()
        _case, empty = self._exam(second)
        action = exam_1.with_context(dental_case_id=case.id).action_continue_examination()
        self.assertEqual(action['res_id'], empty.id, "An empty examination of today is filled, not duplicated")
        self.assertEqual(empty.clinical_findings, 'Baseline')

    def test_measurement_validation(self):
        _case, exam = self._exam()
        with self.assertRaises(ValidationError):
            exam.eo_mouth_opening = 120
        with self.assertRaises(ValidationError):
            self.env['dental.examination.perio.line'].create({'examination_id': exam.id, 'tooth_number': '99'})
        with self.assertRaises(ValidationError):
            self.env['dental.examination.perio.line'].create({'examination_id': exam.id, 'tooth_number': '11', 'pd_b': 25})
        line = self.env['dental.examination.perio.line'].with_user(self.dentist_user).create(
            {'examination_id': exam.id, 'tooth_number': ' 11 ', 'pd_b': 3})
        self.assertEqual(line.tooth_number, '11')
        self.assertEqual(line.patient_id, self.patient)
        self.assertEqual(line.company_id, exam.company_id)
        line.with_user(self.dentist_user).unlink()

    def test_standard_diagnoses_loader(self):
        Diagnosis = self.env['dental.diagnosis'].with_context(active_test=False)
        Diagnosis._load_standard_diagnoses()
        pulpitis = Diagnosis.search([('code', '=', 'K04.02')])
        self.assertEqual(len(pulpitis), 1)
        self.assertEqual(pulpitis.category, 'pulpal')
        # Nothing is duplicated, and what the clinic archived stays archived
        pulpitis.active = False
        count = Diagnosis.search_count([])
        self.assertFalse(Diagnosis._load_standard_diagnoses(), "Running it again adds nothing")
        self.assertEqual(Diagnosis.search_count([]), count)
        self.assertFalse(pulpitis.active)
        # A clinic diagnosis with a standard name but its own code also blocks the standard entry
        pulpitis.unlink()
        own = Diagnosis.create({'name': 'Irreversible Pulpitis', 'code': 'IP-1'})
        self.assertFalse(Diagnosis._load_standard_diagnoses())
        self.assertFalse(Diagnosis.search([('code', '=', 'K04.02')]))
        # Searchable by code; shown with its code
        self.assertIn(own, Diagnosis.search([('display_name', 'ilike', 'IP-1')]))
        self.assertEqual(self.diagnosis.display_name, 'K02.1 CW Caries')

    def test_views_load(self):
        for model in ('dental.clinical.examination', 'dental.case', 'dental.diagnosis'):
            views = self.env[model].get_views([(False, 'form'), (False, 'list'), (False, 'search')])
            self.assertIn('form', views['views'])
        arch = self.env['dental.case'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('clinical_examination', arch)
