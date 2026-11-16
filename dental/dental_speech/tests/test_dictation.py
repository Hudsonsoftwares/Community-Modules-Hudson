import base64
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.dental_speech.models import speech_engine

AUDIO = base64.b64encode(b'fake-webm-audio').decode()


@tagged('post_install', '-at_install', 'dental_speech')
class TestDentalDictation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env['res.partner'].create({'name': 'Dictation Patient', 'is_dental_patient': True})
        cls.dentist = new_test_user(cls.env, login='stt_dentist', groups='base.group_user,dental_base.group_dental_dentist')
        cls.other_dentist = new_test_user(cls.env, login='stt_other', groups='base.group_user,dental_base.group_dental_dentist')
        cls.receptionist = new_test_user(cls.env, login='stt_reception', groups='base.group_user,dental_base.group_dental_receptionist')
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Dictate', 'dental_role': 'dentist', 'user_id': cls.dentist.id})
        start = datetime.now() + timedelta(days=2)
        appt = cls.env['dental.appointment'].create({
            'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'in_consultation'})
        cls.case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id,
                                                  'appointment_id': appt.id, 'chief_complaint': 'Pain'})

    def _transcribe(self, user, case=None, **kwargs):
        target = (case if case is not None else self.case).with_user(user)
        with patch.object(speech_engine, 'transcribe', return_value=('Caries on 36, plan RCT.', 4.2, 'en')) as mocked:
            return target.dental_transcribe_audio(kwargs.get('audio', AUDIO), kwargs.get('mime', 'audio/webm;codecs=opus')), mocked

    def test_treating_dentist_gets_text_and_audit_without_content(self):
        result, mocked = self._transcribe(self.dentist)
        self.assertEqual(result['text'], 'Caries on 36, plan RCT.')
        self.assertEqual(mocked.call_args.args[0], b'fake-webm-audio', 'audio is passed in memory, decoded')
        last = self.case.message_ids[:1]
        self.assertIn('Voice dictation transcribed', last.body)
        self.assertNotIn('Caries', last.body, 'transcribed content must not be written to the chatter')

    def test_unsaved_case_allowed_for_dentist(self):
        result, _mock = self._transcribe(self.dentist, case=self.env['dental.case'])
        self.assertTrue(result['text'])

    def test_receptionist_refused(self):
        with self.assertRaises(AccessError):
            self._transcribe(self.receptionist)

    def test_other_dentist_cannot_dictate_into_foreign_case(self):
        with self.assertRaises(AccessError):
            self._transcribe(self.other_dentist)

    def test_closed_case_refused(self):
        self.case.state = 'completed'
        with self.assertRaises(UserError):
            self._transcribe(self.dentist)

    def test_invalid_payloads_refused(self):
        for kwargs in ({'mime': 'application/x-msdownload'}, {'audio': '!!not-base64!!'}, {'audio': ''}):
            with self.assertRaises(UserError, msg=kwargs):
                self._transcribe(self.dentist, **kwargs)

    def test_oversized_audio_refused_before_decoding(self):
        with patch('odoo.addons.dental_speech.models.dental_case.MAX_AUDIO_BYTES', 10):
            with self.assertRaises(UserError):
                self._transcribe(self.dentist, audio=base64.b64encode(b'x' * 64).decode())

    def test_language_and_translate_settings_reach_engine(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('dental_speech.language', 'ml')
        params.set_bool('dental_speech.translate', True)
        result, mocked = self._transcribe(self.dentist)
        self.assertEqual(mocked.call_args.kwargs['language'], 'ml')
        self.assertTrue(mocked.call_args.kwargs['translate'])
        self.assertEqual(result['language_name'], 'English')
        self.assertTrue(result['translated'])

    def test_language_setting_is_normalized(self):
        normalize = speech_engine.normalize_language
        self.assertEqual(normalize('EN'), 'en')
        self.assertEqual(normalize(' Malayalam '), 'ml')
        self.assertIsNone(normalize(''))
        self.assertIsNone(normalize('klingon'), 'unknown values fall back to automatic detection')

    def test_engine_missing_gives_clear_error(self):
        with patch.object(speech_engine, 'transcribe', side_effect=speech_engine.SpeechEngineUnavailable('not installed')):
            with self.assertRaises(UserError):
                self.case.with_user(self.dentist).dental_transcribe_audio(AUDIO, 'audio/webm')
