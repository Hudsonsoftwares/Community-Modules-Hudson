# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged('post_install', '-at_install', 'dental_pharmacy_pos_ui')
class TestPosPharmacyUI(TestPointOfSaleHttpCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env.user.group_ids |= env.ref('dental_base.group_dental_manager')
        company = cls.main_pos_config.company_id
        company.write({'dental_has_pharmacy': True, 'dental_dispense_mode': 'pos'})
        cls.main_pos_config.write({
            'dental_pharmacy_counter': True,
            'dental_walkin_partner_id': env.ref('dental_pharmacy_pos.partner_pharmacy_walkin').id,
        })
        cls.patient = env['res.partner'].create({
            'name': 'Tour Rx Patient', 'is_dental_patient': True,
            'allergy_status': 'known', 'allergies': '<p>Penicillin</p>',
        })
        dentist = env['hr.employee'].sudo().create({'name': 'Dr. Tour', 'dental_role': 'dentist'})
        cls.medicine = env['product.product'].create({
            'name': 'Tour Amoxicillin', 'is_medicine': True, 'is_storable': True, 'tracking': 'lot',
            'lst_price': 5.0, 'taxes_id': [Command.clear()], 'company_id': company.id,
        })
        location = cls.main_pos_config.picking_type_id.default_location_src_id
        for name, days in (('TOUR-LATE', 200), ('TOUR-SOON', 20), ('TOUR-OLD', -3)):
            lot = env['stock.lot'].create({'name': name, 'product_id': cls.medicine.id,
                                           'expiry_date': date.today() + timedelta(days=days)})
            env['stock.quant']._update_available_quantity(cls.medicine, location, 20, lot_id=lot)
        cls.rx = env['dental.prescription'].with_company(company).create({
            'patient_id': cls.patient.id, 'dentist_id': dentist.id, 'company_id': company.id,
            'line_ids': [Command.create({'medicine_id': cls.medicine.id, 'quantity': 6,
                                         'frequency': 'tid', 'duration': 2})],
        })
        cls.rx.action_confirm()

    def test_counter_dispenses_prescription(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.start_pos_tour('DentalPharmacyCounterTour')

        self.env.invalidate_all()
        order = self.env['pos.order'].sudo().search([('config_id', '=', self.main_pos_config.id)])
        self.rx.invalidate_recordset()
        self.assertEqual(len(order), 1)
        self.assertEqual(order.partner_id, self.patient)
        self.assertTrue(order.account_move, "The counter sale is invoiced")
        self.assertEqual(order.lines.dental_prescription_line_id, self.rx.line_ids)
        self.assertEqual(order.lines.pack_lot_ids.lot_name, 'TOUR-SOON', "Earliest unexpired batch")
        dispense = order.dental_dispense_ids
        self.assertEqual(dispense.prescription_id, self.rx)
        self.assertEqual(dispense.state, 'dispensed')
        self.assertEqual(self.rx.state, 'fully_dispensed')
        self.assertIn('Three times daily', order.lines.customer_note)
