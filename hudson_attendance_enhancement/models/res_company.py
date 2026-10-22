from odoo import models, fields, api

class ResCompany(models.Model):
    _inherit = 'res.company'

    attendance_radius_punching = fields.Boolean(string="Enable Radius Punching", default=False)
    attendance_location_ids = fields.One2many('hr.attendance.location', 'company_id', string="Allowed Locations")

    # Work From Home (WFH) Configuration
    enable_work_from_home = fields.Boolean(string="Enable Work From Home", default=False)
    wfh_tracking_interval = fields.Selection([
        ('5', 'Every 5 Minutes'),
        ('10', 'Every 10 Minutes'),
        ('15', 'Every 15 Minutes'),
        ('30', 'Every 30 Minutes'),
        ('60', 'Every 60 Minutes'),
    ], string="Live Location Ping Interval", default='10')
    wfh_enforce_home_radius = fields.Boolean(
        string="Enforce Home Radius Punching",
        default=False,
        help="If enabled, WFH employees must be within their configured home radius to check in.",
    )
    wfh_home_radius = fields.Float(string="Allowed Home Radius (meters)", default=150.0)
    wfh_require_photo = fields.Boolean(string="Require Photo Verification for WFH", default=True)
    wfh_allow_offsite_with_reason = fields.Boolean(
        string="Allow Offsite Remote Work with Reason",
        default=True,
        help="If employee is outside their home radius, allow check-in if they provide an offsite justification reason.",
    )

    def _ensure_wfh_columns(self):
        columns = [
            ('enable_work_from_home', 'BOOLEAN DEFAULT FALSE'),
            ('wfh_tracking_interval', "VARCHAR DEFAULT '10'"),
            ('wfh_enforce_home_radius', 'BOOLEAN DEFAULT FALSE'),
            ('wfh_home_radius', 'DOUBLE PRECISION DEFAULT 150.0'),
            ('wfh_require_photo', 'BOOLEAN DEFAULT TRUE'),
            ('wfh_allow_offsite_with_reason', 'BOOLEAN DEFAULT TRUE'),
        ]
        try:
            for col, col_def in columns:
                self.env.cr.execute(f"ALTER TABLE res_company ADD COLUMN IF NOT EXISTS {col} {col_def};")
            self.env.registry._hds_wfh_company_cols_synced = True
        except Exception:
            pass

    def fetch(self, field_names=None):
        if not getattr(self.env.registry, '_hds_wfh_company_cols_synced', False):
            self._ensure_wfh_columns()
        return super().fetch(field_names=field_names)

    @api.onchange('attendance_radius_punching', 'enable_work_from_home')
    def _onchange_attendance_tracking_flags(self):
        if self.attendance_radius_punching or self.enable_work_from_home:
            self.attendance_device_tracking = True

    def write(self, vals):
        if vals.get('attendance_radius_punching') or vals.get('enable_work_from_home'):
            vals['attendance_device_tracking'] = True
        return super().write(vals)
