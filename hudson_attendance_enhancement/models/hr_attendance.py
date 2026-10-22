from odoo import api, fields, models

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'


    check_in_photo = fields.Image(string="Check In Photo", max_width=1024, max_height=1024)
    check_out_photo = fields.Image(string="Check Out Photo", max_width=1024, max_height=1024)

    # Work From Home (WFH) Fields
    is_wfh = fields.Boolean(string="Work From Home", default=False, index=True)
    wfh_status = fields.Selection([
        ('verified_home', 'Verified at Home'),
        ('offsite', 'Remote Offsite'),
        ('outside_radius', 'Outside Permitted Radius'),
    ], string="WFH Verification Status", default='verified_home', index=True)
    check_in_distance_from_home = fields.Float(string="Check-In Distance from Home (m)")
    check_out_distance_from_home = fields.Float(string="Check-Out Distance from Home (m)")
    wfh_offsite_reason = fields.Char(string="Offsite Reason / Justification")
    location_log_ids = fields.One2many('hr.employee.location.log', 'attendance_id', string="Location Logs")

    @api.model
    def get_attendance_gantt_data(self, domain=None, date_start=None, date_stop=None, scale='day'):
        """Fetch employee rows and attendance spans for Gantt view."""
        domain = domain or []
        user_tz = self.env.user.tz or 'UTC'

        # Fetch active employees
        emp_domain = [('active', '=', True)]
        # If domain filters on employee_id, extract it
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == 'employee_id':
                emp_domain.append(('id', leaf[1], leaf[2]))
            elif isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == 'department_id':
                emp_domain.append(('department_id', leaf[1], leaf[2]))

        employees = self.env['hr.employee'].search_read(
            emp_domain,
            ['id', 'name', 'department_id', 'resource_calendar_id'],
            order='name asc'
        )

        emp_ids = [e['id'] for e in employees]

        # Fetch calendars for daily planned hours
        cal_ids = list({e['resource_calendar_id'][0] for e in employees if e.get('resource_calendar_id')})
        calendars = {}
        if cal_ids:
            cal_records = self.env['resource.calendar'].sudo().search_read(
                [('id', 'in', cal_ids)],
                ['id', 'hours_per_day']
            )
            calendars = {c['id']: (c.get('hours_per_day') or 8.0) for c in cal_records}

        for emp in employees:
            cal_val = emp.get('resource_calendar_id')
            cal_id = cal_val[0] if isinstance(cal_val, (list, tuple)) and cal_val else None
            emp['daily_planned_hours'] = calendars.get(cal_id, 8.0) if cal_id else 8.0

        # Fetch attendances overlapping the time window
        att_domain = [('employee_id', 'in', emp_ids)]
        if date_start and date_stop:
            att_domain += [
                ('check_in', '<=', date_stop),
                '|',
                ('check_out', '>=', date_start),
                ('check_out', '=', False),
            ]
        # Include extra domain filters that apply to hr.attendance
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3:
                if leaf[0] not in ('employee_id', 'department_id'):
                    att_domain.append(leaf)

        attendances = self.search_read(
            att_domain,
            ['id', 'employee_id', 'check_in', 'check_out', 'worked_hours', 'overtime_hours', 'is_wfh', 'wfh_status'],
            order='check_in asc'
        )

        return {
            'employees': employees,
            'attendances': attendances,
            'user_tz': user_tz,
            'server_time': fields.Datetime.now().isoformat(),
        }

