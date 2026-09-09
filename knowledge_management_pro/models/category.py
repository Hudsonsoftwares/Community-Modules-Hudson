from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class KnowledgeCategory(models.Model):
    _name = 'knowledge.management.category'
    _description = 'Knowledge Category'
    _parent_store = True
    
    name = fields.Char(string='Name', required=True)
    parent_id = fields.Many2one('knowledge.management.category', string='Parent Category', index=True, ondelete='cascade')
    child_ids = fields.One2many('knowledge.management.category', 'parent_id', string='Child Categories')
    parent_path = fields.Char(index=True)

    @api.constrains('parent_id')
    def _check_hierarchy(self):
        if not self._check_recursion():
            raise ValidationError(_('Error! You cannot create recursive categories.'))
