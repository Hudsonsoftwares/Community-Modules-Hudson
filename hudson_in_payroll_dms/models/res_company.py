# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    hds_dms_store_tax_proofs = fields.Boolean(
        string="Store Tax Proofs in Documents",
        default=True,
        help="Copy the proof files of submitted tax declarations into the employee's Documents folder "
             "(Payroll / <tax year> / Tax Proofs).",
    )
