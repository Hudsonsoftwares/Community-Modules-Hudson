from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_multi_company')
class TestPharmacyMultiCompany(TransactionCase):
    """Prescriptions, lines and dispensing stay inside their branch (see dental_base/SECURITY.md)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Pharmacy Branch B'})
        cls.patient = cls.env['res.partner'].create({'name': 'Rx Patient', 'is_dental_patient': True})
        cls.dentist_b = cls.env['hr.employee'].create({'name': 'Dr. Rx B', 'dental_role': 'dentist', 'company_id': cls.company_b.id})
        cls.medicine = cls.env['product.product'].create({'name': 'Amoxicillin MC Test', 'is_medicine': True, 'list_price': 5.0})
        cls.rx_b = cls.env['dental.prescription'].with_company(cls.company_b).create({
            'patient_id': cls.patient.id, 'dentist_id': cls.dentist_b.id, 'company_id': cls.company_b.id,
            'line_ids': [(0, 0, {'medicine_id': cls.medicine.id, 'quantity': 10})],
        })
        common = {'company_id': cls.company_a.id, 'company_ids': [cls.company_a.id]}
        # Root cause: these groups had unfiltered rows (admin on prescriptions, dentist on dispensing)
        # which OR-ed away the company filters of the other rows.
        cls.admin_a = new_test_user(cls.env, login='rx_admin_a', groups='base.group_user,dental_base.group_dental_admin', **common)
        cls.dentist_a = new_test_user(cls.env, login='rx_dentist_a', groups='base.group_user,dental_base.group_dental_dentist', **common)

    def test_prescription_and_lines_isolated(self):
        self.assertEqual(self.rx_b.line_ids.company_id, self.company_b)
        for user in (self.admin_a, self.dentist_a):
            self.assertFalse(self.env['dental.prescription'].with_user(user).search([('id', '=', self.rx_b.id)]), user.login)
            self.assertFalse(self.env['dental.prescription.line'].with_user(user).search([('id', 'in', self.rx_b.line_ids.ids)]), user.login)
            with self.assertRaises(AccessError):
                self.rx_b.with_user(user).read(['name'])

    def test_prescription_cannot_link_foreign_case(self):
        case_b = self.env['dental.case'].with_company(self.company_b).create({
            'patient_id': self.patient.id, 'company_id': self.company_b.id, 'chief_complaint': 'x'})
        with self.assertRaises((UserError, ValidationError)):
            self.env['dental.prescription'].with_company(self.company_a).create({
                'patient_id': self.patient.id, 'dentist_id': self.dentist_b.id,
                'company_id': self.company_a.id, 'case_id': case_b.id})
