from odoo import models

class AccountJournal(models.Model):
    _inherit = "account.journal"

    def open_action(self):
        self.ensure_one()
        if self.type in ('bank', 'cash'):
            action = self.env["ir.actions.act_window"]._for_xml_id('hudson_accounting_enhancements.action_hudson_bank_matching_tree')
            
            action_context = action.get('context', {})
            if isinstance(action_context, str):
                import ast
                action_context = ast.literal_eval(action_context)
                
            action['context'] = {
                **action_context,
                **self.env.context,
                'default_journal_id': self.id,
            }
            action['domain'] = [('journal_id', '=', self.id)]
            return action
            
        return super(AccountJournal, self).open_action()
