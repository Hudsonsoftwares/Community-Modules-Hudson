from odoo import _, api, fields, models

from .dental_clinic_hours import DEFAULT_CLINIC_HOURS, WEEKDAYS


def _fmt_hour(value):
    hours, minutes = divmod(round(value * 60), 60)
    return '%02d:%02d' % (hours, minutes)


class ResCompany(models.Model):
    _inherit = 'res.company'

    is_dental_clinic = fields.Boolean(
        string='Is a Dental Clinic',
        default=True,
        help='Check if this company/branch operates as a dental clinic.',
    )
    clinic_manager_id = fields.Many2one(
        'hr.employee',
        string='Clinic Manager / Head Doctor',
    )
    # Legacy single-range timings, superseded by dental_clinic_hours_ids (kept so no data is lost)
    opening_time = fields.Float(string='Opening Time', default=9.0)
    closing_time = fields.Float(string='Closing Time', default=20.0)
    working_days = fields.Char(string='Working Days', default='Monday - Saturday')
    clinic_registration_number = fields.Char(string='Clinic Reg. No.')
    letterhead_header = fields.Html(string='Letterhead Header')
    letterhead_footer = fields.Html(string='Letterhead Footer')
    clinic_notes = fields.Text(string='Internal Notes')

    # ---- Clinic configuration (per clinic / branch) ----
    dental_clinic_hours_ids = fields.One2many('dental.clinic.hours', 'company_id', string='Clinic Hours')
    dental_hours_summary = fields.Text(string='Weekly Timings', compute='_compute_dental_hours_summary')
    dental_slot_duration = fields.Integer(
        string='Booking Slot (minutes)', default=0,
        help='Length of a booking slot for this clinic. 0 uses the global default from Clinic Settings.')
    dental_warn_outside_hours = fields.Boolean(
        string='Alert for Bookings Outside Clinic Hours', default=True,
        help='Show a warning when an appointment is booked outside the clinic hours. Booking is still allowed.')
    dental_branch_count = fields.Integer(
        string='Branches',
        compute='_compute_dental_branch_count',
    )

    def _compute_dental_branch_count(self):
        for company in self:
            company.dental_branch_count = self.search_count([('parent_id', '=', company.id)])

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('dental_branch_creation'):
            parent = self.env.company.root_id or self.env.company
            res.setdefault('parent_id', parent.id)
            res.setdefault('is_dental_clinic', True)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('dental_branch_creation'):
            parent = self.env.company.root_id or self.env.company
            for vals in vals_list:
                if not vals.get('parent_id'):
                    vals['parent_id'] = parent.id
                vals['is_dental_clinic'] = True
        return super().create(vals_list)

    @api.depends('dental_clinic_hours_ids.dayofweek', 'dental_clinic_hours_ids.hour_from', 'dental_clinic_hours_ids.hour_to')
    def _compute_dental_hours_summary(self):
        for company in self:
            lines = []
            for day, label in WEEKDAYS:
                sessions = company.dental_clinic_hours_ids.filtered(lambda h: h.dayofweek == day).sorted('hour_from')
                text = ', '.join('%s-%s' % (_fmt_hour(s.hour_from), _fmt_hour(s.hour_to)) for s in sessions) or _('Closed')
                lines.append('%s: %s' % (label, text))
            company.dental_hours_summary = '\n'.join(lines)

    # ---- Hours API used by booking and alerts ----
    def _dental_has_configured_hours(self):
        self.ensure_one()
        return bool(self.sudo().dental_clinic_hours_ids)

    def _dental_get_sessions(self, weekday):
        """[(period key, label, hour_from, hour_to)] for a weekday (0 = Monday), or None when the
        clinic has no hours configured at all (callers then use their own defaults)."""
        self.ensure_one()
        hours = self.sudo().dental_clinic_hours_ids
        if not hours:
            return None
        sessions = hours.filtered(lambda h: h.dayofweek == str(weekday)).sorted('hour_from')
        return [('s%d' % s.id, s.name or _('Session'), s.hour_from, s.hour_to) for s in sessions]

    def _dental_get_slot_duration(self):
        self.ensure_one()
        if self.dental_slot_duration > 0:
            return self.dental_slot_duration
        return self.env['ir.config_parameter'].sudo().get_int('dental_base.default_appointment_duration', 30) or 30

    def _dental_outside_hours_message(self, start_local, end_local):
        """Warning text when [start, end] (naive clinic-local datetimes) is not inside one session, else False."""
        self.ensure_one()
        if not self.dental_warn_outside_hours or not start_local or not end_local:
            return False
        sessions = self._dental_get_sessions(start_local.weekday())
        if sessions is None:
            return False
        day_label = dict(WEEKDAYS)[str(start_local.weekday())]
        start_h = start_local.hour + start_local.minute / 60.0
        end_h = (end_local.hour + end_local.minute / 60.0) if end_local.date() == start_local.date() else 24.0
        if any(h_from <= start_h and end_h <= h_to for _p, _l, h_from, h_to in sessions):
            return False
        timings = ', '.join('%s-%s' % (_fmt_hour(f), _fmt_hour(t)) for _p, _l, f, t in sessions)
        if not timings:
            return _("%(clinic)s is closed on %(day)s. You can still keep this appointment.",
                     clinic=self.name, day=day_label)
        return _("%(time)s is outside %(clinic)s hours on %(day)s (%(timings)s). You can still keep this appointment.",
                 time=start_local.strftime('%I:%M %p').lstrip('0'), clinic=self.name, day=day_label, timings=timings)

    def action_dental_load_default_hours(self):
        """Fill in standard timings (Mon-Sat 09:00-13:00 and 14:00-18:00, Sun 10:00-14:00)."""
        for company in self:
            if company.dental_clinic_hours_ids:
                continue
            self.env['dental.clinic.hours'].sudo().create([{
                'company_id': company.id, 'dayofweek': day, 'name': label, 'hour_from': h_from, 'hour_to': h_to,
            } for day, label, h_from, h_to in DEFAULT_CLINIC_HOURS])
        return True

    @api.model
    def _dental_install_default_hours(self):
        """On install/upgrade: give every clinic without hours the standard timings, so the
        configuration starts from what booking used before (hours were fixed in code)."""
        self.sudo().search([('is_dental_clinic', '=', True)]).action_dental_load_default_hours()

    @api.model
    def action_open_dental_configuration(self):
        """Clinic Configuration of the clinic currently selected in the company switcher."""
        return {
            'name': _('Clinic Configuration'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.company',
            'res_id': self.env.company.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dental_base.view_res_company_dental_configuration').id, 'form')],
            'target': 'current',
            'context': {'dental_clinic_configuration': True},
        }

    def action_view_dental_branches(self):
        """Clinic Branches under this clinic/company."""
        self.ensure_one()
        return {
            'name': _('%(clinic)s - Branches', clinic=self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'res.company',
            'view_mode': 'list,kanban,form',
            'domain': [('parent_id', '=', self.id)],
            'context': {
                'dental_branch_creation': True,
                'default_parent_id': self.id,
                'default_is_dental_clinic': True,
            },
            'views': [
                (self.env.ref('dental_base.view_dental_clinic_branch_tree').id, 'list'),
                (self.env.ref('dental_base.view_dental_clinic_branch_kanban').id, 'kanban'),
                (self.env.ref('dental_base.view_dental_clinic_branch_form').id, 'form'),
            ],
            'help': _(
                '<p class="o_view_nocontent_smiling_face">Create a new clinic branch</p>'
                '<p>Add branches under this clinic with branch-specific hours, doctor assignments, and operational details.</p>'
            ),
        }
