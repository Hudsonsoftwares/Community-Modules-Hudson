# -*- coding: utf-8 -*-
import json
from datetime import date, timedelta

from odoo.tests import HttpCase, TransactionCase, tagged

from .common import TeleconsultCommonMixin


class TeleconsultBookingMixin(TeleconsultCommonMixin):

    @classmethod
    def _setup_booking(cls):
        cls._setup_teleconsult_clinic()
        AppointmentType = cls.env['dental.appointment.type']
        cls.type_online = AppointmentType.create({'name': 'TC Video Review', 'duration': 30, 'allow_online': True})
        cls.type_clinic_only = AppointmentType.create({'name': 'TC Scaling', 'duration': 30, 'allow_online': False})
        cls.public_user = cls.env.ref('base.public_user')

    def _free_slot(self):
        Appointment = self.env['dental.appointment'].sudo()
        for offset in range(1, 15):
            day = (date.today() + timedelta(days=offset)).isoformat()
            res = Appointment.get_available_slots(date=day, doctor_id=self.doctor.id, duration=30,
                                                  branch_id=self.company.id)
            slot = next((s for s in res['slots'] if s['available']), None)
            if slot:
                return day, slot['time']
        self.skipTest("No free clinic slot for the test dentist in the next two weeks")

    def _post(self, **extra):
        day, time = self._free_slot()
        post = {
            'patient_type': 'new', 'name': 'Web Video Patient', 'phone': '+91 90000 77123',
            'email': 'web.video@example.com', 'dob': '1988-02-03', 'gender': 'female',
            'appointment_type_id': self.type_online.id, 'doctor_id': self.doctor.id,
            'branch_id': self.company.id, 'appointment_date': day, 'appointment_time': time,
            'consultation_mode': 'online',
        }
        post.update(extra)
        return post

    def _mail_subjects(self, appt):
        return self.env['mail.mail'].sudo().search([
            ('model', '=', 'dental.appointment'), ('res_id', '=', appt.id)]).mapped('subject')


@tagged('post_install', '-at_install', 'dental_teleconsult')
class TestTeleconsultBooking(TeleconsultBookingMixin, TransactionCase):
    """Online consultations booked through the website booking engine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_booking()

    def _book_as_public(self, post):
        return self.env['dental.appointment'].with_user(self.public_user).sudo().create_appointment_booking(post)

    def test_website_online_request_then_confirm(self):
        res = self._book_as_public(self._post())
        self.assertTrue(res['success'], res.get('error'))
        self.assertEqual(res['consultation_mode'], 'online')
        self.assertIn('online video', res['service_name'])
        self.assertIn('will confirm', res['teleconsult_message'])
        appt = self.env['dental.appointment'].browse(res['appointment_id'])
        self.assertEqual(appt.consultation_mode, 'online')
        self.assertEqual(appt.state, 'pending')
        self.assertFalse(appt.teleconsult_access_token, "No join link before the clinic confirms")
        subjects = self._mail_subjects(appt)
        self.assertTrue(any('received your online consultation request' in s for s in subjects), subjects)
        self.assertFalse(any(s.startswith('Appointment Confirmation') for s in subjects),
                         "The in-clinic confirmation must not be sent for an online request")

        appt.with_user(self.receptionist_user).action_confirm()
        self.assertTrue(appt.teleconsult_access_token)
        self.assertTrue(appt.teleconsult_invoice_id, "Pay-before-join: fee requested at confirmation")
        subjects = self._mail_subjects(appt)
        self.assertTrue(any('Your online video consultation' in s for s in subjects), subjects)

    def test_front_desk_booking_is_confirmed_and_invited_once(self):
        res = self.env['dental.appointment'].with_user(self.receptionist_user).create_appointment_booking(
            self._post(name='Desk Video Patient', phone='+91 90000 66321', email='desk.video@example.com'))
        self.assertTrue(res['success'], res.get('error'))
        appt = self.env['dental.appointment'].browse(res['appointment_id'])
        self.assertEqual(appt.state, 'confirmed')
        self.assertTrue(appt.teleconsult_access_token)
        self.assertIn('is confirmed', res['teleconsult_message'])
        subjects = self._mail_subjects(appt)
        self.assertEqual(len([s for s in subjects if 'Your online video consultation' in s]), 1, subjects)
        self.assertFalse(any(s.startswith('Appointment Confirmation') for s in subjects), subjects)

    def test_online_refused_for_in_clinic_only_type(self):
        res = self._book_as_public(self._post(appointment_type_id=self.type_clinic_only.id))
        self.assertFalse(res['success'])
        self.assertIn('cannot be done as an online consultation', res['error'])

    def test_online_refused_when_branch_disabled(self):
        self.company.dental_teleconsult_enabled = False
        res = self._book_as_public(self._post())
        self.assertFalse(res['success'])
        self.assertIn('not offered', res['error'])

    def test_in_clinic_booking_unchanged(self):
        res = self._book_as_public(self._post(consultation_mode='in_clinic', name='Clinic Web Patient',
                                              phone='+91 90000 55432', email='clinic.web@example.com'))
        self.assertTrue(res['success'], res.get('error'))
        self.assertNotIn('consultation_mode', res)
        appt = self.env['dental.appointment'].browse(res['appointment_id'])
        self.assertEqual(appt.consultation_mode, 'in_clinic')
        self.assertTrue(any(s.startswith('Appointment Confirmation') for s in self._mail_subjects(appt)))


@tagged('post_install', '-at_install', 'dental_teleconsult')
class TestTeleconsultBookingHttp(TeleconsultBookingMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_booking()

    def test_booking_page_offers_online_option(self):
        page = self.url_open('/book-appointment')
        self.assertEqual(page.status_code, 200)
        self.assertIn('step5_booking_form', page.text, "The 6-step website booking template is served")
        self.assertIn('o_dental_tc_booking_mode', page.text)
        self.assertIn('data-allow-online="0"', page.text)

        self.company.dental_teleconsult_enabled = False
        self.assertNotIn('o_dental_tc_booking_mode', self.url_open('/book-appointment').text)

    def test_json_booking_route(self):
        response = self.url_open('/dental/book_appointment', data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'params': self._post()}),
            headers={'Content-Type': 'application/json'})
        result = response.json()['result']
        self.assertTrue(result['success'], result.get('error'))
        appt = self.env['dental.appointment'].browse(result['appointment_id'])
        self.assertEqual(appt.consultation_mode, 'online')
        self.assertEqual(appt.state, 'pending')
