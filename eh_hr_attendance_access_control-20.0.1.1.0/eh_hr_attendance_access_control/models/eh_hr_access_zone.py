# -*- encoding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EhHrAccessZone(models.Model):
    _name = 'eh.hr.access.zone'
    _description = 'Access Zone'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Zone name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, help="URL-safe identifier. Letters, digits, dashes and underscores only.")
    site_ids = fields.Many2many(
        'eh.hr.kiosk.site',
        'eh_hr_access_zone_site_rel',
        'zone_id',
        'site_id',
        string='Sites that grant access here',
        help="Kiosks at any of these sites can trigger an unlock for this zone, subject to per-employee permissions.",
    )
    reader_ids = fields.One2many('eh.hr.access.reader', 'zone_id', string='Readers')
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    notes = fields.Text(string='Notes')

    _unique_code_per_company = models.Constraint(
        'UNIQUE(code, company_id)',
        'Zone code must be unique per company.')

    @api.constrains('code')
    def _check_code(self):
        for record in self:
            if not record.code or not re.match(r'^[A-Za-z0-9_-]+$', record.code):
                raise ValidationError(_("Zone code must be a non-empty string of letters, digits, dashes and underscores."))
