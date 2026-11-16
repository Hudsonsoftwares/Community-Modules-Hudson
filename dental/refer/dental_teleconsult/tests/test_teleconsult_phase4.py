# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from .common import TeleconsultCommonMixin


@tagged('post_install', '-at_install', 'dental_teleconsult')
class TestTeleconsultPhase4(TeleconsultCommonMixin, TransactionCase):
    """Consent record, visit summary PDF, colleague invitation, recordings and reporting values."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_teleconsult_clinic()
        cls.specialist_user = new_test_user(
            cls.env, login='tc_specialist', groups='base.group_user,dental_base.group_dental_dentist',
            company_id=cls.company.id, company_ids=[cls.company.id])

    def _ready(self, appt):
        appt.sudo().teleconsult_payment_waived = True
        guest = self.env['mail.guest'].create({'name': self.patient.name})
        appt._teleconsult_patient_ready(guest=guest, consent_info={
            'ip': '203.0.113.7', 'user_agent': 'Mozilla/5.0 TC-Test'})
        return guest

    def test_consent_record(self):
        appt = self._online_appointment()
        self._ready(appt)
        self.assertEqual(appt.teleconsult_consent_ip, '203.0.113.7')
        self.assertEqual(appt.teleconsult_consent_user_agent, 'Mozilla/5.0 TC-Test')
        self.assertEqual(appt.teleconsult_consent_method, 'identity')
        record = appt.teleconsult_consent_attachment_id
        self.assertTrue(record, "A consent record is generated when the patient accepts the terms")
        self.assertEqual((record.res_model, record.res_id), ('dental.appointment', appt.id))
        self.assertIn('Consent', record.name)
        # Reconnecting does not overwrite the original evidence
        appt._teleconsult_patient_ready(guest=appt.teleconsult_guest_id, consent_info={'ip': '198.51.100.1'})
        self.assertEqual(appt.teleconsult_consent_ip, '203.0.113.7')
        self.assertEqual(appt.teleconsult_consent_attachment_id, record)
        html = self.env['ir.actions.report']._render_qweb_html(
            'dental_teleconsult.report_teleconsult_consent', appt.ids)[0].decode()
        self.assertIn('203.0.113.7', html)
        self.assertIn('cannot physically', html)

    def test_summary_pdf_attached_to_email(self):
        appt = self._online_appointment()
        self._run_session(appt)
        appt.write({'teleconsult_outcome': 'advice', 'teleconsult_summary': '<p>Warm salt water rinses.</p>'})
        appt.with_user(self.dentist_user).action_teleconsult_send_summary()
        summary = appt.teleconsult_summary_attachment_id
        self.assertTrue(summary)
        mail = self.env['mail.mail'].sudo().search([('model', '=', 'dental.appointment'), ('res_id', '=', appt.id),
                                                    ('subject', 'ilike', 'visit summary')], limit=1)
        self.assertIn(summary, mail.attachment_ids)
        html = self.env['ir.actions.report']._render_qweb_html(
            'dental_teleconsult.report_teleconsult_summary', appt.ids)[0].decode()
        self.assertIn('Warm salt water rinses', html)

    def test_invite_colleague(self):
        appt = self._online_appointment()
        self._ready(appt)
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        with self.assertRaises(AccessError):
            appt.with_user(self.receptionist_user)._teleconsult_invite_colleagues(self.specialist_user)

        wizard = self.env['dental.teleconsult.invite'].with_user(self.dentist_user).create({
            'appointment_id': appt.id, 'user_ids': [(6, 0, self.specialist_user.ids)], 'note': 'Tooth 36'})
        wizard.action_invite()
        channel = appt.sudo().teleconsult_channel_id
        self.assertIn(self.specialist_user.partner_id, channel.channel_member_ids.partner_id)
        self.assertEqual(appt.teleconsult_colleague_ids, self.specialist_user)

        appt.with_user(self.dentist_user).action_teleconsult_end()
        members = channel.channel_member_ids.partner_id
        self.assertNotIn(self.specialist_user.partner_id, members, "Colleagues leave the room at the end")
        self.assertIn(self.dentist_user.partner_id, members, "The treating dentist keeps the room")
        with self.assertRaises(UserError):
            appt.with_user(self.dentist_user)._teleconsult_invite_colleagues(self.specialist_user)

    def test_transcript_file(self):
        appt = self._online_appointment()
        guest = self._ready(appt)
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        channel = appt.sudo().teleconsult_channel_id
        channel.with_user(self.dentist_user).message_post(
            body='Please show the upper left side', message_type='comment', subtype_xmlid='mail.mt_comment')
        appt.with_user(self.dentist_user).action_teleconsult_end()
        transcript = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'dental.appointment'), ('res_id', '=', appt.id),
            ('description', '=', 'dental_teleconsult_transcript')])
        self.assertEqual(len(transcript), 1)
        self.assertIn(b'Please show the upper left side', bytes(transcript.raw))
        self.assertTrue(guest)

    def test_recordings_and_report_values(self):
        appt = self._online_appointment()
        self.assertEqual(appt.teleconsult_recording_count, 0)
        with self.assertRaises(UserError):
            appt.with_user(self.dentist_user).action_teleconsult_recordings()

        paid = self._online_appointment(start_in=timedelta(minutes=8), doctor_id=self.other_doctor.id)
        self.assertEqual(paid.teleconsult_fee_amount, 50.0, "Posted fee invoice is reported")
        self._ready(appt)
        appt.sudo().teleconsult_waiting_since = appt.teleconsult_waiting_since - timedelta(minutes=6)
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        appt.sudo().teleconsult_started_at = appt.teleconsult_started_at - timedelta(minutes=20)
        appt.with_user(self.dentist_user).action_teleconsult_end()
        self.assertAlmostEqual(appt.teleconsult_call_minutes, 20, delta=1)
        self.assertAlmostEqual(appt.teleconsult_wait_minutes, 0, delta=7)
        groups = self.env['dental.appointment'].with_user(self.manager_user).formatted_read_group(
            [('consultation_mode', '=', 'online'), ('id', 'in', (appt | paid).ids)],
            [], ['teleconsult_call_minutes:avg', 'teleconsult_fee_amount:sum'])
        self.assertTrue(groups)

    def test_staff_booking_services_flag_online(self):
        type_online = self.env['dental.appointment.type'].create({'name': 'TC Online OK', 'allow_online': True})
        type_clinic = self.env['dental.appointment.type'].create({'name': 'TC Clinic Only', 'allow_online': False})
        services = {s['appointment_type_id']: s['allow_online'] for s in self.env['dental.appointment'].with_user(
            self.receptionist_user).get_bookable_services(branch_id=self.company.id)['services']
            if s.get('appointment_type_id')}
        self.assertTrue(services[type_online.id])
        self.assertFalse(services[type_clinic.id])
        self.company.dental_teleconsult_enabled = False
        result = self.env['dental.appointment'].get_bookable_services(branch_id=self.company.id)
        self.assertFalse(result['teleconsult_enabled'])
        self.assertFalse(any(s['allow_online'] for s in result['services']))
