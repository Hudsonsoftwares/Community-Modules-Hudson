from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'abdm')
class TestDentalAbdm(TransactionCase):

    def test_profile_mapping_for_new_patient(self):
        profile = {'name': 'Ravi Kumar', 'abha_number': '91-1111-2222-3333',
                   'dob': date(1990, 5, 17), 'gender': 'M', 'mobile': '9876543210'}
        Partner = self.env['res.partner']
        vals = Partner._abdm_partner_vals_from_profile(profile, for_create=True)
        self.assertEqual(vals['date_of_birth'], date(1990, 5, 17))
        self.assertEqual(vals['gender'], 'male')
        self.assertTrue(vals['is_dental_patient'])
        patient = Partner.create(vals)
        patient._abdm_apply_abha_profile(profile, 'aadhaar_otp')
        self.assertTrue(patient.is_dental_patient)
        self.assertNotEqual(patient.dental_patient_id, 'New', 'Patient ID assigned')
        self.assertEqual(patient.abha_number, '91-1111-2222-3333')

        update = Partner._abdm_partner_vals_from_profile(dict(profile, gender='F'))
        self.assertNotIn('is_dental_patient', update, 'only new contacts become patients')
        self.assertEqual(update['gender'], 'female')

    def test_roles_get_abha_access(self):
        abdm_user = self.env.ref('abdm_base.group_abdm_user')
        for xmlid in ('dental_base.group_dental_receptionist', 'dental_base.group_dental_dentist'):
            group = self.env.ref(xmlid)
            self.assertIn(abdm_user, group.all_implied_ids)

    def test_views_load(self):
        form = self.env['res.partner'].get_views([(False, 'form')])
        arch = form['views']['form']['arch']
        self.assertIn('action_abdm_abha_wizard', arch)
        self.assertTrue(self.env.ref('dental_abdm.menu_dental_abha_registration').action)
