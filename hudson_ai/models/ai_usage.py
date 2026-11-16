# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class HudsonAIUsage(models.Model):
    """One line per call to the AI provider: who used how many tokens."""
    _name = 'hudson.ai.usage'
    _description = 'Hudson AI Usage'
    _order = 'id desc'
    _log_access = False

    date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True, index='btree_not_null',
                              ondelete='set null', help='Local user (empty for gateway clients).')
    client_id = fields.Many2one('hudson.ai.client', string='Gateway Client', readonly=True,
                                ondelete='cascade')
    feature = fields.Selection([
        ('chat', 'Chat'),
        ('summarize', 'Summarize'),
        ('draft', 'Draft'),
        ('write', 'Write article'),
        ('test', 'Connection test'),
        ('gateway', 'Gateway'),
    ], required=True, readonly=True, default='chat')
    model = fields.Char(string='AI Model', readonly=True)
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    total_tokens = fields.Integer(readonly=True, aggregator='sum')

    _client_date_idx = models.Index('(client_id, date) WHERE client_id IS NOT NULL')

    @api.model
    def _log(self, usage, feature, model=None, client=None):
        """Store the `usage` dict returned by an OpenAI-compatible API."""
        usage = usage or {}
        prompt = int(usage.get('prompt_tokens') or 0)
        completion = int(usage.get('completion_tokens') or 0)
        self.sudo().create({
            'user_id': False if client else self.env.uid,
            'client_id': client.id if client else False,
            'feature': feature,
            'model': model,
            'prompt_tokens': prompt,
            'completion_tokens': completion,
            'total_tokens': int(usage.get('total_tokens') or prompt + completion),
        })
