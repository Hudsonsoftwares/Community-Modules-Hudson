from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Lower rank = more specific rule. Specialty modules slot their own levels in
# between (e.g. dental treatment category = 10).
RANK_PRODUCT = 0
RANK_PRODUCT_CATEGORY = 20
RANK_ALL = 100


class InsurancePlan(models.Model):
    _name = 'insurance.plan'
    _description = 'Insurance Plan'
    _inherit = ['mail.thread']
    _order = 'insurer_id, name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(help="Payer's code for the plan / product, if any.")
    active = fields.Boolean(default=True)
    insurer_id = fields.Many2one(
        'res.partner', string='Insurance Company', required=True, index=True, tracking=True,
        domain=[('insurance_partner_type', '=', 'insurer')])
    tpa_id = fields.Many2one(
        'res.partner', string='Default TPA', tracking=True,
        domain=[('insurance_partner_type', '=', 'tpa')],
        help='TPA that usually processes this plan. Can be changed per policy.')
    company_id = fields.Many2one('res.company', string='Company',
                                 help='Leave empty to share the plan between companies.')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id,
                                  required=True)
    annual_limit = fields.Monetary(help='Yearly maximum the plan pays per member (0 = no limit).')
    coverage_line_ids = fields.One2many('insurance.coverage.line', 'plan_id', string='Coverage Rules',
                                        copy=True)
    policy_count = fields.Integer(compute='_compute_policy_count')
    note = fields.Text(string='Notes')

    def _compute_policy_count(self):
        counts = dict(self.env['insurance.policy']._read_group(
            [('plan_id', 'in', self.ids)], ['plan_id'], ['__count']))
        for plan in self:
            plan.policy_count = counts.get(plan, 0)

    def action_view_policies(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('insurance_base.action_insurance_policy')
        action.update({'domain': [('plan_id', '=', self.id)],
                       'context': {'default_plan_id': self.id}})
        return action

    def _get_coverage(self, product_template):
        """What this plan pays for ``product_template`` (a service).

        The most specific matching rule wins (exact service, then specialty
        levels, then product category, then "everything"); on a tie the rule
        higher in the list wins. Returns a dict:
        ``covered``, ``percent``, ``max_amount``, ``requires_preauth``, ``line``.
        """
        self.ensure_one()
        best, best_key = None, None
        for line in self.coverage_line_ids:
            rank = line._match_rank(product_template)
            if rank is None:
                continue
            key = (rank, line.sequence, line.id)
            if best_key is None or key < best_key:
                best, best_key = line, key
        if not best:
            return {'covered': False, 'percent': 0.0, 'max_amount': 0.0,
                    'requires_preauth': False, 'line': self.env['insurance.coverage.line']}
        return {
            'covered': best.covered,
            'percent': best.coverage_percent if best.covered else 0.0,
            'max_amount': best.max_amount if best.covered else 0.0,
            'requires_preauth': best.covered and best.requires_preauth,
            'line': best,
        }


class InsuranceCoverageLine(models.Model):
    _name = 'insurance.coverage.line'
    _description = 'Insurance Coverage Rule'
    _order = 'plan_id, sequence, id'

    sequence = fields.Integer(default=10)
    plan_id = fields.Many2one('insurance.plan', required=True, index=True, ondelete='cascade')
    currency_id = fields.Many2one(related='plan_id.currency_id')
    applies_to = fields.Selection([
        ('product', 'Service'),
        ('product_category', 'Product Category'),
        ('all', 'Everything Else'),
    ], required=True, default='product')
    product_tmpl_id = fields.Many2one('product.template', string='Service', ondelete='cascade')
    product_categ_id = fields.Many2one('product.category', string='Product Category',
                                       ondelete='cascade')
    covered = fields.Boolean(default=True, help='Untick to exclude (e.g. cosmetic treatment).')
    coverage_percent = fields.Float(string='Coverage %', default=100.0)
    max_amount = fields.Monetary(string='Limit per Service',
                                 help='Maximum the plan pays for one service (0 = no limit).')
    requires_preauth = fields.Boolean(string='Pre-Auth Required')
    note = fields.Char()

    @api.constrains('applies_to', 'product_tmpl_id', 'product_categ_id')
    def _check_target(self):
        for line in self:
            if line.applies_to != 'all' and not line._get_target():
                raise ValidationError(self.env._(
                    "Coverage rule of plan %(plan)s: choose what it applies to.",
                    plan=line.plan_id.display_name))

    @api.constrains('coverage_percent')
    def _check_percent(self):
        for line in self:
            if not 0 <= line.coverage_percent <= 100:
                raise ValidationError(self.env._("Coverage % must be between 0 and 100."))

    def _get_target(self):
        """Record the rule applies to (overridden by specialty modules)."""
        self.ensure_one()
        if self.applies_to == 'product':
            return self.product_tmpl_id
        if self.applies_to == 'product_category':
            return self.product_categ_id
        return None

    @api.onchange('applies_to')
    def _onchange_applies_to(self):
        if self.applies_to != 'product':
            self.product_tmpl_id = False
        if self.applies_to != 'product_category':
            self.product_categ_id = False

    def _match_rank(self, template):
        """Return how specifically this rule matches ``template`` (lower is
        more specific), or None when it does not apply."""
        self.ensure_one()
        if self.applies_to == 'product':
            return RANK_PRODUCT if template == self.product_tmpl_id else None
        if self.applies_to == 'product_category':
            category = template.categ_id
            if not category or not self.product_categ_id:
                return None
            if category == self.product_categ_id:
                return RANK_PRODUCT_CATEGORY
            ancestors = [int(x) for x in (category.parent_path or '').split('/') if x]
            if self.product_categ_id.id in ancestors:
                # a closer parent category is more specific than a far one
                distance = len(ancestors) - 1 - ancestors.index(self.product_categ_id.id)
                return RANK_PRODUCT_CATEGORY + min(distance, RANK_ALL - RANK_PRODUCT_CATEGORY - 1)
            return None
        if self.applies_to == 'all':
            return RANK_ALL
        return None
