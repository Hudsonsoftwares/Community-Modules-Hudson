# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from .common import TeleconsultCommonMixin


@tagged('post_install', '-at_install', 'dental_teleconsult')
class TestTeleconsult(TeleconsultCommonMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_teleconsult_clinic()

    def _guest(self):
        return self.env['mail.guest'].create({'name': self.patient.name})

    # ---------------------------------------------------------------
    # Confirmation: room, link, payment request, invitation
    # ---------------------------------------------------------------
    def test_confirm_creates_private_room_link_and_payment_request(self):
        appt = self._online_appointment()
        self.assertEqual(appt.state, 'confirmed')
        self.assertEqual(appt.teleconsult_state, 'scheduled')
        self.assertGreaterEqual(len(appt.teleconsult_access_token), 32)
        self.assertIn('/dental/teleconsult/%s' % appt.teleconsult_access_token, appt.teleconsult_join_url)

        channel = appt.teleconsult_channel_id
        self.assertEqual(channel.channel_type, 'group')
        self.assertEqual(channel.dental_channel_type, 'teleconsult')
        self.assertEqual(channel.default_display_mode, 'video_full_screen')
        self.assertTrue(channel.is_confidential_phi)
        self.assertEqual(channel.dental_appointment_id, appt)
        members = channel.channel_member_ids.partner_id
        self.assertIn(self.dentist_user.partner_id, members)
        self.assertNotIn(self.receptionist_user.partner_id, members,
                         "The front desk confirming the visit must not join the PHI video room")

        invoice = appt.teleconsult_invoice_id
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_untaxed, 50.0, "The doctor's consultation fee is billed")
        self.assertEqual(invoice.invoice_line_ids.dental_appointment_id, appt)
        self.assertEqual(appt.teleconsult_payment_state, 'due')
        self.assertTrue(appt.teleconsult_payment_url)

        mails = self.env['mail.mail'].search([('model', '=', 'dental.appointment'), ('res_id', '=', appt.id)])
        subjects = mails.mapped('subject')
        self.assertTrue(any('online video consultation' in s for s in subjects), subjects)
        self.assertFalse(any(s.startswith('Appointment Confirmation') for s in subjects),
                         "Online visits get the video invitation instead of the in-clinic confirmation")
        self.assertIn(appt.teleconsult_join_url, mails.filtered(
            lambda m: 'online video consultation' in m.subject)[0].body_html)

    def test_in_clinic_visit_untouched(self):
        appt = self._online_appointment(consultation_mode='in_clinic')
        self.assertFalse(appt.teleconsult_state)
        self.assertFalse(appt.teleconsult_channel_id)
        self.assertFalse(appt.teleconsult_access_token)
        self.assertFalse(appt.teleconsult_payment_state)

    def test_switch_confirmed_visit_to_online_sends_invitation(self):
        appt = self._online_appointment(consultation_mode='in_clinic')
        appt.with_user(self.receptionist_user).consultation_mode = 'online'
        self.assertEqual(appt.teleconsult_state, 'scheduled')
        self.assertTrue(appt.teleconsult_channel_id)
        self.assertTrue(self.env['mail.mail'].search_count([
            ('model', '=', 'dental.appointment'), ('res_id', '=', appt.id),
            ('subject', 'ilike', 'online video consultation')]))
        appt.consultation_mode = 'in_clinic'
        self.assertEqual(appt.teleconsult_state, 'closed')

    def test_type_not_available_online(self):
        visit_type = self.env['dental.appointment.type'].create({'name': 'Surgical Extraction', 'allow_online': False})
        with self.assertRaises(ValidationError):
            self._online_appointment(appointment_type_id=visit_type.id, confirm=False)

    def test_disabled_branch(self):
        self.company.dental_teleconsult_enabled = False
        with self.assertRaises(ValidationError):
            self._online_appointment(confirm=False)

    # ---------------------------------------------------------------
    # Pay before joining
    # ---------------------------------------------------------------
    def test_payment_gate_paid_and_no_double_billing(self):
        appt = self._online_appointment()
        self.assertFalse(appt._teleconsult_can_join())
        self._pay(appt.teleconsult_invoice_id)
        self.assertIn(appt.teleconsult_invoice_id.payment_state, ('paid', 'in_payment'))
        self.assertEqual(appt.teleconsult_payment_state, 'paid')
        self.assertTrue(appt._teleconsult_can_join())
        self.assertFalse(appt._get_consultation_fee_line_vals(),
                         "The prepaid fee must not be billed again when the visit is completed")

    def test_waive_fee_requires_manager(self):
        appt = self._online_appointment()
        with self.assertRaises(AccessError):
            appt.with_user(self.receptionist_user).action_teleconsult_waive_payment()
        appt.with_user(self.manager_user).action_teleconsult_waive_payment()
        self.assertEqual(appt.teleconsult_payment_state, 'waived')
        self.assertTrue(appt._teleconsult_can_join())

    def test_prepayment_disabled(self):
        self.company.dental_teleconsult_require_prepayment = False
        appt = self._online_appointment()
        self.assertFalse(appt.teleconsult_invoice_id)
        self.assertEqual(appt.teleconsult_payment_state, 'not_required')

    # ---------------------------------------------------------------
    # Identity
    # ---------------------------------------------------------------
    def test_identity_check(self):
        appt = self._online_appointment()
        self.assertEqual(appt._teleconsult_identity_method(), 'dob')
        self.assertTrue(appt._teleconsult_check_identity(dob='1990-05-17'))
        self.assertFalse(appt._teleconsult_check_identity(dob='1990-05-18'))
        self.assertFalse(appt._teleconsult_check_identity(dob='not a date'))
        self.patient.date_of_birth = False
        self.assertEqual(appt._teleconsult_identity_method(), 'phone')
        self.assertTrue(appt._teleconsult_check_identity(phone_digits='1234'))
        self.assertFalse(appt._teleconsult_check_identity(phone_digits='4321'))
        self.company.dental_teleconsult_verify_identity = False
        self.assertFalse(appt._teleconsult_identity_method())

    def test_new_link_rotates_token(self):
        appt = self._online_appointment()
        old_token = appt.teleconsult_access_token
        appt.teleconsult_failed_verifications = 5
        appt.with_user(self.receptionist_user).action_teleconsult_send_link()
        self.assertNotEqual(appt.teleconsult_access_token, old_token)
        self.assertEqual(appt.teleconsult_failed_verifications, 0)

    # ---------------------------------------------------------------
    # Waiting room -> admit -> end
    # ---------------------------------------------------------------
    def test_full_session_guest(self):
        appt = self._online_appointment()
        self._pay(appt.teleconsult_invoice_id)
        guest = self._guest()
        public_partner = self.env.ref('base.public_partner')

        appt._teleconsult_patient_ready(guest=guest, recording_consent=False)
        self.assertEqual(appt.teleconsult_state, 'waiting')
        self.assertEqual(appt.state, 'checked_in', "Entering the waiting room checks the patient in")
        self.assertTrue(appt.token_number)
        self.assertTrue(appt.teleconsult_consent_at)
        channel = appt.teleconsult_channel_id
        self.assertNotIn(guest, channel.channel_member_ids.guest_id, "Not in the room before being admitted")
        self.assertTrue(channel.message_ids.filtered(lambda m: 'waiting' in (m.body or '')))
        coordination = self.env['discuss.channel'].search([('dental_channel_type', '=', 'coordination')])
        self.assertNotIn(public_partner, coordination.channel_member_ids.partner_id)

        # Only the clinical team admits
        with self.assertRaises(AccessError):
            appt.with_user(self.receptionist_user).action_teleconsult_admit()
        action = appt.with_user(self.dentist_user).action_teleconsult_admit()
        self.assertEqual(action['tag'], 'mail.action_discuss')
        self.assertEqual(action['context']['call'], 'accept')
        self.assertEqual(action['context']['active_id'], 'discuss.channel_%s' % channel.id)
        self.assertEqual(appt.teleconsult_state, 'in_call')
        self.assertEqual(appt.state, 'in_consultation')
        self.assertTrue(appt.teleconsult_started_at)
        self.assertIn(guest, channel.channel_member_ids.guest_id)

        # Chat during the call, then end it: patient removed, transcript archived
        channel.with_context(guest=guest).sudo().message_post(
            body='I have pain on the lower left side', message_type='comment', subtype_xmlid='mail.mt_comment',
            author_guest_id=guest.id, author_id=False)
        appt.with_user(self.dentist_user).action_teleconsult_end()
        self.assertEqual(appt.teleconsult_state, 'ended')
        self.assertTrue(appt.teleconsult_ended_at)
        self.assertNotIn(guest, channel.channel_member_ids.guest_id)
        self.assertIn(self.dentist_user.partner_id, channel.channel_member_ids.partner_id)
        transcript = appt.message_ids.filtered(lambda m: 'chat transcript' in (m.body or ''))
        self.assertTrue(transcript)
        self.assertIn('lower left side', transcript[0].body)

        # Reopen (ended by mistake), then completing the visit closes the room
        appt.with_user(self.dentist_user).action_teleconsult_reopen()
        self.assertEqual(appt.teleconsult_state, 'scheduled')

    def test_portal_patient_joins_with_account(self):
        portal_user = self.env['res.users'].create({
            'name': 'TC Patient', 'login': 'tc_patient_portal', 'partner_id': self.patient.id,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        appt = self._online_appointment()
        self.assertTrue(appt._teleconsult_is_patient_user(portal_user))
        self.assertFalse(appt._teleconsult_is_patient_user(self.env.ref('base.public_user')))
        appt.sudo().teleconsult_payment_waived = True
        appt._teleconsult_patient_ready(partner=portal_user.partner_id)
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        self.assertIn(self.patient, appt.teleconsult_channel_id.channel_member_ids.partner_id)
        appt.with_user(self.dentist_user).action_teleconsult_end()
        self.assertNotIn(self.patient, appt.teleconsult_channel_id.channel_member_ids.partner_id)

    def test_cancel_closes_room(self):
        appt = self._online_appointment()
        appt.sudo().teleconsult_payment_waived = True
        guest = self._guest()
        appt._teleconsult_patient_ready(guest=guest)
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        appt.write({'state': 'cancelled'})
        self.assertEqual(appt.teleconsult_state, 'closed')
        self.assertNotIn(guest, appt.teleconsult_channel_id.channel_member_ids.guest_id)

    def test_doctor_change_moves_room_membership(self):
        appt = self._online_appointment()
        appt.write({'doctor_id': self.other_doctor.id})
        members = appt.teleconsult_channel_id.channel_member_ids.partner_id
        self.assertIn(self.other_dentist_user.partner_id, members)
        self.assertNotIn(self.dentist_user.partner_id, members)

    def test_join_requires_clinician(self):
        appt = self._online_appointment()
        with self.assertRaises(AccessError):
            appt.with_user(self.receptionist_user).action_teleconsult_join()
        action = appt.with_user(self.dentist_user).action_teleconsult_join()
        self.assertEqual(action['tag'], 'mail.action_discuss')
        with self.assertRaises(UserError):
            appt.with_user(self.dentist_user).action_teleconsult_end()

    # ---------------------------------------------------------------
    # Recording
    # ---------------------------------------------------------------
    def test_recording_requires_setting_and_consent(self):
        appt = self._online_appointment()
        member = appt.teleconsult_channel_id.channel_member_ids.filtered(
            lambda m: m.partner_id == self.dentist_user.partner_id)
        perms = member._get_recording_permissions(self.dentist_user, sfu_url='https://sfu.example.com')
        self.assertFalse(any(perms.values()), "Recording is off by default")
        self.company.dental_teleconsult_allow_recording = True
        perms = member._get_recording_permissions(self.dentist_user, sfu_url='https://sfu.example.com')
        self.assertFalse(any(perms.values()), "No recording without the patient's consent")
        appt.teleconsult_recording_consent = True
        perms = member._get_recording_permissions(self.dentist_user, sfu_url='https://sfu.example.com')
        self.assertTrue(perms['videoRecording'])
        perms = member._get_recording_permissions(self.receptionist_user, sfu_url='https://sfu.example.com')
        self.assertFalse(any(perms.values()))

    # ---------------------------------------------------------------
    # Phase 2: patient files before the call, visit summary after it
    # ---------------------------------------------------------------
    def test_patient_files_reach_appointment_and_case(self):
        appt = self._online_appointment()
        files = [('lower-left.jpg', 'image/jpeg', b'\xff\xd8\xff\xe0fakejpeg'), ('xray.pdf', 'application/pdf', b'%PDF-1.4 x')]
        created = appt._teleconsult_add_patient_files(notes='Pain lower left for 3 days', files=files)
        self.assertEqual(len(created), 2)
        self.assertEqual(appt.teleconsult_upload_count, 2)
        self.assertEqual(appt.teleconsult_patient_notes, 'Pain lower left for 3 days')
        self.assertEqual(set(created.mapped('res_model')), {'dental.appointment'})

        # The file limit holds
        many = [('p%s.png' % i, 'image/png', b'\x89PNG x') for i in range(10)]
        appt._teleconsult_add_patient_files(files=many)
        self.assertEqual(appt.teleconsult_upload_count, 8)

        appt.sudo().teleconsult_payment_waived = True
        appt._teleconsult_patient_ready(guest=self._guest())
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        case = appt.case_id
        self.assertTrue(case, "Admitting starts the consultation, which opens the clinical case")
        note = case.message_ids.filtered(lambda m: 'Shared by the patient' in (m.body or ''))
        self.assertTrue(note)
        self.assertIn('Pain lower left', note.body)
        self.assertEqual(len(note.attachment_ids), 8)

    def test_visit_summary(self):
        appt = self._online_appointment()
        with self.assertRaises(UserError):
            appt.with_user(self.dentist_user).action_teleconsult_send_summary()  # call not held yet
        self._run_session(appt)
        with self.assertRaises(UserError):
            appt.with_user(self.dentist_user).action_teleconsult_send_summary()  # no outcome / advice
        rx = self._issued_prescription(appt)
        draft_rx = self._issued_prescription(appt)
        draft_rx.state = 'draft'
        self.assertEqual(appt._teleconsult_prescriptions(), rx, "Draft prescriptions are not shared")

        appt.write({'teleconsult_outcome': 'prescription',
                    'teleconsult_summary': '<p>Rinse with warm salt water twice a day.</p>'})
        with self.assertRaises(AccessError):
            appt.with_user(self.receptionist_user).action_teleconsult_send_summary()
        appt.with_user(self.dentist_user).action_teleconsult_send_summary()
        self.assertTrue(appt.teleconsult_summary_sent_at)
        mail = self.env['mail.mail'].search([('model', '=', 'dental.appointment'), ('res_id', '=', appt.id),
                                             ('subject', 'ilike', 'visit summary')])
        self.assertEqual(len(mail), 1)
        self.assertIn('warm salt water', mail.body_html)
        self.assertEqual(len(mail.attachment_ids), 2, "The visit summary PDF and the prescription are attached")
        self.assertIn(appt.teleconsult_summary_attachment_id, mail.attachment_ids)
        self.assertIn(rx.name.replace('/', '-'), ' '.join(mail.attachment_ids.mapped('name')))

    # ---------------------------------------------------------------
    # Reminders
    # ---------------------------------------------------------------
    def test_reminder_cron(self):
        soon = self._online_appointment(start_in=timedelta(minutes=10))
        later = self._online_appointment(start_in=timedelta(hours=2))
        self.env['dental.appointment']._cron_teleconsult_reminders()
        self.assertTrue(soon.teleconsult_reminder_sent)
        self.assertFalse(later.teleconsult_reminder_sent)
        self.assertTrue(self.env['mail.mail'].search_count([
            ('model', '=', 'dental.appointment'), ('res_id', '=', soon.id), ('subject', 'ilike', 'Starting soon')]))

    def test_window(self):
        appt = self._online_appointment(start_in=timedelta(days=2))
        opens, closes = appt._teleconsult_window()
        self.assertEqual(opens, appt.date_start - timedelta(minutes=15))
        self.assertEqual(closes, appt.date_end + timedelta(minutes=30))
        self.assertLess(fields.Datetime.now(), opens)

    def test_patient_display_name_and_clinic_time(self):
        appt = self._online_appointment(start_in=timedelta(days=2), confirm=False)
        # The dentist's name already carries the title: never "Dr. Dr. ..."
        self.assertEqual(appt.teleconsult_doctor_label, 'Dr. Video TC')
        self.doctor.name = 'Asha Varma'
        self.env.invalidate_all()  # doctor_id is hr.employee.public, an SQL view of hr.employee
        self.assertEqual(appt.teleconsult_doctor_label, 'Dr. Asha Varma')
        # Times shown to the patient follow the clinic's timezone, whoever renders them
        self.company.partner_id.tz = 'Asia/Kolkata'
        appt.invalidate_recordset(['teleconsult_start_display'])
        self.assertIn('(IST)', appt.teleconsult_start_display)
        as_reception = appt.with_user(self.receptionist_user)
        as_reception.invalidate_recordset(['teleconsult_start_display'])
        self.assertEqual(as_reception.teleconsult_start_display, appt.teleconsult_start_display)
