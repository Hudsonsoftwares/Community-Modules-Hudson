# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo.tests import new_test_user


class TeleconsultCommonMixin:
    """Shared clinic set-up: a dentist with a consultation fee, front desk, manager and a patient."""

    @classmethod
    def _setup_teleconsult_clinic(cls):
        cls.company = cls.env.company
        cls.company.write({
            'dental_teleconsult_enabled': True,
            'dental_teleconsult_require_prepayment': True,
            'dental_teleconsult_verify_identity': True,
            'dental_teleconsult_allow_recording': False,
            'dental_teleconsult_join_before': 15,
            'dental_teleconsult_join_after': 30,
            'dental_teleconsult_reminder_minutes': 15,
        })
        Employee = cls.env['hr.employee']
        # Unrelated add-on hooks (DMS folders) must not interfere with these tests
        if hasattr(type(Employee), '_setup_dms_folder_and_permissions'):
            cls.startClassPatcher(patch.object(
                type(Employee), '_setup_dms_folder_and_permissions', lambda self: None))
        common = {'company_id': cls.company.id, 'company_ids': [cls.company.id]}
        cls.dentist_user = new_test_user(
            cls.env, login='tc_dentist', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.other_dentist_user = new_test_user(
            cls.env, login='tc_dentist_2', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.receptionist_user = new_test_user(
            cls.env, login='tc_reception',
            groups='base.group_user,dental_base.group_dental_receptionist,account.group_account_invoice', **common)
        cls.manager_user = new_test_user(
            cls.env, login='tc_manager', groups='base.group_user,dental_base.group_dental_manager', **common)
        cls.doctor = Employee.create({
            'name': 'Dr. Video TC', 'dental_role': 'dentist', 'user_id': cls.dentist_user.id,
            'company_id': cls.company.id, 'consultation_fee': 50.0,
        })
        cls.other_doctor = Employee.create({
            'name': 'Dr. Second TC', 'dental_role': 'dentist', 'user_id': cls.other_dentist_user.id,
            'company_id': cls.company.id, 'consultation_fee': 50.0,
        })
        cls.patient = cls.env['res.partner'].create({
            'name': 'TC Patient', 'is_dental_patient': True, 'phone': '+91 98765 41234',
            'email': 'tc.patient@example.com', 'date_of_birth': date(1990, 5, 17),
        })

    def _online_appointment(self, start_in=timedelta(minutes=5), confirm=True, user=None, **extra):
        start = datetime.now().replace(microsecond=0) + start_in
        vals = {
            'patient_id': self.patient.id, 'doctor_id': self.doctor.id, 'branch_id': self.company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30),
            'consultation_mode': 'online', 'reason': 'Tooth pain',
        }
        vals.update(extra)
        appt = self.env['dental.appointment'].with_user(user or self.receptionist_user).create(vals)
        if confirm:
            appt.action_confirm()
        return appt.with_env(self.env)

    def _issued_prescription(self, appt):
        medicine = self.env['product.product'].create({'name': 'Amoxicillin TC 500', 'is_medicine': True})
        rx = self.env['dental.prescription'].create({
            'patient_id': self.patient.id, 'dentist_id': self.doctor.id, 'appointment_id': appt.id,
            'company_id': self.company.id,
            'line_ids': [(0, 0, {'medicine_id': medicine.id, 'quantity': 10})]})
        rx.state = 'issued'
        return rx

    def _run_session(self, appt):
        """Paid patient waits, is admitted and the doctor ends the call."""
        appt.sudo().teleconsult_payment_waived = True
        appt._teleconsult_patient_ready(guest=self.env['mail.guest'].create({'name': self.patient.name}))
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        appt.with_user(self.dentist_user).action_teleconsult_end()

    def _pay(self, invoice):
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        invoice.invalidate_recordset()
