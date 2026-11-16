from odoo import models, fields, api, _
from odoo.exceptions import UserError


def dental_billing_summary(invoices, has_billable):
    """Shared billing status for cases and appointments: (state, invoice_count, amount_due, has_draft)."""
    invoices = invoices.filtered(lambda m: m.move_type == 'out_invoice' and m.state != 'cancel')
    posted = invoices.filtered(lambda m: m.state == 'posted')
    drafts = invoices.filtered(lambda m: m.state == 'draft')
    amount_due = sum(posted.mapped('amount_residual'))
    if has_billable:
        state = 'to_invoice'
    elif drafts:
        state = 'draft'
    elif amount_due:
        state = 'due'
    elif posted:
        state = 'paid'
    else:
        state = 'nothing'
    return state, len(invoices), amount_due, bool(drafts)


class AccountMove(models.Model):
    _inherit = 'account.move'

    dental_case_id = fields.Many2one(
        'dental.case',
        string='Dental Case',
        index=True,
        check_company=True,
        help='Linked dental consultation case'
    )

    @api.model
    def _dental_create_or_extend_invoice(self, partner, company, line_vals, case=False, origin=False):
        """One invoice per visit: extend the visit's draft invoice if any, otherwise create one.

        Returns (invoice, extended).
        """
        if case:
            draft = case.sudo().invoice_ids.filtered(lambda m: m.move_type == 'out_invoice' and m.state == 'draft')[:1]
            if draft:
                draft = draft.with_env(self.env)
                draft.write({'invoice_line_ids': [(0, 0, vals) for vals in line_vals]})
                return draft, True
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "No Sales journal is configured for %s. Set the Fiscal Localization in "
                "Invoicing / Accounting > Configuration > Settings before billing patients.", company.name))
        invoice = self.with_company(company).create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'company_id': company.id,
            'journal_id': journal.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': origin or (case.name if case else False),
            'dental_case_id': case.id if case else False,
            'invoice_line_ids': [(0, 0, vals) for vals in line_vals],
        })
        return invoice, False

    def action_view_dental_case(self):
        self.ensure_one()
        return {
            'name': _('Dental Case'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.case',
            'view_mode': 'form',
            'res_id': self.dental_case_id.id,
        }


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Source records billed by this line; used to never bill the same visit or session twice
    dental_appointment_id = fields.Many2one('dental.appointment', string='Billed Appointment', index=True, copy=False, check_company=True)
    dental_session_id = fields.Many2one('dental.treatment.session', string='Billed Treatment Session', index=True, copy=False, check_company=True)
