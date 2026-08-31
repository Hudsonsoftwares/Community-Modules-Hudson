from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
    hudson_deferred_start_date = fields.Date(string='Deferred Start Date')
    hudson_deferred_end_date = fields.Date(string='Deferred End Date')

    @api.constrains('hudson_deferred_start_date', 'hudson_deferred_end_date')
    def _check_hudson_deferred_dates(self):
        for line in self:
            if line.hudson_deferred_start_date and line.hudson_deferred_end_date:
                if line.hudson_deferred_start_date > line.hudson_deferred_end_date:
                    raise ValidationError("Deferred Start Date cannot be after Deferred End Date.")

    def action_hudson_manual_reconcile(self):
        """Action for the manual Reconcile button on the custom Reconcile view."""
        return self.reconcile()
