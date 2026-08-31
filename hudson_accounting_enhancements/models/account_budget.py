from odoo import models, fields, api, _
from odoo.osv import expression

class CrossoveredBudgetLines(models.Model):
    _name = 'crossovered.budget.lines'
    _inherit = ['crossovered.budget.lines', 'analytic.plan.fields.mixin']
    
    account_id = fields.Many2one('account.analytic.account', string='Project Plan', domain="[('plan_id', 'child_of', 1)]")
    x_plan2_id = fields.Many2one('account.analytic.account', string='Departments', domain="[('plan_id', 'child_of', 2)]")
    x_plan3_id = fields.Many2one('account.analytic.account', string='Internal', domain="[('plan_id', 'child_of', 3)]")
    x_plan4_id = fields.Many2one('account.analytic.account', string='Hudson', domain="[('plan_id', 'child_of', 4)]")
    x_plan5_id = fields.Many2one('account.analytic.account', string='Hyperbaric Chamber', domain="[('plan_id', 'child_of', 5)]")
    analytic_account_id = fields.Many2one('account.analytic.account', related='account_id', store=True, readonly=False)

    budget_state = fields.Selection(related='crossovered_budget_id.state', string='Budget State')
    date_from = fields.Date('Start Date', required=False)
    date_to = fields.Date('End Date', required=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('date_from') or not vals.get('date_to'):
                budget_id = vals.get('crossovered_budget_id')
                if budget_id:
                    budget = self.env['crossovered.budget'].browse(budget_id)
                    if not vals.get('date_from'):
                        vals['date_from'] = budget.date_from
                    if not vals.get('date_to'):
                        vals['date_to'] = budget.date_to
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for record in self:
            if not record.date_from or not record.date_to:
                if record.crossovered_budget_id:
                    update_vals = {}
                    if not record.date_from:
                        update_vals['date_from'] = record.crossovered_budget_id.date_from
                    if not record.date_to:
                        update_vals['date_to'] = record.crossovered_budget_id.date_to
                    if update_vals:
                        super(CrossoveredBudgetLines, record).write(update_vals)
        return res

    practical_amount = fields.Monetary(
        compute='_compute_practical_amount', string='Practical Amount', help="Amount really earned/spent.", aggregator='sum')
    theoritical_amount = fields.Monetary(
        compute='_compute_theoritical_amount', string='Theoretical Amount',
        help="Amount you are supposed to have earned/spent at this date.", aggregator='sum')

    @api.model
    def _register_hook(self):
        super()._register_hook()
        # Automatically ensure plan columns exist on this model
        try:
            self.env['account.analytic.plan']._sync_all_plan_column()
        except Exception:
            pass

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields, attributes)
        if 'practical_amount' in res:
            res['practical_amount']['aggregator'] = 'sum'
        if 'theoritical_amount' in res:
            res['theoritical_amount']['aggregator'] = 'sum'
        if 'percentage' in res:
            res['percentage']['aggregator'] = 'sum'
        return res

    @api.model
    def _read_grouping_sets(self, domain, grouping_sets, aggregates=(), order=None):
        manual_fields = {'practical_amount', 'theoritical_amount', 'percentage'}
        sql_aggregates = []
        manual_agg_indices = {}
        for i, agg in enumerate(aggregates):
            field_name = agg.split(':')[0]
            if field_name in manual_fields:
                manual_agg_indices[i] = field_name
            else:
                sql_aggregates.append(agg)
        
        if not manual_agg_indices:
            return super()._read_grouping_sets(domain, grouping_sets, sql_aggregates, order=order)

        res = super()._read_grouping_sets(domain, grouping_sets, sql_aggregates, order=order)
        
        new_res = []
        for set_idx, grouping_set in enumerate(grouping_sets):
            group_rows = []
            for row in res[set_idx]:
                group_domain = list(domain) if domain else []
                for i, field in enumerate(grouping_set):
                    val = row[i]
                    if val is None:
                        group_domain.append((field, '=', False))
                    else:
                        if isinstance(val, tuple):
                            group_domain.append((field, '=', val[0]))
                        else:
                            group_domain.append((field, '=', val))
                
                lines = self.search(group_domain)
                prac_sum = sum(lines.mapped('practical_amount'))
                theo_sum = sum(lines.mapped('theoritical_amount'))
                
                groupby_vals = list(row[:len(grouping_set)])
                sql_agg_vals = list(row[len(grouping_set):])
                
                final_row = groupby_vals
                sql_idx = 0
                for i in range(len(aggregates)):
                    if i in manual_agg_indices:
                        f = manual_agg_indices[i]
                        if f == 'practical_amount':
                            final_row.append(prac_sum)
                        elif f == 'theoritical_amount':
                            final_row.append(theo_sum)
                        elif f == 'percentage':
                            if theo_sum:
                                final_row.append((prac_sum / theo_sum) * 100)
                            else:
                                final_row.append(0.0)
                    else:
                        final_row.append(sql_agg_vals[sql_idx])
                        sql_idx += 1
                        
                group_rows.append(tuple(final_row))
            new_res.append(group_rows)
            
        return new_res

    @api.constrains()
    def _must_have_analytical_or_budgetary_or_both(self):
        import odoo
        for record in self:
            has_plan = False
            for fname, field in self._fields.items():
                if field.type == 'many2one' and field.comodel_name == 'account.analytic.account':
                    if getattr(record, fname, False):
                        has_plan = True
                        break
            if not has_plan and not record.general_budget_id:
                raise odoo.exceptions.ValidationError(
                    _("You have to enter at least an analytic account or budgetary position on a budget line."))

    def _compute_practical_amount(self):
        for line in self:
            acc_ids = line.general_budget_id.account_ids.ids
            date_to = line.date_to
            date_from = line.date_from
            
            domain = [('date', '>=', date_from), ('date', '<=', date_to)]
            has_plan = False
            
            # Check plans dynamically
            for fname, field in line._fields.items():
                if field.type == 'many2one' and field.comodel_name == 'account.analytic.account':
                    # Skip analytic_account_id if account_id is already used, because they are related
                    if fname == 'analytic_account_id':
                        continue
                    val = getattr(line, fname, False)
                    if val:
                        domain.append((fname, '=', val.id))
                        has_plan = True
            
            if not has_plan and line.analytic_account_id:
                domain.append(('account_id', '=', line.analytic_account_id.id))
                has_plan = True
                    
            if has_plan:
                if acc_ids:
                    domain.append(('general_account_id', 'in', acc_ids))
                
                analytic_line_obj = self.env['account.analytic.line']
                result = analytic_line_obj._read_group(domain, [], ['amount:sum'])
                if result and isinstance(result[0], tuple):
                    amt = result[0][0] if result[0][0] else 0.0
                elif result and isinstance(result[0], dict):
                    amt = result[0].get('amount', 0.0)
                else:
                    amt = 0.0
                line.practical_amount = -amt if line.crossovered_budget_id.budget_type == 'expense' else amt
            elif line.general_budget_id:
                aml_obj = self.env['account.move.line']
                aml_domain = [('account_id', 'in', line.general_budget_id.account_ids.ids),
                              ('date', '>=', date_from),
                              ('date', '<=', date_to)]
                result = aml_obj._read_group(aml_domain, [], ['credit:sum', 'debit:sum'])
                if result and isinstance(result[0], tuple):
                    credit = result[0][0] or 0.0
                    debit = result[0][1] or 0.0
                    amt = credit - debit
                    line.practical_amount = -amt if line.crossovered_budget_id.budget_type == 'expense' else amt
                else:
                    line.practical_amount = 0.0
            else:
                line.practical_amount = 0.0

class CrossoveredBudget(models.Model):
    _inherit = 'crossovered.budget'

    budget_type = fields.Selection([
        ('revenue', 'Revenue'),
        ('expense', 'Expense'),
        ('both', 'Both')
    ], string='Budget Type', default='expense')

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id=view_id, view_type=view_type, **options)
        if view_type == 'form':
            from lxml import etree
            root = arch
            
            # Find the inline list and form views for crossovered_budget_line
            line_field = root.find(".//field[@name='crossovered_budget_line']")
            if line_field is not None:
                plans = self.env['account.analytic.plan'].search([])
                
                # Dynamic list view injection
                list_view = line_field.find("list")
                if list_view is not None:
                    # Remove hardcoded analytic fields
                    for child in list(list_view):
                        if child.tag == 'field' and ('plan' in child.get('name', '') or child.get('name') == 'account_id') and child.get('name') != 'planned_amount':
                            list_view.remove(child)
                    
                    # Find insertion point
                    insert_idx = 0
                    for i, child in enumerate(list_view):
                        if child.tag == 'field' and child.get('name') == 'planned_amount':
                            insert_idx = i
                            break
                    
                    for plan in plans:
                        field_name = plan._column_name()
                        new_field = etree.Element('field', {
                            'name': field_name, 
                            'string': plan.name, 
                            'optional': 'show', 
                            'domain': f"[('plan_id', 'child_of', {plan.id})]"
                        })
                        list_view.insert(insert_idx, new_field)
                        insert_idx += 1

                # Dynamic form view injection
                form_view = line_field.find("form")
                if form_view is not None:
                    group = form_view.find(".//group/group")
                    if group is not None:
                        for child in list(group):
                            if child.tag == 'field' and ('plan' in child.get('name', '') or child.get('name') == 'account_id') and child.get('name') != 'planned_amount':
                                group.remove(child)
                        
                        insert_idx = 0
                        for i, child in enumerate(group):
                            if child.tag == 'field' and child.get('name') == 'planned_amount':
                                insert_idx = i
                                break
                                
                        for plan in plans:
                            field_name = plan._column_name()
                            new_field = etree.Element('field', {
                                'name': field_name, 
                                'string': plan.name, 
                                'domain': f"[('plan_id', 'child_of', {plan.id})]"
                            })
                            group.insert(insert_idx, new_field)
                            insert_idx += 1
                            
        return arch, view

    def action_revise_budget(self):
        self.ensure_one()
        # Find all revisions of this budget
        base_name = self.name
        if " - Rev " in base_name:
            base_name = base_name.rsplit(" - Rev ", 1)[0]
        
        # Check existing revisions to find the next number
        existing_revisions = self.search([('name', 'ilike', f"{base_name} - Rev %")])
        rev_num = 1
        for rev in existing_revisions:
            try:
                num = int(rev.name.rsplit(" - Rev ", 1)[-1])
                if num >= rev_num:
                    rev_num = num + 1
            except ValueError:
                pass

        new_name = f"{base_name} - Rev {rev_num}"
        
        # Duplicate the budget
        new_budget = self.copy(default={'name': new_name, 'state': 'draft'})
        
        # Return an action to open the new budget
        return {
            'type': 'ir.actions.act_window',
            'name': _('Budget Revision'),
            'res_model': 'crossovered.budget',
            'view_mode': 'form',
            'res_id': new_budget.id,
            'target': 'current',
        }

class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    crossovered_budget_line = fields.Many2many(
        'crossovered.budget.lines',
        compute='_compute_crossovered_budget_line',
        string='Budget Lines'
    )

    def _compute_crossovered_budget_line(self):
        analytic_fields = [
            f for f, field in self.env['crossovered.budget.lines']._fields.items()
            if field.type == 'many2one' and field.comodel_name == 'account.analytic.account'
        ]
        for account in self:
            if not account.id:
                account.crossovered_budget_line = False
                continue
            clauses = [(f, '=', account.id) for f in analytic_fields]
            if clauses:
                domain = expression.OR([[c] for c in clauses])
                account.crossovered_budget_line = self.env['crossovered.budget.lines'].search(domain)
            else:
                account.crossovered_budget_line = False
