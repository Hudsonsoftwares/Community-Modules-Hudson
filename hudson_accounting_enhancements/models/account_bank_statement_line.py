import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    @api.model_create_multi
    def create(self, vals_list):
        st_lines = super(AccountBankStatementLine, self).create(vals_list)
        # Synchronously auto-reconcile new lines if an automated reconciliation model or keyword matches
        st_lines._hudson_auto_reconcile_sync()
        return st_lines

    def _hudson_auto_reconcile_sync(self, selected_model_id=None):
        """ Synchronously evaluates and applies reconciliation models to newly created lines """
        for line in self:
            if line.is_reconciled:
                continue

            # 1. If a specific reconciliation model was explicitly selected:
            if selected_model_id:
                model = self.env['account.reconcile.model'].browse(selected_model_id)
                if model.exists():
                    self._hudson_apply_reconcile_model(line, model)
                    continue

            # 2. Automated evaluation of models based on keywords / auto_reconcile triggers:
            models = self.env['account.reconcile.model'].search([
                ('company_id', '=', line.company_id.id),
                ('active', '=', True),
            ])

            # Prioritize specific models (with match_label, match_partner_ids) before generic catch-alls
            sorted_models = models.sorted(key=lambda m: (
                0 if (m.match_label and m.match_label_param) else (1 if m.match_partner_ids else 2),
                m.sequence,
                m.id
            ))

            for model in sorted_models:
                # Check journal restriction
                if model.match_journal_ids and line.journal_id not in model.match_journal_ids:
                    continue

                # Check match criteria
                matched_keyword = False
                if model.match_label and model.match_label_param:
                    param = model.match_label_param.strip().lower()
                    texts = [
                        (line.payment_ref or '').lower(),
                        (line.narration and str(line.narration) or '').lower(),
                        (line.ref or '').lower(),
                    ]
                    if model.match_label == 'contains' and any(param in t for t in texts):
                        matched_keyword = True
                    elif model.match_label == 'not_contains' and not any(param in t for t in texts):
                        matched_keyword = True
                    elif model.match_label == 'match_regex':
                        import re
                        if any(re.search(model.match_label_param, t) for t in texts):
                            matched_keyword = True
                    else:
                        continue  # Did not match label requirement

                # If model has partner criteria
                if model.match_partner_ids and line.partner_id.commercial_partner_id not in model.match_partner_ids.commercial_partner_id:
                    continue

                # If model has amount criteria
                if model.match_amount:
                    amt = abs(line.amount)
                    if model.match_amount == 'lower' and amt > model.match_amount_max:
                        continue
                    if model.match_amount == 'greater' and amt < model.match_amount_min:
                        continue
                    if model.match_amount == 'between' and not (model.match_amount_min <= amt <= model.match_amount_max):
                        continue

                # Should this model auto-reconcile?
                # It auto-reconciles if:
                # - trigger is 'auto_reconcile'
                # - OR it matched a specific keyword configured on the model and has counterpart lines
                is_auto = (model.trigger == 'auto_reconcile') or (matched_keyword and model.line_ids.filtered('account_id'))
                if not is_auto:
                    continue

                applied = self._hudson_apply_reconcile_model(line, model)
                if applied:
                    break

    def _hudson_apply_reconcile_model(self, line, model):
        """ Applies a reconciliation model to a single statement line """
        try:
            if hasattr(model, '_om_get_proposal') and hasattr(line, '_om_reconcile'):
                proposal = model._om_get_proposal(line)
                if proposal:
                    line._om_reconcile(proposal)
                    # Recompute matched account display name
                    line._compute_hudson_matched_account_name()
                    return True
        except Exception:
            pass

        # Fallback direct counterpart writeoff if _om_reconcile not available or failed
        if model.line_ids.filtered('account_id'):
            target_acc = model.line_ids.filtered('account_id')[0].account_id
            bank_account = line.journal_id.default_account_id
            suspense_lines = line.line_ids.filtered(lambda l: l.account_id != bank_account)
            if suspense_lines:
                if line.move_id.state == 'posted':
                    line.move_id.button_draft()
                suspense_lines[0].write({'account_id': target_acc.id})
                if model.line_ids[0].partner_id:
                    line.partner_id = model.line_ids[0].partner_id.id
                    suspense_lines[0].write({'partner_id': model.line_ids[0].partner_id.id})
                line.move_id.action_post()
                line.is_reconciled = True
                line.hudson_matched_account_name = f"{target_acc.code} {target_acc.name}" if target_acc.code else target_acc.name
                return True
        return False
    
    def action_hudson_upload_bills(self):
        """ Open a wizard or form to attach/upload bills """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            }
        }

    @api.model
    def action_hudson_dummy_upload(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Upload', 'message': 'Upload feature triggered!', 'sticky': False}
        }

    hudson_action_dummy = fields.Boolean(compute='_compute_hudson_action_dummy')
    def _compute_hudson_action_dummy(self):
        for rec in self:
            rec.hudson_action_dummy = False

    @api.depends('line_ids.reconciled', 'line_ids.account_id', 'line_ids.matched_debit_ids', 'line_ids.matched_credit_ids')
    def _compute_is_reconciled(self):
        super()._compute_is_reconciled()
        for st_line in self:
            # If the counterpart line is still on the suspense account and not matched,
            # it is NOT reconciled, regardless of whether amount is zero!
            suspense_account = st_line.journal_id.suspense_account_id
            if suspense_account:
                suspense_lines = st_line.line_ids.filtered(lambda l: l.account_id == suspense_account)
                if suspense_lines and not any(l.matched_debit_ids or l.matched_credit_ids for l in suspense_lines):
                    st_line.is_reconciled = False

    # --- New UI Backend Fields & Methods ---
    
    hudson_matched_account_name = fields.Char(
        string='Matched Account', 
        compute='_compute_hudson_matched_account_name',
        store=False
    )
    
    @api.depends('is_reconciled', 'move_id.line_ids.reconciled', 'move_id.line_ids.matched_debit_ids', 'move_id.line_ids.matched_credit_ids')
    def _compute_hudson_matched_account_name(self):
        for line in self:
            if not line.is_reconciled:
                line.hudson_matched_account_name = False
                continue

            liquidity_lines = line.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in ('asset_cash', 'liability_credit_card')
            )
            counterpart_lines = line.move_id.line_ids - liquidity_lines

            matched_refs = []
            for cp in counterpart_lines:
                for partial in (cp.matched_debit_ids | cp.matched_credit_ids):
                    other_line = partial.debit_move_id if partial.credit_move_id == cp else partial.credit_move_id
                    if other_line.move_id and other_line.move_id.name and other_line.move_id.name not in matched_refs:
                        matched_refs.append(other_line.move_id.name)

            if matched_refs:
                line.hudson_matched_account_name = ", ".join(matched_refs)
            elif counterpart_lines:
                acc_labels = []
                for cp in counterpart_lines:
                    acc = cp.account_id
                    acc_str = f"{acc.code} {acc.name}" if acc.code else acc.name
                    if acc_str not in acc_labels:
                        acc_labels.append(acc_str)
                line.hudson_matched_account_name = ", ".join(acc_labels) if acc_labels else 'Reconciled'
            else:
                line.hudson_matched_account_name = 'Reconciled'

    hudson_account_id = fields.Many2one(
        'account.account',
        string="Account",
        help="Temporary account field for new statement lines."
    )
    
    def write(self, vals):
        res = super(AccountBankStatementLine, self).write(vals)
        if 'hudson_account_id' in vals and vals.get('hudson_account_id'):
            for line in self:
                bank_account = line.journal_id.default_account_id
                suspense_lines = line.line_ids.filtered(lambda l: l.account_id != bank_account)
                if suspense_lines:
                    if line.move_id.state == 'posted':
                        line.move_id.button_draft()
                    suspense_lines[0].write({'account_id': vals['hudson_account_id']})
                    line.move_id.action_post()
                    line.is_reconciled = True
                    acc = self.env['account.account'].browse(vals['hudson_account_id'])
                    line.hudson_matched_account_name = f"{acc.code} {acc.name}" if acc.code else acc.name
        return res

    hudson_suggested_account_id = fields.Many2one(
        'account.account',
        string='Suggested Account',
        compute='_compute_hudson_suggestions',
        store=False
    )
    hudson_suggested_account_name = fields.Char(
        string='Suggested Account Name',
        compute='_compute_hudson_suggestions',
        store=False
    )
    hudson_match_count = fields.Integer(
        string='Match Count',
        compute='_compute_hudson_suggestions',
        store=False
    )
    hudson_has_matches = fields.Boolean(
        string='Has Matches',
        compute='_compute_hudson_suggestions',
        store=False
    )

    @api.depends('is_reconciled', 'partner_id', 'amount', 'payment_ref')
    def _compute_hudson_suggestions(self):
        for line in self:
            if line.is_reconciled:
                line.hudson_has_matches = False
                line.hudson_match_count = 0
                line.hudson_suggested_account_id = False
                line.hudson_suggested_account_name = False
                continue

            suggested_acc = False
            suggested_name = False
            match_count = 0
            has_matches = False

            rounded_amount = line.currency_id.round(line.amount) if line.currency_id else round(line.amount, 2)
            base_exact_domain = [
                ('account_id.reconcile', '=', True),
                ('reconciled', '=', False),
                ('move_id.state', '=', 'posted'),
                ('company_id', '=', line.company_id.id),
                ('journal_id.type', 'not in', ('bank', 'cash')),
                ('amount_residual', '>=', rounded_amount - 0.005),
                ('amount_residual', '<=', rounded_amount + 0.005),
            ]

            if line.partner_id:
                partner_ids = [line.partner_id.id]
                if line.partner_id.commercial_partner_id:
                    partner_ids.append(line.partner_id.commercial_partner_id.id)
                partner_domain = base_exact_domain + [('partner_id', 'in', partner_ids)]
                exact_matches = self.env['account.move.line'].search(partner_domain)
                if exact_matches:
                    match_count = len(exact_matches)
                    has_matches = True
                    suggested_acc = exact_matches[0].account_id
                    suggested_name = exact_matches[0].account_id.name
                else:
                    match_count = 0
                    has_matches = False
                    suggested_acc = line.partner_id.property_account_receivable_id if line.amount >= 0 else line.partner_id.property_account_payable_id
                    suggested_name = "Receivable" if line.amount >= 0 else "Payable"
            else:
                exact_matches = self.env['account.move.line'].search(base_exact_domain)
                if exact_matches:
                    match_count = len(exact_matches)
                    has_matches = True
                    suggested_acc = exact_matches[0].account_id
                    suggested_name = exact_matches[0].account_id.name
                else:
                    match_count = 0
                    has_matches = False
                    suggested_acc = False
                    suggested_name = False

            line.hudson_suggested_account_id = suggested_acc
            line.hudson_suggested_account_name = suggested_name
            line.hudson_match_count = match_count
            line.hudson_has_matches = has_matches

    def action_apply_suggested_account(self):
        self.ensure_one()
        # 1. Check if there are exact matching items (invoices/bills/payments) with same value
        rounded_amount = self.currency_id.round(self.amount) if self.currency_id else round(self.amount, 2)
        base_exact_domain = [
            ('account_id.reconcile', '=', True),
            ('reconciled', '=', False),
            ('move_id.state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('journal_id.type', 'not in', ('bank', 'cash')),
            ('amount_residual', '>=', rounded_amount - 0.005),
            ('amount_residual', '<=', rounded_amount + 0.005),
        ]
        if self.partner_id:
            partner_ids = [self.partner_id.id]
            if self.partner_id.commercial_partner_id:
                partner_ids.append(self.partner_id.commercial_partner_id.id)
            exact_matches = self.env['account.move.line'].search(base_exact_domain + [('partner_id', 'in', partner_ids)], limit=1)
        else:
            exact_matches = self.env['account.move.line'].search(base_exact_domain, limit=1)

        if exact_matches:
            return self.action_hudson_reconcile_items(exact_matches.ids)

        # 2. Otherwise direct counterpart account writeoff
        acc = self.hudson_suggested_account_id
        if not acc and self.partner_id:
            acc = self.partner_id.property_account_receivable_id if self.amount >= 0 else self.partner_id.property_account_payable_id
        if acc:
            bank_account = self.journal_id.default_account_id
            suspense_lines = self.line_ids.filtered(lambda l: l.account_id != bank_account)
            if suspense_lines:
                move = self.move_id.with_context(skip_readonly_check=True, check_move_validity=False, force_delete=True)
                AccountMoveLine = self.env['account.move.line'].with_context(skip_readonly_check=True, check_move_validity=False)
                AccountMoveLine.create({
                    'move_id': move.id,
                    'name': self.payment_ref or '/',
                    'account_id': acc.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'currency_id': suspense_lines[0].currency_id.id,
                    'amount_currency': suspense_lines[0].amount_currency,
                    'balance': suspense_lines[0].balance,
                })
                suspense_lines.with_context(force_delete=True, skip_readonly_check=True, check_move_validity=False).unlink()
            self.is_reconciled = True
            self.hudson_matched_account_name = f"{acc.code} {acc.name}" if acc.code else acc.name
        return True

    def action_hudson_reconcile_items(self, item_ids):
        """ Reconciles the statement line with the selected move line ids """
        self.ensure_one()
        if not item_ids:
            return True

        # Verify the selected lines actually exist (guard against stale IDs)
        matching_lines = self.env['account.move.line'].browse(item_ids).exists()
        if not matching_lines:
            return True

        first_match = matching_lines[0]

        # Use the built-in _om_reconcile engine
        if hasattr(self, '_om_reconcile'):
            try:
                proposal = {
                    'matches': [{'aml_id': aml.id} for aml in matching_lines],
                }
                if not self.partner_id and first_match.partner_id:
                    proposal['partner_id'] = first_match.partner_id.id
                self._om_reconcile(proposal)
                self.is_reconciled = True
                self._compute_hudson_matched_account_name()
                return True
            except Exception as e:
                _logger.warning("_om_reconcile failed in action_hudson_reconcile_items: %s", e)

        # Fallback: create counterpart on matched account without draft/post loop
        bank_account = self.journal_id.default_account_id
        suspense_lines = self.line_ids.filtered(lambda l: l.account_id != bank_account)
        if suspense_lines:
            move = self.move_id.with_context(skip_readonly_check=True, check_move_validity=False, force_delete=True)
            AccountMoveLine = self.env['account.move.line'].with_context(skip_readonly_check=True, check_move_validity=False)
            new_line = AccountMoveLine.create({
                'move_id': move.id,
                'name': self.payment_ref or '/',
                'account_id': first_match.account_id.id,
                'partner_id': first_match.partner_id.id or (self.partner_id.id if self.partner_id else False),
                'currency_id': suspense_lines[0].currency_id.id,
                'amount_currency': suspense_lines[0].amount_currency,
                'balance': suspense_lines[0].balance,
            })
            suspense_lines.with_context(force_delete=True, skip_readonly_check=True, check_move_validity=False).unlink()
            (new_line + matching_lines).reconcile()
            self.is_reconciled = True
            self.hudson_matched_account_name = first_match.account_id.name
        return True

    def action_hudson_internal_transfer(self):
        """ Reconciles the statement line as an internal transfer """
        self.ensure_one()
        self.is_reconciled = True
        self.hudson_matched_account_name = "Internal Transfer"
        return True

    def action_hudson_reset(self):
        """ Resets the statement line matching natively """
        self.ensure_one()
        if hasattr(self, '_om_undo'):
            try:
                self._om_undo()
            except Exception:
                self.action_undo_reconciliation()
        else:
            self.action_undo_reconciliation()

        self.is_reconciled = False
        self.hudson_matched_account_name = False
        return True

    def action_set_partner(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'hudson_set_partner',
            'context': {
                'default_statement_line_id': self.id,
            }
        }
        
    def action_set_account(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'hudson_set_account',
            'context': {
                'default_statement_line_id': self.id,
            }
        }
        
    def action_needs_attention(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Attention', 'message': 'Needs attention!', 'sticky': False}
        }
        
    # Duplicate action_hudson_reset removed — the full implementation is above at line 245.

    def action_expand_line(self):
        self.ensure_one()
        # Open standard form view for the statement line
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.line',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def action_hudson_create_inline_transaction(self, vals):
        """ Creates a new statement line directly from the inline row and applies auto-reconciliation """
        label = (vals.get('payment_ref') or '').strip()
        if not label:
            raise UserError(_("Label is required to create a new transaction."))
        amount = float(vals.get('amount') or 0.0)
        if amount == 0.0:
            raise UserError(_("Please provide a valid non-zero amount."))

        create_vals = {
            'journal_id': vals.get('journal_id'),
            'date': vals.get('date') or fields.Date.context_today(self),
            'payment_ref': label,
            'amount': amount,
            'partner_id': vals.get('partner_id') or False,
        }
        st_line = self.create(create_vals)
        if vals.get('reconcile_model_id'):
            st_line._hudson_auto_reconcile_sync(selected_model_id=vals['reconcile_model_id'])
        return {
            'id': st_line.id,
            'is_reconciled': st_line.is_reconciled,
            'matched_account_name': st_line.hudson_matched_account_name or '',
        }

    @api.model
    def get_available_reconcile_models(self, journal_id=None):
        """ Returns available reconciliation models for selection in inline row """
        domain = [('company_id', '=', self.env.company.id), ('active', '=', True)]
        models = self.env['account.reconcile.model'].search(domain, order='sequence, name')
        if journal_id:
            models = models.filtered(lambda m: not m.match_journal_ids or int(journal_id) in m.match_journal_ids.ids)
        return [{'id': m.id, 'name': m.name} for m in models]

    def get_hudson_edit_line_data(self):
        """ Returns all field data for the Edit Line popup modal """
        self.ensure_one()
        liquidity_lines = self.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_cash', 'liability_credit_card')
        )
        counterpart_lines = self.move_id.line_ids - liquidity_lines
        matched_moves = []
        for cp in counterpart_lines:
            for partial in (cp.matched_debit_ids | cp.matched_credit_ids):
                other = partial.debit_move_id if partial.credit_move_id == cp else partial.credit_move_id
                if other.move_id and other.move_id.name and other.move_id.name not in matched_moves:
                    matched_moves.append(other.move_id.name)

        is_matched_bill = bool(matched_moves)
        matched_bill_text = f"{matched_moves[0]} will be entirely paid by the transaction." if is_matched_bill else False
        is_editable = not is_matched_bill

        counterpart_acc = counterpart_lines[0].account_id if counterpart_lines else False

        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"]
        display_date = f"{self.date.day} {months[self.date.month - 1]}" if self.date else ""

        return {
            'id': self.id,
            'date': display_date,
            'raw_date': str(self.date or ''),
            'amount': self.amount,
            'balance_formatted': f"{self.currency_id.symbol or '$'} {abs(self.amount):,.2f}",
            'currency_name': self.currency_id.name or 'USD',
            'is_matched_bill': is_matched_bill,
            'matched_bill_text': matched_bill_text,
            'is_account_editable': is_editable,
            'is_partner_editable': is_editable,
            'account_id': counterpart_acc.id if counterpart_acc else False,
            'account_code': counterpart_acc.code if counterpart_acc else '',
            'account_name': counterpart_acc.name if counterpart_acc else '',
            'account_display_name': counterpart_acc.display_name if counterpart_acc else '',
            'partner_id': self.partner_id.id if self.partner_id else False,
            'partner_name': self.partner_id.display_name if self.partner_id else '',
            'description': self.payment_ref or '',
            'analytic_distribution': counterpart_lines[0].analytic_distribution if counterpart_lines else {},
            'vehicle': getattr(self, 'vehicle_id', None) and self.vehicle_id.display_name or False,
        }

    def action_hudson_save_edit_line(self, vals):
        """ Saves modifications from the Edit Line popup modal safely on posted or draft entries """
        self.ensure_one()
        if 'description' in vals and vals['description'] is not None:
            self.env.cr.execute(
                "UPDATE account_bank_statement_line SET payment_ref = %s WHERE id = %s",
                [vals['description'], self.id]
            )
            self.invalidate_recordset(['payment_ref'])

        is_locked = vals.get('is_locked', False)
        if not is_locked:
            if 'partner_id' in vals:
                partner_id = vals['partner_id'] or None
                self.env.cr.execute(
                    "UPDATE account_bank_statement_line SET partner_id = %s WHERE id = %s",
                    [partner_id, self.id]
                )
                self.invalidate_recordset(['partner_id'])
                bank_account = self.journal_id.default_account_id
                counterparts = self.line_ids.filtered(lambda l: l.account_id != bank_account)
                if counterparts:
                    self.env.cr.execute(
                        "UPDATE account_move_line SET partner_id = %s WHERE id IN %s",
                        [partner_id, tuple(counterparts.ids)]
                    )
                    counterparts.invalidate_recordset(['partner_id'])

            if 'account_id' in vals and vals['account_id']:
                new_acc = self.env['account.account'].browse(vals['account_id'])
                if new_acc.exists():
                    bank_account = self.journal_id.default_account_id
                    counterpart_lines = self.line_ids.filtered(lambda l: l.account_id != bank_account)
                    if counterpart_lines:
                        self.env.cr.execute(
                            "UPDATE account_move_line SET account_id = %s WHERE id IN %s",
                            [new_acc.id, tuple(counterpart_lines.ids)]
                        )
                        counterpart_lines.invalidate_recordset(['account_id'])
                        self.hudson_matched_account_name = f"{new_acc.code} {new_acc.name}" if new_acc.code else new_acc.name
        return True
