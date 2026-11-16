# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""Which models the AI may read for a user ("AI scope").

Odoo's access rights alone are too wide for an assistant: a salesperson can
technically read invoices and the chart of accounts (needed for links from
sales orders), but should not be able to ask the AI about the accounting.

Scope of a user =
  * models opened by the menus the user can see, plus their line models
    (one2many whose inverse is required + cascade, e.g. sale.order.line);
  * + models of matching "Allow" rules, - models of matching "Block" rules.
Models only referenced (many2one) by those are "lookup" models: the AI can
find their records by name to get an ID, nothing more.
"""

from odoo import api, fields, models

LOOKUP_FIELDS = ('id', 'name', 'display_name', 'active', 'default_code', 'code', 'ref')


class HudsonAIAccessRule(models.Model):
    _name = 'hudson.ai.access.rule'
    _description = 'Hudson AI Data Access Rule'
    _order = 'mode, model_id'

    active = fields.Boolean(default=True)
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade',
                               domain=[('transient', '=', False)])
    model = fields.Char(string='Model Name', related='model_id.model', store=True)
    mode = fields.Selection([('block', 'Block'), ('allow', 'Allow')], required=True, default='block',
                            help='Block: the AI never reads this model for these users, even if they '
                                 'can open it.\nAllow: the AI may read it even without a menu '
                                 '(Odoo access rights still apply).')
    group_ids = fields.Many2many('res.groups', string='For Groups',
                                 help='Leave empty to apply the rule to everybody.')
    note = fields.Char()

    @api.model
    def _get_scope(self):
        """Return (full, lookup): sets of model names for the current user."""
        env = self.env
        visible_ids = set(env['ir.ui.menu']._visible_menu_ids())
        menus = env['ir.ui.menu'].browse(visible_ids).sudo()
        # _visible_menu_ids() keeps sub-menus of hidden apps (e.g. Invoicing >
        # Customers > Invoices for a salesperson): require the whole chain.
        menus = menus.filtered(lambda m: all(
            int(menu_id) in visible_ids for menu_id in (m.parent_path or '').split('/') if menu_id))
        full = {
            action.res_model for action in menus.mapped('action')
            if action and action._name == 'ir.actions.act_window' and action.res_model
        }
        full = {name for name in full if name in env}
        for name in list(full):
            for field in env[name]._fields.values():
                if field.type == 'one2many' and field.comodel_name in env:
                    inverse = env[field.comodel_name]._fields.get(field.inverse_name)
                    if (inverse is not None and inverse.type == 'many2one' and inverse.required
                            and inverse.ondelete == 'cascade'):
                        full.add(field.comodel_name)

        user_groups = env.user.all_group_ids
        rules = self.sudo().search([])
        applying = rules.filtered(lambda r: not r.group_ids or r.group_ids & user_groups)
        full |= set(applying.filtered(lambda r: r.mode == 'allow').mapped('model'))
        blocked = set(applying.filtered(lambda r: r.mode == 'block').mapped('model'))
        full -= blocked

        lookup = set()
        for name in full:
            for field in env[name]._fields.values():
                if field.type == 'many2one' and field.comodel_name in env:
                    lookup.add(field.comodel_name)
        lookup -= full | blocked
        return {
            'full': {name for name in full if env[name].has_access('read')},
            'lookup': {name for name in lookup if env[name].has_access('read')},
        }
