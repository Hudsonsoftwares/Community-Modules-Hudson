# -*- coding: utf-8 -*-
from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hds_dms_store_tax_proofs = fields.Boolean(
        related='company_id.hds_dms_store_tax_proofs',
        readonly=False,
    )

    def action_hds_dms_store_existing_tax_proofs(self):
        """Copy the proofs of the company's submitted declarations that are not in Documents yet."""
        self.ensure_one()
        declarations = self.env['tds.employee.declaration'].sudo().search([
            ('company_id', '=', self.company_id.id),
        ])
        declarations._hds_dms_sync_proofs()
        stored = self.env['hds.in.tax.proof.document'].sudo().search_count([
            ('declaration_id', 'in', declarations.ids), ('dms_file_id.is_trashed', '=', False),
        ])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Store tax proofs in Documents"),
                'message': _("%(count)s tax proof file(s) are now in the employee folders.", count=stored),
                'type': 'success',
                'sticky': False,
            },
        }
