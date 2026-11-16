# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged

from .test_teleconsult_booking import TeleconsultBookingMixin


@tagged('post_install', '-at_install', 'dental_teleconsult', 'dental_teleconsult_ui')
class TestTeleconsultBookingUI(TeleconsultBookingMixin, HttpCase):
    """The Online / At the clinic choice in a real browser (website and staff booking flows)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_booking()
        cls.env.ref('base.user_admin').write({'group_ids': [
            (4, cls.env.ref('dental_base.group_dental_receptionist').id)]})

    def test_website_online_booking(self):
        day, time = self._free_slot()
        params = json.dumps({
            'day': day, 'time': time, 'doctor': self.doctor.id,
            'online_type': self.type_online.id, 'clinic_type': self.type_clinic_only.id,
        })
        code = """
            (async () => {
                const P = %s;
                const $ = (s) => document.querySelector(s);
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        let value = false;
                        try { value = check(); } catch (e) { value = false; }
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 150) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const box = await wait(() => $('.o_dental_tc_booking_mode.o_dental_tc_ready'), 'online choice started');
                const online = box.querySelector('[data-mode="online"]');
                const hint = box.querySelector('.o_dental_tc_online_hint');

                // An in-clinic-only appointment type disables the online choice
                $(`.type-choice-card[data-id="${P.clinic_type}"]`).click();
                await wait(() => online.disabled, 'online disabled for in-clinic-only type');
                if (box.querySelector('.o_dental_tc_unavailable').classList.contains('d-none')) {
                    throw new Error('the in-clinic-only notice must be shown');
                }
                // An online-capable type enables it
                $(`.type-choice-card[data-id="${P.online_type}"]`).click();
                await wait(() => !online.disabled, 'online enabled');
                online.click();
                await wait(() => online.classList.contains('active') && !hint.classList.contains('d-none'), 'online selected');

                // Fill step 5 with a real free slot and submit the actual form
                Object.assign(flowState, {
                    patientType: 'new', serviceId: String(P.online_type), serviceDuration: 30,
                    serviceName: 'TC Video Review', providerId: P.doctor, providerName: 'Dr. Video TC',
                    selectedDate: P.day, selectedTime: P.time,
                    selectedDateFormatted: P.day, selectedTimeFormatted: P.time,
                });
                const fill = (id, value) => { const el = document.getElementById(id); el.value = value; };
                fill('inp_first_name', 'Browser'); fill('inp_last_name', 'Video');
                fill('inp_email', 'browser.video@example.com'); fill('inp_phone', '+91 90000 44321');
                fill('inp_gender', 'male'); fill('inp_dob_year', '1985');
                goToStep(5);
                $('#step5_booking_form').requestSubmit();
                await wait(() => !$('#pane_step_success').classList.contains('d-none'), 'booking success screen');
                const title = $('#pane_step_success h3').textContent;
                if (!title.includes('Online Consultation Requested')) { throw new Error('success title: ' + title); }
                const note = $('#pane_step_success .o_dental_tc_success_online');
                if (note.classList.contains('d-none') || !note.textContent.includes('secure join link')) {
                    throw new Error('online next steps must be explained');
                }
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """ % params
        self.browser_js('/book-appointment', code, timeout=120)
        appt = self.env['dental.appointment'].search([('patient_id.email', '=', 'browser.video@example.com')])
        self.assertEqual(len(appt), 1)
        self.assertEqual(appt.consultation_mode, 'online')
        self.assertEqual(appt.state, 'pending')

    def test_staff_booking_flow_loads(self):
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        if (check()) { clearInterval(timer); resolve(true); }
                        else if (++tries > 150) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                await wait(() => document.querySelector('.step-pane'), 'staff booking flow rendered');
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """
        self.browser_js('/odoo/action-dental_appointment.action_dental_appointment_book_flow', code,
                        login='admin', timeout=120)
