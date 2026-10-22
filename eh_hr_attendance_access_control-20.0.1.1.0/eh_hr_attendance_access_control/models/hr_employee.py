# -*- encoding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    eh_access_permission_ids = fields.One2many(
        'eh.hr.access.permission',
        'employee_id',
        string='Access permissions',
    )
