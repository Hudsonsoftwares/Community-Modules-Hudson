import base64
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.dental_speech.models import llm_engine, speech_engine

AUDIO = base64.b64encode(b'fake-webm-audio').decode()
SUMMARY = {
    'chief_complaint': 'Pain in lower left back tooth',
    'symptoms': '- Throbbing pain for 3 days\n- Worse with cold',
    'medical_history': 'Type 2 diabetes on metformin',
    'clinical_findings': 'Deep caries on 36, tender on percussion',
    'diagnosis': 'Irreversible pulpitis 36',
    'treatment_plan': 'Root canal treatment 36',
    'follow_up': 'Review in 1 week',
}


@tagged('post_install', '-at_install', 'dental_speech')
class TestConversationSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env['res.partner'].create({'name': 'Summary Patient', 'is_dental_patient': True})
        cls.dentist = new_test_user(cls.env, login='sum_dentist', groups='base.group_user,dental_base.group_dental_dentist')
        cls.other_dentist = new_test_user(cls.env, login='sum_other', groups='base.group_user,dental_base.group_dental_dentist')
        cls.receptionist = new_test_user(cls.env, login='sum_reception', groups='base.group_user,dental_base.group_dental_receptionist')
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Summary', 'dental_role': 'dentist', 'user_id': cls.dentist.id})
        start = datetime.now() + timedelta(days=2)
        cls.visit = cls.env['dental.appointment'].create({
            'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'in_consultation'})
        cls.case = cls.env['dental.case'].create({
            'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id, 'appointment_id': cls.visit.id,
            'chief_complaint': 'Toothache', 'medical_history_summary': 'Hypertension'})

    def _wizard(self, user=None, **vals):
        Wizard = self.env['dental.conversation.summary.wizard'].with_user(user or self.dentist)
        return Wizard.create({'case_id': self.case.id, **vals})

    def _transcribe(self, wizard):
        with patch.object(speech_engine, 'transcribe', return_value=('Doctor: what brings you in?', 42.0, 'en')):
            return wizard.action_transcribe_chunk(AUDIO, 'audio/webm;codecs=opus')

    def _review(self, wizard, summary=SUMMARY):
        wizard.transcript = 'Patient: my lower left tooth hurts. Doctor: this is irreversible pulpitis of 36.'
        with patch.object(llm_engine, 'summarize', return_value=dict(summary)) as mocked:
            wizard.action_generate_summary()
        return mocked

    def _exams(self):
        return self.env['dental.clinical.examination'].search([('case_id', '=', self.case.id)])

    # Consent and access

    def test_opened_from_case_form(self):
        action = self.case.with_user(self.dentist).action_open_conversation_summary()
        Wizard = self.env[action['res_model']].with_user(self.dentist).with_context(action['context'])
        wizard = Wizard.create({'patient_consent': True})   # readonly case_id comes from the context
        self.assertEqual(wizard.case_id, self.case)

    def test_opened_from_case_actions_menu(self):
        server_action = self.env.ref('dental_speech.action_server_dental_case_conversation_summary')
        action = server_action.with_user(self.dentist).with_context(
            active_model='dental.case', active_id=self.case.id, active_ids=self.case.ids).run()
        self.assertEqual(action['res_model'], 'dental.conversation.summary.wizard')

    def test_no_summary_on_closed_case(self):
        self.case.state = 'completed'
        with self.assertRaises(UserError):
            self.case.with_user(self.dentist).action_open_conversation_summary()

    def test_recording_requires_consent(self):
        wizard = self._wizard()
        with self.assertRaises(UserError):
            self._transcribe(wizard)

    def test_recording_with_consent_audits_without_content(self):
        wizard = self._wizard(patient_consent=True)
        result = self._transcribe(wizard)
        self._transcribe(wizard)
        self.assertEqual(result['text'], 'Doctor: what brings you in?')
        self.assertEqual(wizard.audio_seconds, 84.0)
        self.assertTrue(wizard.consent_date)
        started = self.case.message_ids.filtered(lambda m: 'recording started' in (m.body or ''))
        self.assertEqual(len(started), 1, 'consent is logged once per conversation')
        self.assertNotIn('brings you in', started.body)

    def test_receptionist_and_other_dentist_refused(self):
        for user in (self.receptionist, self.other_dentist):
            with self.assertRaises(AccessError, msg=user.login):
                self._wizard(user=user)

    def test_closed_case_refused(self):
        self.case.state = 'completed'
        with self.assertRaises(UserError):
            self._wizard()

    # Summary and approval

    def test_summary_needs_review_and_diagnosis_confirmation(self):
        wizard = self._wizard()
        with self.assertRaises(UserError):
            wizard.action_approve()            # nothing generated yet
        mocked = self._review(wizard)
        self.assertEqual(wizard.state, 'review')
        self.assertFalse(wizard.diagnosis_confirmed)
        self.assertNotIn('Summary Patient', mocked.call_args.args[0], 'only the transcript goes to the model')
        with self.assertRaises(ValidationError):
            wizard.action_approve()
        self.assertFalse(self._exams(), 'nothing is saved before approval')

    def test_approve_saves_to_existing_fields_without_overwriting(self):
        exam = self.env['dental.clinical.examination'].browse(self.case.action_new_visit_consultation()['res_id'])
        exam.clinical_findings = 'Mobility grade I on 31'
        wizard = self._wizard(patient_consent=True)
        self._transcribe(wizard)
        self._review(wizard)
        wizard.diagnosis = 'Irreversible pulpitis 36 (edited by doctor)'
        wizard.diagnosis_confirmed = True
        wizard.action_approve()

        self.assertEqual(self._exams(), exam, "today's consultation record is reused, not duplicated")
        self.assertIn('Toothache', exam.chief_complaint)
        self.assertIn('Pain in lower left back tooth', exam.chief_complaint)
        self.assertEqual(exam.presenting_complaint, SUMMARY['symptoms'])
        self.assertTrue(exam.clinical_findings.startswith('Mobility grade I on 31'), 'existing findings are kept')
        self.assertIn('Deep caries on 36', exam.clinical_findings)
        self.assertEqual(exam.conversation_diagnosis, 'Irreversible pulpitis 36 (edited by doctor)')
        self.assertEqual(exam.conversation_treatment_plan, SUMMARY['treatment_plan'])
        self.assertEqual(exam.conversation_follow_up, SUMMARY['follow_up'])
        self.assertEqual(exam.conversation_approved_by_id, self.dentist)
        self.assertEqual(exam.conversation_consent_by_id, self.dentist)
        self.assertFalse(exam.conversation_transcript, 'transcripts are not kept unless enabled')
        self.assertEqual(self.case.medical_history_summary, 'Hypertension\n\nType 2 diabetes on metformin')
        self.assertFalse(wizard.exists(), 'the draft is deleted after approval')
        approval = self.case.message_ids[:1]
        self.assertIn('approved', approval.body)
        self.assertNotIn('pulpitis', approval.body, 'no clinical content in the chatter')

    def test_approving_twice_does_not_duplicate(self):
        for _attempt in range(2):
            wizard = self._wizard()
            self._review(wizard, {**SUMMARY, 'diagnosis': ''})
            wizard.action_approve()
        exam = self._exams()
        self.assertEqual(len(exam), 1)
        self.assertEqual(exam.presenting_complaint, SUMMARY['symptoms'])
        self.assertEqual(self.case.medical_history_summary.count('Type 2 diabetes'), 1)

    def test_keep_transcript_setting(self):
        self.env['ir.config_parameter'].sudo().set_bool('dental_speech.keep_transcript', True)
        wizard = self._wizard()
        self._review(wizard, {**SUMMARY, 'diagnosis': ''})
        wizard.action_approve()
        self.assertIn('irreversible pulpitis', self._exams().conversation_transcript)

    def test_discard_saves_nothing(self):
        wizard = self._wizard(patient_consent=True)
        self._transcribe(wizard)
        wizard.action_discard()
        self.assertFalse(wizard.exists())
        self.assertFalse(self._exams())
        self.assertIn('discarded', self.case.message_ids[:1].body)

    def test_model_unavailable_gives_clear_error(self):
        wizard = self._wizard(transcript='Patient: toothache.')
        with patch.object(llm_engine, 'summarize', side_effect=llm_engine.LLMUnavailable('not running')):
            with self.assertRaises(UserError):
                wizard.action_generate_summary()
        self.assertEqual(wizard.state, 'record')


@tagged('post_install', '-at_install', 'dental_speech')
class TestLLMEngine(TransactionCase):

    def test_only_local_or_private_addresses(self):
        self.assertEqual(llm_engine.check_endpoint('http://127.0.0.1:11434/'), 'http://127.0.0.1:11434')
        self.assertTrue(llm_engine.check_endpoint('http://192.168.1.20:11434'))
        for endpoint in ('http://8.8.8.8:11434', 'ftp://127.0.0.1', 'http://0.0.0.0:11434', ''):
            with self.assertRaises(llm_engine.LLMUnavailable, msg=endpoint):
                llm_engine.check_endpoint(endpoint)

    def test_placeholders_become_empty(self):
        self.assertEqual(llm_engine._clean('Not mentioned.'), '')
        self.assertEqual(llm_engine._clean(['a', ' b ']), '- a\n- b')

    def test_overlong_transcript_refused(self):
        with self.assertRaises(llm_engine.LLMUnavailable):
            llm_engine.summarize('x' * (llm_engine.MAX_TRANSCRIPT_CHARS + 1))
