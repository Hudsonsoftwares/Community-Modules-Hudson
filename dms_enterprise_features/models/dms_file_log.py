# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

class DMSFileLog(models.Model):
    _name = 'dms.file.log'
    _description = 'Document Logs'
    _order = 'date desc'

    name = fields.Char(string='Document Name', required=True)
    file_id = fields.Many2one('dms.file', string='Document', ondelete='set null')
    action = fields.Selection([
        ('create', 'Created'),
        ('edit', 'Edited'),
        ('delete', 'Deleted')
    ], string='Action', required=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    details = fields.Text(string='Details')
