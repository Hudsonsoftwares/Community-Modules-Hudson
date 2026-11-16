from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    attendance_radius_punching = fields.Boolean(
        string="Enable Radius Punching",
        related='company_id.attendance_radius_punching',
        readonly=False,
    )

    attendance_capture_check_out = fields.Boolean(
        related='company_id.attendance_capture_check_out',
        readonly=False,
    )

    # Work From Home (WFH) Settings
    enable_work_from_home = fields.Boolean(
        string="Enable Work From Home Management",
        related='company_id.enable_work_from_home',
        readonly=False,
    )
    wfh_tracking_interval = fields.Selection(
        string="Live Location Ping Interval",
        related='company_id.wfh_tracking_interval',
        readonly=False,
    )
    wfh_enforce_home_radius = fields.Boolean(
        string="Enforce Home Radius Punching",
        related='company_id.wfh_enforce_home_radius',
        readonly=False,
    )
    wfh_home_radius = fields.Float(
        string="Allowed Home Radius (meters)",
        related='company_id.wfh_home_radius',
        readonly=False,
    )
    wfh_require_photo = fields.Boolean(
        string="Require Photo Verification for WFH",
        related='company_id.wfh_require_photo',
        readonly=False,
    )
    wfh_allow_offsite_with_reason = fields.Boolean(
        string="Allow Offsite Remote Work with Reason",
        related='company_id.wfh_allow_offsite_with_reason',
        readonly=False,
    )
