# Copyright 2026 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models


def _default_directory(env):
    directory_id = env.context.get("default_directory_id")
    return env["dms.directory"].browse(directory_id).exists() if directory_id else env["dms.directory"]


class DmsFileRequestWizard(models.TransientModel):
    _name = "dms.file.request.wizard"
    _description = "Request a file"

    name = fields.Char(string="Document Name", required=True)
    partner_id = fields.Many2one("res.partner", string="Request To", required=True)
    directory_id = fields.Many2one(
        "dms.directory",
        string="Folder",
        required=True,
        default=lambda self: _default_directory(self.env),
    )
    tag_ids = fields.Many2many("dms.tag", string="Tags")
    activity_date_deadline_range = fields.Integer(string="Due Date In", default=30)
    activity_date_deadline_range_type = fields.Selection(
        [("days", "Days"), ("weeks", "Weeks"), ("months", "Months")],
        string="Due type",
        default="days",
        required=True,
    )
    date_deadline = fields.Date(compute="_compute_date_deadline")
    message = fields.Text(string="Message")

    @api.depends("activity_date_deadline_range", "activity_date_deadline_range_type")
    def _compute_date_deadline(self):
        today = fields.Date.context_today(self)
        for wizard in self:
            count = wizard.activity_date_deadline_range or 0
            unit = wizard.activity_date_deadline_range_type or "days"
            wizard.date_deadline = today + relativedelta(**{unit: count}) if count > 0 else False

    def action_request(self):
        self.ensure_one()
        self.env["dms.file"].dms_create_request({
            "name": self.name,
            "directory_id": self.directory_id.id,
            "partner_id": self.partner_id.id,
            "date_deadline": self.date_deadline,
            "message": self.message,
            "tag_ids": self.tag_ids.ids,
        })
        return {"type": "ir.actions.act_window_close"}


class DmsFileUrlWizard(models.TransientModel):
    _name = "dms.file.url.wizard"
    _description = "Add a link"

    url = fields.Char(string="URL", required=True)
    name = fields.Char(string="Name")
    directory_id = fields.Many2one(
        "dms.directory",
        string="Folder",
        required=True,
        default=lambda self: _default_directory(self.env),
    )

    def action_add(self):
        self.ensure_one()
        self.env["dms.file"].dms_create_link(self.directory_id.id, self.url, self.name)
        return {"type": "ir.actions.act_window_close"}
