from odoo import api, fields, models

class KnowledgeArticleMoveWizard(models.TransientModel):
    _name = 'knowledge.article.move.wizard'
    _description = 'Move Knowledge Article'

    article_id = fields.Many2one('knowledge.management.article', string='Article to Move', required=True)
    target_parent_id = fields.Many2one('knowledge.management.article', string='Target Parent Article')
    target_workspace_id = fields.Many2one('knowledge.management.workspace', string='Target Workspace')
    target_category_id = fields.Many2one('knowledge.management.category', string='Target Category')

    @api.model
    def default_get(self, fields_list):
        res = super(KnowledgeArticleMoveWizard, self).default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            article = self.env['knowledge.management.article'].browse(active_id)
            res['article_id'] = article.id
            res['target_workspace_id'] = article.workspace_id.id
            res['target_category_id'] = article.category_id.id
        return res

    def action_move(self):
        self.ensure_one()
        if self.article_id:
            # We also update workspace and category to match the new parent, if a parent is selected.
            # Wait, standard behavior for move is we select new parent.
            # If target_parent_id is set, it might make sense to inherit its workspace/category.
            vals = {
                'parent_id': self.target_parent_id.id,
                'workspace_id': self.target_workspace_id.id,
                'category_id': self.target_category_id.id,
            }
            if self.target_parent_id:
                vals['workspace_id'] = self.target_parent_id.workspace_id.id
                vals['category_id'] = self.target_parent_id.category_id.id
            self.article_id.write(vals)
        return {'type': 'ir.actions.act_window_close'}
