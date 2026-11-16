from odoo import api, fields, models

# Between an exact service (0) and a generic product category (20).
RANK_DENTAL_CATEGORY = 10


class InsuranceCoverageLine(models.Model):
    _inherit = 'insurance.coverage.line'

    applies_to = fields.Selection(
        selection_add=[('dental_category', 'Dental Treatment Category')],
        ondelete={'dental_category': 'cascade'})
    dental_treatment_category_id = fields.Many2one(
        'dental.treatment.category', string='Treatment Category', ondelete='cascade',
        help='e.g. Endodontics, Orthodontics, Cosmetic.')

    def _get_target(self):
        if self.applies_to == 'dental_category':
            return self.dental_treatment_category_id
        return super()._get_target()

    @api.onchange('applies_to')
    def _onchange_applies_to(self):
        super()._onchange_applies_to()
        if self.applies_to != 'dental_category':
            self.dental_treatment_category_id = False

    def _match_rank(self, template):
        if self.applies_to == 'dental_category':
            category = template.dental_treatment_category_id
            if category and category == self.dental_treatment_category_id:
                return RANK_DENTAL_CATEGORY
            return None
        return super()._match_rank(template)
