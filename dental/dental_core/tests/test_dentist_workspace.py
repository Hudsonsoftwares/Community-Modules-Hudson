from datetime import datetime, timedelta

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_dentist_workspace')
class TestDentistWorkspaceAccess(TransactionCase):
    """The Dentist Workspace belongs only to users linked to an employee with Dental Role = Dentist,
    and always shows that user's own data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root_menu = cls.env.ref('dental_core.menu_dental_dentist_workspace')
        company = cls.env.company
        common = {'company_id': company.id, 'company_ids': [company.id]}

        cls.dentist_user = new_test_user(cls.env, login='ws_dentist', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.other_dentist_user = new_test_user(cls.env, login='ws_other_dentist', groups='base.group_user,dental_base.group_dental_dentist', **common)
        # Dental Administrator permission but no dentist employee profile (the reported case)
        cls.admin_no_profile = new_test_user(cls.env, login='ws_admin_no_profile',
                                             groups='base.group_user,dental_base.group_dental_dentist,dental_base.group_dental_admin', **common)
        cls.receptionist = new_test_user(cls.env, login='ws_reception', groups='base.group_user,dental_base.group_dental_receptionist', **common)

        Employee = cls.env['hr.employee']
        cls.doctor = Employee.create({'name': 'Dr. Own', 'dental_role': 'dentist', 'user_id': cls.dentist_user.id, 'company_id': company.id})
        cls.other_doctor = Employee.create({'name': 'Dr. Other', 'dental_role': 'dentist', 'user_id': cls.other_dentist_user.id, 'company_id': company.id})
        # Linked to an employee, but not as a dentist
        cls.admin_employee = Employee.create({'name': 'Admin Staff', 'dental_role': 'admin', 'user_id': cls.admin_no_profile.id, 'company_id': company.id})

        patient = cls.env['res.partner'].create({'name': 'WS Patient', 'is_dental_patient': True, 'phone': '9000000077'})
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
        cls.other_appt = cls.env['dental.appointment'].create({
            'patient_id': patient.id, 'doctor_id': cls.other_doctor.id, 'branch_id': company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
        })

    def _sees_workspace(self, user):
        menus = self.env['ir.ui.menu'].with_user(user).load_menus(False)
        roots = self.env['ir.ui.menu'].with_user(user).get_user_roots()
        in_menus = self.root_menu.id in menus
        self.assertEqual(in_menus, self.root_menu in roots, "App list and menu tree must agree")
        return in_menus

    def test_menu_requires_dentist_employee(self):
        self.assertTrue(self._sees_workspace(self.dentist_user))
        self.assertFalse(self._sees_workspace(self.admin_no_profile),
                         "A dental permission without a Dentist employee profile must not show the workspace")
        self.assertFalse(self._sees_workspace(self.receptionist))

    def test_menu_follows_employee_changes(self):
        self.assertFalse(self._sees_workspace(self.admin_no_profile))
        self.admin_employee.dental_role = 'dentist'
        self.assertTrue(self._sees_workspace(self.admin_no_profile))
        self.admin_employee.action_archive()
        self.assertFalse(self._sees_workspace(self.admin_no_profile))

    def test_dashboard_without_profile_returns_no_data(self):
        res = self.env['dental.appointment'].with_user(self.admin_no_profile).get_dentist_dashboard_data()
        self.assertFalse(res['has_doctor'])
        self.assertNotIn('today_schedule', res)
        self.assertNotIn('kpi_stats', res)

    def test_dashboard_rejects_non_dental_users(self):
        with self.assertRaises(AccessError):
            self.env['dental.appointment'].with_user(self.receptionist).get_dentist_dashboard_data()

    def test_checked_in_patient_booked_for_another_day_is_in_queue(self):
        """Reported case: booked for tomorrow, checked in today -> must be in today's queue."""
        patient = self.env['res.partner'].create({'name': 'Early Patient', 'is_dental_patient': True, 'phone': '9000000078'})
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        appt = self.env['dental.appointment'].create({
            'patient_id': patient.id, 'doctor_id': self.doctor.id, 'branch_id': self.env.company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
        })
        appt.action_check_in()
        res = self.env['dental.appointment'].with_user(self.dentist_user).get_dentist_dashboard_data()
        self.assertIn(appt.id, [row['id'] for row in res['waiting_queue']])
        self.assertIn(appt.id, [row['id'] for row in res['today_schedule']])
        # The dentist can start the consultation from the dashboard
        appt.with_user(self.dentist_user).action_start_consultation()
        self.assertEqual(appt.state, 'in_consultation')

    def test_dashboard_ignores_requested_doctor(self):
        Appt = self.env['dental.appointment'].with_user(self.dentist_user)
        res = Appt.get_dentist_dashboard_data(doctor_id=self.other_doctor.id)
        self.assertEqual(res['doctor_info']['id'], self.doctor.id)
        self.assertNotIn('doctors', res)
        self.assertNotIn('can_switch_doctor', res)


@tagged('post_install', '-at_install', 'dental_start_consultation')
class TestStartConsultationRights(TransactionCase):
    """Only dentists start consultations; a receptionist alone cannot (a receptionist who is also a dentist can)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        common = {'company_id': company.id, 'company_ids': [company.id]}
        cls.receptionist = new_test_user(cls.env, login='sc_reception', groups='base.group_user,dental_base.group_dental_receptionist', **common)
        cls.dentist_only = new_test_user(cls.env, login='sc_dentist_only', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.reception_dentist = new_test_user(cls.env, login='sc_reception_dentist',
                                              groups='base.group_user,dental_base.group_dental_receptionist,dental_base.group_dental_dentist', **common)
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Desk', 'dental_role': 'dentist', 'user_id': cls.reception_dentist.id,
                                                    'company_id': company.id})
        patient = cls.env['res.partner'].create({'name': 'SC Patient', 'is_dental_patient': True, 'phone': '9000000055'})
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
        cls.appt = cls.env['dental.appointment'].create({
            'patient_id': patient.id, 'doctor_id': cls.doctor.id, 'branch_id': company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
        })
        cls.appt.action_check_in()

    def test_receptionist_cannot_start(self):
        with self.assertRaises(AccessError):
            self.appt.with_user(self.receptionist).action_start_consultation()
        data = self.env['dental.appointment'].with_user(self.receptionist).get_reception_dashboard_data()
        self.assertFalse(data['can_start_consultation'])
        self.assertTrue(data['can_check_in'])
        board = self.env['dental.appointment'].with_user(self.receptionist).get_waiting_queue_board_data()
        self.assertFalse(board['can_start_consultation'])
        self.assertTrue(board['can_check_in'])

    def test_receptionist_who_is_dentist_can_start(self):
        data = self.env['dental.appointment'].with_user(self.reception_dentist).get_reception_dashboard_data()
        self.assertTrue(data['can_start_consultation'])
        self.appt.with_user(self.reception_dentist).action_start_consultation()
        self.assertEqual(self.appt.state, 'in_consultation')

    def test_doctor_cannot_check_in(self):
        """Only receptionists can check in patients; a pure doctor cannot."""
        patient = self.env['res.partner'].create({'name': 'Checkin Patient', 'is_dental_patient': True, 'phone': '9000000088'})
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=5)
        appt = self.env['dental.appointment'].create({
            'patient_id': patient.id, 'doctor_id': self.doctor.id, 'branch_id': self.env.company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
        })
        self.assertFalse(appt.with_user(self.dentist_only).is_receptionist)
        board = self.env['dental.appointment'].with_user(self.dentist_only).get_waiting_queue_board_data()
        self.assertFalse(board['can_check_in'])
        with self.assertRaises(AccessError):
            appt.with_user(self.dentist_only).action_check_in()

    def test_receptionist_can_check_in(self):
        """A receptionist can check in patients."""
        patient = self.env['res.partner'].create({'name': 'Checkin Patient 2', 'is_dental_patient': True, 'phone': '9000000089'})
        start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=6)
        appt = self.env['dental.appointment'].create({
            'patient_id': patient.id, 'doctor_id': self.doctor.id, 'branch_id': self.env.company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
        })
        self.assertTrue(appt.with_user(self.receptionist).is_receptionist)
        appt.with_user(self.receptionist).action_check_in()
        self.assertEqual(appt.state, 'checked_in')
