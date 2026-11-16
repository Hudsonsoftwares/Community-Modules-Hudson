from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_booking_search')
class TestBookingPatientSearch(TransactionCase):
    """Staff booking: find registered patients by name, phone, email or Patient ID."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.receptionist = new_test_user(cls.env, login='bk_reception', groups='base.group_user,dental_base.group_dental_receptionist',
                                         company_id=company.id, company_ids=[company.id])
        Partner = cls.env['res.partner']
        cls.anita = Partner.create({'name': 'Anita Varghese', 'is_dental_patient': True, 'phone': '98470 12345',
                                    'email': 'anita@example.com'})
        cls.anand = Partner.create({'name': 'Anand Kumar', 'is_dental_patient': True, 'phone': '9000011111'})
        cls.not_patient = Partner.create({'name': 'Anil Supplier', 'phone': '9000022222'})

    def _search(self, term):
        return [p['id'] for p in self.env['dental.appointment'].with_user(self.receptionist).search_booking_patients(term)]

    def test_search_by_name_phone_email_and_id(self):
        self.assertIn(self.anita.id, self._search('anita'))
        self.assertIn(self.anita.id, self._search('varghese'))
        self.assertEqual(set(self._search('ana')), {self.anand.id}, "Partial name, patients only")
        self.assertIn(self.anita.id, self._search('12345'))
        self.assertIn(self.anita.id, self._search('anita@example'))
        self.assertIn(self.anita.id, self._search(self.anita.dental_patient_id))
        self.assertNotIn(self.not_patient.id, self._search('anil'), "Non-patients are never offered")
        self.assertEqual(self._search('a'), [], "At least 2 characters")

    def test_search_is_staff_only(self):
        portal = new_test_user(self.env, login='bk_portal', groups='base.group_portal')
        with self.assertRaises(AccessError):
            self.env['dental.appointment'].with_user(portal).search_booking_patients('anita')

    def test_public_lookup_still_exact_only(self):
        # The website lookup must not become a name search (privacy)
        res = self.env['dental.appointment'].sudo().check_patient(identifier='Anita')
        self.assertFalse(res.get('found'))

    def test_registered_patient_payload(self):
        data = self.env['dental.appointment'].with_user(self.receptionist).get_booking_patient(self.anand.id)
        self.assertEqual(data['name'], 'Anand Kumar')

    def test_clinic_app_tabs_removed(self):
        admin = self.env.ref('base.user_admin')
        root = self.env.ref('dental_base.menu_dental_root')
        menus = self.env['ir.ui.menu'].with_user(admin).load_menus(False)
        names = [menus[c]['name'] for c in menus[root.id]['children']]
        for hidden in ('Laboratory', 'Second Opinions', 'Documents'):
            self.assertNotIn(hidden, names)


@tagged('post_install', '-at_install', 'dental_booking_search_ui')
class TestBookingFlowUI(HttpCase):
    """Step 1 shows live suggestions and waits for an explicit choice before continuing."""

    def test_live_suggestions_and_explicit_selection(self):
        self.env['res.partner'].create({'name': 'Zelda Fernandes', 'is_dental_patient': True, 'phone': '9000033333'})
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        const value = check();
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 150) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const $ = (sel) => document.querySelector(sel);
                const input = await wait(() => $('.patient-search-wrap input'), 'search input');
                if ([...document.querySelectorAll('.choice-label')].some((e) => e.textContent.includes('New Patient'))) {
                    throw new Error('New/Existing patient choice should be gone');
                }
                if (![...document.querySelectorAll('button')].some((b) => b.textContent.includes('Register New Patient'))) {
                    throw new Error('Register New Patient button missing');
                }
                const next = $('.btn-next');
                if (!next.disabled) { throw new Error('Continue must be disabled until a patient is selected'); }

                input.focus();
                input.value = 'zeld';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                await wait(() => [...document.querySelectorAll('.patient-suggestion')]
                    .find((o) => o.textContent.includes('Zelda Fernandes')), 'live suggestion');
                // Searching alone never moves on
                [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Search').click();
                await new Promise((r) => setTimeout(r, 800));
                if (!$('.patient-search-wrap')) { throw new Error('Search must not skip the patient choice'); }

                const fresh = await wait(() => [...document.querySelectorAll('.patient-suggestion')]
                    .find((o) => o.textContent.includes('Zelda Fernandes')), 'suggestion after search');
                fresh.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                await wait(() => $('.patient-preview-card') && !$('.btn-next').disabled, 'patient selected');
                $('.btn-next').click();
                await wait(() => [...document.querySelectorAll('.flow-title')].some((t) => t.textContent.includes('Choose Service')), 'step 2');
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """
        self.browser_js('/odoo/action-dental_appointment.action_dental_appointment_book_flow', code, login='admin', timeout=120)

    def test_register_new_patient_in_popup(self):
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        const value = check();
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 150) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const $ = (sel) => document.querySelector(sel);
                const setValue = (el, value) => {
                    el.value = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                };
                const register = await wait(() => [...document.querySelectorAll('button')]
                    .find((b) => b.textContent.includes('Register New Patient')), 'register button');
                register.click();
                const nameInput = await wait(() => $('.modal .o_field_widget[name="name"] input, .modal .o_field_widget[name="name"] textarea'), 'name field');
                setValue(nameInput, 'Yusuf Popup Patient');
                const phone = $('.modal .o_field_widget[name="phone"] input');
                if (phone) { setValue(phone, '9000044444'); }
                await new Promise((r) => setTimeout(r, 300));
                (await wait(() => $('.modal .o_form_button_save, .modal .modal-footer .btn-primary'), 'save')).click();
                await wait(() => !$('.modal') && $('.patient-preview-card') &&
                    $('.patient-preview-card').textContent.includes('Yusuf Popup Patient') && !$('.btn-next').disabled, 'new patient selected');
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """
        self.browser_js('/odoo/action-dental_appointment.action_dental_appointment_book_flow', code, login='admin', timeout=120)
        patient = self.env['res.partner'].search([('name', '=', 'Yusuf Popup Patient')])
        self.assertTrue(patient.is_dental_patient)
