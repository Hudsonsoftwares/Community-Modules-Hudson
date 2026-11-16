# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser

_spawn_chrome = ChromeBrowser._spawn_chrome


def _spawn_chrome_without_webgl(self, cmd):
    # The case form hosts the 3D odontogram; software WebGL is far too slow in a headless browser
    return _spawn_chrome(self, cmd[:-1] + ['--disable-webgl', '--disable-3d-apis'] + cmd[-1:])


@tagged('post_install', '-at_install', 'dental_rx_ui')
class TestCasePrescriptionUI(HttpCase):
    """Prescriptions tab: medicines are typed inline (no dialog), each line shows the pharmacy
    forecast icon, and earlier prescriptions are listed as cards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.write({'group_ids': [(4, cls.env.ref('dental_base.group_dental_dentist').id),
                                   (4, cls.env.ref('stock.group_stock_user').id)]})
        dentist = cls.env['hr.employee'].create({
            'name': 'Dr. Rx UI', 'dental_role': 'dentist', 'registration_number': 'RX-UI-1', 'user_id': admin.id})
        patient = cls.env['res.partner'].create({'name': 'Rx UI Patient', 'is_dental_patient': True})
        medicine = cls.env['product.product'].create({
            'name': 'Metronidazole UI Test', 'is_medicine': True, 'dosage_form': 'tablet',
            'strength': '400 mg', 'list_price': 1.0, 'is_storable': True})
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.env['stock.quant']._update_available_quantity(medicine, warehouse.lot_stock_id, 50.0)
        old_case = cls.env['dental.case'].create({
            'patient_id': patient.id, 'doctor_id': dentist.id, 'chief_complaint': 'Old abscess'})
        old_rx = cls.env['dental.prescription'].create({
            'patient_id': patient.id, 'case_id': old_case.id, 'dentist_id': dentist.id,
            'prescription_date': date(2026, 1, 10), 'diagnosis': 'Old abscess 36',
            'line_ids': [(0, 0, {'medicine_id': medicine.id, 'dose': '1 tablet', 'frequency': 'tid',
                                 'duration': 5, 'quantity': 15.0})]})
        old_rx.action_confirm()
        cls.case = cls.env['dental.case'].create({
            'patient_id': patient.id, 'doctor_id': dentist.id, 'chief_complaint': 'Swelling 46', 'state': 'open'})
        cls.env['dental.prescription'].create({
            'patient_id': patient.id, 'case_id': cls.case.id, 'dentist_id': dentist.id,
            'line_ids': [(0, 0, {'medicine_id': medicine.id, 'dose': '1 tablet', 'frequency': 'bid',
                                 'duration': 3, 'quantity': 6.0})]})

    def test_prescriptions_tab(self):
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        let value = false;
                        try { value = check(); } catch (e) { value = false; }
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 300) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const $ = (sel, root = document) => root.querySelector(sel);
                const tab = await wait(() => [...document.querySelectorAll('.o_notebook .nav-link')]
                    .find((a) => a.textContent.trim() === 'Prescriptions'), 'Prescriptions tab');
                tab.click();
                const editor = await wait(() => $('div[name="rx_editor"]'), 'prescription editor');
                const linesField = $('div[name="rx_line_ids"]', editor);
                await wait(() => linesField.textContent.includes('Metronidazole UI Test'), 'draft line listed');

                // Forecast icon opens the availability popover
                const icon = await wait(() => linesField.querySelector('a.oi[data-icon="area_chart"]:not(.invisible)'), 'forecast icon');
                if (!icon.classList.contains('text-success')) { throw new Error('In-stock medicine must show a green icon: ' + icon.className); }
                icon.click();
                const popover = await wait(() => [...document.querySelectorAll('.o_popover')]
                    .find((p) => p.textContent.includes('Pharmacy Availability')), 'availability popover');
                if (!popover.textContent.includes('50')) { throw new Error('Popover must show the 50 on hand: ' + popover.textContent); }
                if (!popover.textContent.includes('View Forecast')) { throw new Error('Stock users get the forecast link'); }
                const outside = document.querySelector('.o_form_sheet_bg') || document.body;
                outside.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                outside.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                await wait(() => ![...document.querySelectorAll('.o_popover')].some((p) => p.textContent.includes('Pharmacy Availability')), 'popover closed');

                // Add a line: an editable row, never a dialog
                const add = await wait(() => linesField.querySelector('.o_field_x2many_list_row_add button, .o_field_x2many_list_row_add a'), 'Add a line');
                add.click();
                await wait(() => linesField.querySelector('.o_selected_row'), 'editable row');
                if (document.querySelector('.modal-dialog')) { throw new Error('Adding a medicine must not open a dialog'); }
                if (!$('button[name="action_rx_finalize"]:not(.o_invisible_modifier)', editor)) { throw new Error('Finalize button missing'); }

                // Earlier prescription shown as a card
                await wait(() => [...document.querySelectorAll('div[name="previous_prescription_ids"] .o_kanban_record')]
                    .some((c) => c.textContent.includes('Old abscess 36') && c.textContent.includes('Metronidazole UI Test')), 'previous prescription card');

                const discard = $('.o_form_button_cancel');
                if (discard) { discard.click(); }
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """
        with patch.object(ChromeBrowser, '_spawn_chrome', _spawn_chrome_without_webgl):
            self.browser_js(f'/odoo/action-dental_core.action_dental_case/{self.case.id}', code, login='admin', timeout=120)
