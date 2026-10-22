# -*- encoding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EhHrAccessPermission(models.Model):
    _name = 'eh.hr.access.permission'
    _description = 'Access Permission'
    _order = 'employee_id, zone_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    zone_id = fields.Many2one(
        'eh.hr.access.zone',
        string='Zone',
        required=True,
        ondelete='cascade',
        index=True,
    )
    valid_from = fields.Date(string='Valid from')
    valid_to = fields.Date(string='Valid to')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='zone_id.company_id',
        store=True,
        index=True,
    )

    _unique_employee_zone = models.Constraint(
        'UNIQUE(employee_id, zone_id)',
        'An employee can have only one permission row per zone.')

    @api.constrains('valid_from', 'valid_to')
    def _check_dates(self):
        for record in self:
            if record.valid_from and record.valid_to and record.valid_to < record.valid_from:
                raise ValidationError(_("Valid to cannot be before valid from."))

    def is_currently_valid(self):
        """True if active and within the configured window."""
        self.ensure_one()
        if not self.active:
            return False
        today = fields.Date.context_today(self)
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_to and today > self.valid_to:
            return False
        return True
