from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestEmployeePrivateFields(HttpCase):
    """Non-HR users must be able to read employees and check in (incl. WFH)
    although the module's hr.employee fields are HR-only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'enable_work_from_home': True, 'attendance_radius_punching': False})
        cls.user = new_test_user(cls.env, 'wfh_worker', groups='base.group_user')
        cls.hr_user = new_test_user(cls.env, 'hr_officer', groups='base.group_user,hr.group_hr_user')
        cls.colleague = cls.env['hr.employee'].create({'name': 'Colleague', 'is_wfh_employee': True,
                                                       'home_latitude': 10.0, 'home_longitude': 76.0})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'WFH Worker', 'user_id': cls.user.id, 'is_wfh_employee': True, 'wfh_type': 'full_time',
            'home_latitude': 9.9312, 'home_longitude': 76.2673, 'custom_home_radius': 500,
        })

    def test_non_hr_user_reads_employees(self):
        Employee = self.env['hr.employee'].with_user(self.user)
        self.env.invalidate_all()  # force a real fetch (setUpClass values are cached)
        # Used to raise "The fields ... are not available for employee public profiles"
        self.assertEqual(Employee.browse(self.colleague.id).name, 'Colleague')
        self.env.invalidate_all()
        Employee.browse(self.colleague.id).read(['name', 'department_id'])
        self.env.invalidate_all()
        self.assertEqual(Employee.search([('id', '=', self.colleague.id)]).name, 'Colleague')
        # ... but the WFH / home location data stays private
        with self.assertRaises(AccessError):
            Employee.browse(self.colleague.id).read(['home_latitude'])
        # HR officers still see it
        self.assertEqual(self.colleague.with_user(self.hr_user).home_latitude, 10.0)

    def test_non_hr_user_wfh_check_in_and_heartbeat(self):
        self.env.invalidate_all()
        self.authenticate('wfh_worker', 'wfh_worker')
        res = self.make_jsonrpc_request('/hr_attendance/systray_check_in_out',
                                        {'latitude': 9.9313, 'longitude': 76.2674})
        self.assertTrue(res.get('wfh_enabled'))
        attendance = self.env['hr.attendance'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(attendance), 1)
        self.assertTrue(attendance.is_wfh)
        self.assertEqual(attendance.wfh_status, 'verified_home')

        res = self.make_jsonrpc_request('/hudson_attendance/wfh_heartbeat',
                                        {'latitude': 9.9400, 'longitude': 76.2700})
        self.assertEqual(res['status'], 'success')
        self.employee.invalidate_recordset()
        self.assertAlmostEqual(self.employee.last_known_latitude, 9.94, places=3)
