# -*- coding: utf-8 -*-
from datetime import datetime, time
import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError


class DentalPaymentSummary(models.Model):
    _name = 'dental.payment.summary'
    _description = 'End of Day Payment Summary'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Summary Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New')
    )
    date = fields.Date(
        string='Summary Date',
        required=True,
        default=fields.Date.context_today,
        readonly=True,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Clinic Branch',
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Cashier / Receptionist',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft / In Progress'),
        ('closed', 'Reconciled & Closed'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)

    closing_user_id = fields.Many2one(
        'res.users',
        string='Closed By',
        readonly=True,
        copy=False,
    )
    closing_date = fields.Datetime(
        string='Closing Timestamp',
        readonly=True,
        copy=False,
    )
    note = fields.Text(
        string='Discrepancy Notes / Remarks',
        tracking=True,
        help='Explain any cash drawer discrepancy or special settlement notes.',
    )

    # ---------------------------------------------------------
    # Aggregated Financial Metrics
    # ---------------------------------------------------------
    total_invoiced = fields.Monetary(
        string='Total Invoiced Today',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total amount of invoices confirmed/posted today in this clinic branch.',
    )
    total_collected = fields.Monetary(
        string='Total Collections',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total inbound customer payments received today.',
    )
    total_refunded = fields.Monetary(
        string='Total Refunds',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total outbound customer refunds processed today.',
    )
    net_collected = fields.Monetary(
        string='Net Collected Today',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Gross Collections minus Refunds.',
    )
    total_cash_expected = fields.Monetary(
        string='Expected Cash in Drawer',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='System expected cash collections minus cash refunds.',
    )
    total_cash_counted = fields.Monetary(
        string='Counted Cash',
        compute='_compute_totals',
        inverse='_set_total_cash_counted',
        store=True,
        currency_field='currency_id',
        help='Physical cash counted in the cash drawer at end of day.',
    )
    cash_difference = fields.Monetary(
        string='Cash Discrepancy',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Difference between physical counted cash and system expected cash (Counted - Expected).',
    )
    total_bank_collected = fields.Monetary(
        string='Electronic / Card / UPI',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total payments collected via Card, POS, Bank, UPI, or Online journals.',
    )
    payment_count = fields.Integer(
        string='Transactions Count',
        compute='_compute_totals',
        store=True,
    )
    invoices_count = fields.Integer(
        string='Invoices Issued Today',
        compute='_compute_totals',
        store=True,
    )
    invoices_settled_count = fields.Integer(
        string='Invoices Settled Today',
        compute='_compute_totals',
        store=True,
    )
    pending_invoices_amount = fields.Monetary(
        string='Pending Due from Today',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )

    # ---------------------------------------------------------
    # Relational Breakdown Lines
    # ---------------------------------------------------------
    journal_line_ids = fields.One2many(
        'dental.payment.summary.journal.line',
        'summary_id',
        string='Payment Method Breakdown',
        copy=True,
    )
    line_ids = fields.One2many(
        'dental.payment.summary.line',
        'summary_id',
        string='Payment Transactions',
        copy=True,
    )
    denomination_ids = fields.One2many(
        'dental.payment.summary.denomination',
        'summary_id',
        string='Cash Denominations',
        copy=True,
    )

    # ---------------------------------------------------------
    # Constraints
    # ---------------------------------------------------------
    @api.constrains('date', 'company_id', 'user_id', 'state')
    def _check_unique_summary(self):
        for rec in self:
            if rec.state != 'cancel':
                dup = self.search([
                    ('id', '!=', rec.id),
                    ('date', '=', rec.date),
                    ('company_id', '=', rec.company_id.id),
                    ('user_id', '=', rec.user_id.id),
                    ('state', '!=', 'cancel'),
                ], limit=1)
                if dup:
                    raise ValidationError(_(
                        "An End of Day Payment Summary (%s) already exists for %s on %s. "
                        "Please use or review the existing record.",
                        dup.name, rec.user_id.name, rec.date
                    ))

    # ---------------------------------------------------------
    # CRUD & Defaults
    # ---------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.payment.summary') or _('New')
        records = super().create(vals_list)
        for rec in records:
            if not rec.line_ids and not rec.journal_line_ids:
                rec.action_fetch_payments()
        return records

    # ---------------------------------------------------------
    # Computations
    # ---------------------------------------------------------
    @api.depends(
        'line_ids',
        'line_ids.amount',
        'line_ids.payment_type',
        'journal_line_ids',
        'journal_line_ids.amount_collected',
        'journal_line_ids.amount_refunded',
        'journal_line_ids.amount_expected',
        'journal_line_ids.amount_counted',
        'denomination_ids',
        'denomination_ids.total_amount',
        'date',
        'company_id',
    )
    def _compute_totals(self):
        for rec in self:
            inbound_lines = rec.line_ids.filtered(lambda l: l.payment_type == 'inbound')
            outbound_lines = rec.line_ids.filtered(lambda l: l.payment_type == 'outbound')

            rec.total_collected = sum(inbound_lines.mapped('amount'))
            rec.total_refunded = sum(outbound_lines.mapped('amount'))
            rec.net_collected = rec.total_collected - rec.total_refunded
            rec.payment_count = len(rec.line_ids)

            cash_jlines = rec.journal_line_ids.filtered(lambda j: j.journal_type == 'cash')
            non_cash_jlines = rec.journal_line_ids.filtered(lambda j: j.journal_type != 'cash')

            rec.total_cash_expected = sum(cash_jlines.mapped('amount_expected'))
            rec.total_bank_collected = sum(non_cash_jlines.mapped('amount_expected'))

            # Counted cash logic:
            denom_total = sum(rec.denomination_ids.mapped('total_amount'))
            if denom_total > 0:
                rec.total_cash_counted = denom_total
            else:
                rec.total_cash_counted = sum(cash_jlines.mapped('amount_counted'))

            rec.cash_difference = rec.total_cash_counted - rec.total_cash_expected

            # Compute invoice statistics for the target day and branch
            if rec.date and rec.company_id:
                invoices = self.env['account.move'].search([
                    ('company_id', '=', rec.company_id.id),
                    ('invoice_date', '=', rec.date),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                ])
                rec.invoices_count = len(invoices)
                rec.total_invoiced = sum(invoices.mapped('amount_total'))
                rec.invoices_settled_count = len(invoices.filtered(lambda m: m.payment_state in ('paid', 'in_payment')))
                rec.pending_invoices_amount = sum(invoices.mapped('amount_residual'))
            else:
                rec.invoices_count = 0
                rec.total_invoiced = 0.0
                rec.invoices_settled_count = 0
                rec.pending_invoices_amount = 0.0

    def _set_total_cash_counted(self):
        for rec in self:
            cash_jlines = rec.journal_line_ids.filtered(lambda j: j.journal_type == 'cash')
            if cash_jlines:
                cash_jlines[0].amount_counted = rec.total_cash_counted

    @api.onchange('denomination_ids')
    def _onchange_denomination_ids(self):
        denom_total = sum(self.denomination_ids.mapped('total_amount'))
        if denom_total > 0:
            cash_jlines = self.journal_line_ids.filtered(lambda j: j.journal_type == 'cash')
            if cash_jlines:
                cash_jlines[0].amount_counted = denom_total

    # ---------------------------------------------------------
    # Core Business Logic: Fetching Daily Payments & Receipts
    # ---------------------------------------------------------
    def action_fetch_payments(self):
        """Fetch all posted patient customer payments, receipts, and invoices for the selected day."""
        self.ensure_one()
        if self.state == 'closed':
            raise UserError(_("Cannot refresh transactions on a closed payment summary."))

        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')

        # 1. Search candidate posted payments on summary date for this company
        payments = self.env['account.payment'].search([
            ('company_id', '=', self.company_id.id),
            ('date', '=', self.date),
            ('state', '=', 'posted'),
        ], order='create_date asc, id asc')

        # Filter strictly customer inbound/refund payments, dental patients, or reconciled with clinic invoices
        filtered_payments = []
        for p in payments:
            is_customer = not p.partner_type or p.partner_type == 'customer'
            is_patient = bool(p.partner_id and getattr(p.partner_id, 'is_dental_patient', False))
            reconciled_invs = getattr(p, 'reconciled_invoice_ids', False) or getattr(p, 'reconciled_invoices', False) or self.env['account.move']
            is_clinic_inv = any(
                inv.dental_case_id or inv.invoice_line_ids.dental_appointment_id
                for inv in reconciled_invs
            )
            if is_customer or is_patient or is_clinic_inv:
                filtered_payments.append(p)

        # 2. Build Transaction Lines
        new_lines_vals = []
        for p in filtered_payments:
            reconciled_invs = getattr(p, 'reconciled_invoice_ids', False) or getattr(p, 'reconciled_invoices', False) or self.env['account.move']

            # Find treating doctor and invoice origins
            doctor_id = False
            origin_parts = []
            for inv in reconciled_invs:
                if inv.name:
                    origin_parts.append(inv.name)
                if not doctor_id and inv.dental_case_id and inv.dental_case_id.doctor_id:
                    doctor_id = inv.dental_case_id.doctor_id.id
                if not doctor_id:
                    appt = inv.invoice_line_ids.mapped('dental_appointment_id')[:1]
                    if appt and appt.doctor_id:
                        doctor_id = appt.doctor_id.id

            # Fallback doctor check if not reconciled: search today's appointment for this patient
            if not doctor_id and p.partner_id:
                today_appt = self.env['dental.appointment'].search([
                    ('patient_id', '=', p.partner_id.id),
                    ('branch_id', '=', self.company_id.id),
                ], order='date_start desc', limit=1)
                if today_appt:
                    doctor_id = today_appt.doctor_id.id if today_appt.doctor_id else False
                    if not origin_parts:
                        origin_parts.append(today_appt.name)

            # Format local time
            time_display = ""
            if p.create_date:
                try:
                    utc_dt = pytz.utc.localize(p.create_date)
                    time_display = utc_dt.astimezone(user_tz).strftime('%I:%M %p')
                except Exception:
                    time_display = p.create_date.strftime('%H:%M')

            communication = getattr(p, 'memo', False) or getattr(p, 'ref', False) or p.name or ''
            invoice_origin = ", ".join(origin_parts) if origin_parts else communication

            new_lines_vals.append({
                'payment_id': p.id,
                'payment_name': p.name,
                'payment_date': p.date,
                'payment_time': time_display,
                'partner_id': p.partner_id.id if p.partner_id else False,
                'patient_identifier': getattr(p.partner_id, 'dental_patient_id', '') or '',
                'journal_id': p.journal_id.id,
                'payment_type': p.payment_type or 'inbound',
                'amount': p.amount,
                'invoice_origin': invoice_origin,
                'dentist_id': doctor_id,
                'cashier_id': p.create_uid.id if p.create_uid else self.env.user.id,
                'communication': communication,
            })

        # 3. Build Payment Methods Breakdown (Journal lines)
        journals_used = {p.journal_id for p in filtered_payments}
        # Ensure company's active cash journals are always included so cash drawer can be reconciled
        cash_journals = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('type', '=', 'cash'),
        ])
        all_journals = list(journals_used.union(set(cash_journals)))
        all_journals.sort(key=lambda j: (0 if j.type == 'cash' else 1, j.name))

        # Preserve any previously manually entered amount_counted
        prev_counted = {
            jl.journal_id.id: jl.amount_counted
            for jl in self.journal_line_ids
        }

        new_journal_vals = []
        for j in all_journals:
            j_payments = [p for p in filtered_payments if p.journal_id.id == j.id]
            collected = sum(p.amount for p in j_payments if p.payment_type == 'inbound')
            refunded = sum(p.amount for p in j_payments if p.payment_type == 'outbound')
            expected = collected - refunded

            # Default counted amount:
            if j.id in prev_counted and prev_counted[j.id] > 0:
                counted = prev_counted[j.id]
            elif j.type != 'cash':
                # Electronic/POS/UPI payments match expected settlement by default
                counted = expected
            else:
                counted = 0.0

            new_journal_vals.append({
                'journal_id': j.id,
                'transaction_count': len(j_payments),
                'amount_collected': collected,
                'amount_refunded': refunded,
                'amount_counted': counted,
            })

        # 4. Initialize currency denominations if missing
        new_denom_vals = []
        if not self.denomination_ids:
            standard_denominations = [2000.0, 500.0, 200.0, 100.0, 50.0, 20.0, 10.0, 5.0, 2.0, 1.0]
            for val in standard_denominations:
                new_denom_vals.append({
                    'denomination_value': val,
                    'count': 0,
                })

        # Update lines on summary
        write_vals = {
            'line_ids': [(5, 0, 0)] + [(0, 0, v) for v in new_lines_vals],
            'journal_line_ids': [(5, 0, 0)] + [(0, 0, v) for v in new_journal_vals],
        }
        if new_denom_vals:
            write_vals['denomination_ids'] = [(0, 0, v) for v in new_denom_vals]

        self.write(write_vals)
        return True

    # ---------------------------------------------------------
    # Actions & Workflow
    # ---------------------------------------------------------
    def action_close(self):
        """Finalize and close the daily payment summary after receptionist verification."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only draft payment summaries can be closed."))

        if not self.line_ids and not self.journal_line_ids:
            self.action_fetch_payments()

        # Enforce note explanation if cash discrepancy exists
        if self.cash_difference != 0 and not (self.note and self.note.strip()):
            curr = self.currency_id.symbol or ''
            raise ValidationError(_(
                "There is a cash difference of %(curr)s %(diff).2f between expected and counted cash. "
                "Please provide an explanation in the 'Discrepancy Notes / Remarks' field before closing.",
                curr=curr,
                diff=self.cash_difference,
            ))

        self.write({
            'state': 'closed',
            'closing_user_id': self.env.user.id,
            'closing_date': fields.Datetime.now(),
        })

        curr_sym = self.currency_id.symbol or ''
        self.message_post(body=_(
            "<strong>End of Day Payment Summary Reconciled &amp; Closed</strong><br/>"
            "• <strong>Closed By:</strong> %(user)s<br/>"
            "• <strong>Net Collections:</strong> %(curr)s %(col).2f<br/>"
            "• <strong>Expected Cash:</strong> %(curr)s %(exp).2f<br/>"
            "• <strong>Counted Cash:</strong> %(curr)s %(cnt).2f<br/>"
            "• <strong>Cash Difference:</strong> %(curr)s %(diff).2f<br/>"
            "• <strong>Transactions:</strong> %(count)s",
            user=self.env.user.name,
            curr=curr_sym,
            col=self.net_collected,
            exp=self.total_cash_expected,
            cnt=self.total_cash_counted,
            diff=self.cash_difference,
            count=self.payment_count,
        ))
        return True

    def action_reopen(self):
        """Allow Clinic Managers and Administrators to reopen a closed day summary."""
        self.ensure_one()
        is_manager = self.env.user.has_group('dental_base.group_dental_manager')
        is_admin = self.env.user.has_group('dental_base.group_dental_admin')
        if not (is_manager or is_admin):
            raise AccessError(_("Only clinic managers or administrators can reopen a closed payment summary."))

        self.write({
            'state': 'draft',
            'closing_user_id': False,
            'closing_date': False,
        })
        self.message_post(body=_("Payment summary reopened to Draft by %s", self.env.user.name))
        return True

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'closed':
            is_manager = self.env.user.has_group('dental_base.group_dental_manager')
            is_admin = self.env.user.has_group('dental_base.group_dental_admin')
            if not (is_manager or is_admin):
                raise AccessError(_("Only clinic managers can cancel a closed payment summary."))
        self.write({'state': 'cancel'})
        self.message_post(body=_("Payment summary cancelled by %s", self.env.user.name))
        return True

    def action_print_pdf(self):
        """Generate official PDF Day Close Summary Report."""
        self.ensure_one()
        return self.env.ref('dental_core.action_report_dental_payment_summary').report_action(self)

    def action_view_payments(self):
        self.ensure_one()
        payment_ids = self.line_ids.mapped('payment_id').ids
        return {
            'name': _('Payments Recorded (%s)', self.date),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', payment_ids)],
            'context': {'default_date': self.date, 'default_company_id': self.company_id.id},
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'name': _('Invoices Today (%s)', self.date),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [
                ('company_id', '=', self.company_id.id),
                ('invoice_date', '=', self.date),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
            ],
            'context': {'default_move_type': 'out_invoice'},
        }

    # ---------------------------------------------------------
    # Reception Desk Quick Action: Open or Create Today
    # ---------------------------------------------------------
    @api.model
    def action_open_or_create_today(self):
        """Front desk shortcut: Opens today's summary if existing, or creates and loads it instantly."""
        today = fields.Date.context_today(self)
        company = self.env.company
        user = self.env.user

        summary = self.search([
            ('date', '=', today),
            ('company_id', '=', company.id),
            ('user_id', '=', user.id),
            ('state', '!=', 'cancel'),
        ], limit=1)

        if not summary:
            # Fallback: check if any open summary exists for this clinic branch today
            summary = self.search([
                ('date', '=', today),
                ('company_id', '=', company.id),
                ('state', '=', 'draft'),
            ], limit=1)

        if not summary:
            summary = self.create({
                'date': today,
                'company_id': company.id,
                'user_id': user.id,
            })
            summary.action_fetch_payments()

        return {
            'name': _('End of Day Payment Summary'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.payment.summary',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_id': summary.id,
            'target': 'current',
        }


class DentalPaymentSummaryJournalLine(models.Model):
    _name = 'dental.payment.summary.journal.line'
    _description = 'Payment Method Summary Line'
    _order = 'journal_id asc'

    summary_id = fields.Many2one(
        'dental.payment.summary',
        string='Payment Summary',
        required=True,
        ondelete='cascade',
        index=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Method',
        required=True,
    )
    journal_type = fields.Selection(
        related='journal_id.type',
        string='Method Type',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='summary_id.currency_id',
    )
    transaction_count = fields.Integer(
        string='Transactions',
        default=0,
    )
    amount_collected = fields.Monetary(
        string='Gross Collected',
        default=0.0,
        currency_field='currency_id',
    )
    amount_refunded = fields.Monetary(
        string='Refunded',
        default=0.0,
        currency_field='currency_id',
    )
    amount_expected = fields.Monetary(
        string='Net Expected',
        compute='_compute_expected',
        store=True,
        currency_field='currency_id',
    )
    amount_counted = fields.Monetary(
        string='Counted / Verified',
        default=0.0,
        currency_field='currency_id',
        help='Actual physical amount counted or slip total verified by cashier.',
    )
    amount_difference = fields.Monetary(
        string='Difference',
        compute='_compute_difference',
        store=True,
        currency_field='currency_id',
    )
    notes = fields.Char(
        string='Notes',
    )

    @api.depends('amount_collected', 'amount_refunded')
    def _compute_expected(self):
        for rec in self:
            rec.amount_expected = rec.amount_collected - rec.amount_refunded

    @api.depends('amount_counted', 'amount_expected')
    def _compute_difference(self):
        for rec in self:
            rec.amount_difference = rec.amount_counted - rec.amount_expected


class DentalPaymentSummaryLine(models.Model):
    _name = 'dental.payment.summary.line'
    _description = 'Payment Summary Detail Transaction Line'
    _order = 'payment_date asc, payment_time asc, id asc'

    summary_id = fields.Many2one(
        'dental.payment.summary',
        string='Payment Summary',
        required=True,
        ondelete='cascade',
        index=True,
    )
    payment_id = fields.Many2one(
        'account.payment',
        string='Payment Record',
        ondelete='set null',
    )
    payment_name = fields.Char(
        string='Payment Ref',
    )
    payment_date = fields.Date(
        string='Date',
    )
    payment_time = fields.Char(
        string='Time',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Patient',
    )
    patient_identifier = fields.Char(
        string='Patient ID',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Method',
    )
    payment_type = fields.Selection([
        ('inbound', 'Collection'),
        ('outbound', 'Refund'),
    ], string='Type', default='inbound')
    currency_id = fields.Many2one(
        'res.currency',
        related='summary_id.currency_id',
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
    )
    invoice_origin = fields.Char(
        string='Invoice / Visit',
    )
    dentist_id = fields.Many2one(
        'hr.employee',
        string='Treating Doctor',
    )
    cashier_id = fields.Many2one(
        'res.users',
        string='Cashier',
    )
    communication = fields.Char(
        string='Memo / Ref',
    )


class DentalPaymentSummaryDenomination(models.Model):
    _name = 'dental.payment.summary.denomination'
    _description = 'Cash Denomination Breakdown'
    _order = 'denomination_value desc'

    summary_id = fields.Many2one(
        'dental.payment.summary',
        string='Payment Summary',
        required=True,
        ondelete='cascade',
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='summary_id.currency_id',
    )
    denomination_value = fields.Float(
        string='Denomination Note / Coin',
        required=True,
    )
    count = fields.Integer(
        string='Pieces / Count',
        default=0,
    )
    total_amount = fields.Monetary(
        string='Subtotal',
        compute='_compute_total',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('denomination_value', 'count')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = (rec.denomination_value or 0.0) * (rec.count or 0)

