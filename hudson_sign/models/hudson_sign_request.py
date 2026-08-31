from odoo import api, fields, models, _

class HudsonSignRequest(models.Model):
    _name = "hudson.sign.request"
    _description = "Signature Request Group"
    _rec_name = "name"
    _order = "create_date desc"

    name = fields.Char(related="revision_id.file_name", string="Document Name", store=True)
    revision_id = fields.Many2one("dms.file.revision", string="Document", required=True, ondelete="cascade")
    template_id = fields.Many2one("hudson.sign.template", string="Template")
    
    request_ids = fields.One2many("dms.file.signature.request", "hudson_request_id", string="Signers")
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'To Sign'),
        ('signed', 'Signed')
    ], compute='_compute_state', string="Status", store=True)
    
    @api.depends('request_ids.state')
    def _compute_state(self):
        for req in self:
            if not req.request_ids:
                req.state = 'draft'
            elif all(r.state == 'signed' for r in req.request_ids):
                req.state = 'signed'
            else:
                req.state = 'sent'

    def action_resend(self):
        for req in self.request_ids.filtered(lambda r: r.state != 'signed'):
            req.action_resend()

    def action_download(self):
        self.ensure_one()
        if not self.revision_id or not self.revision_id.content:
            return
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/dms.file.revision/{self.revision_id.id}/content?download=true',
            'target': 'self',
        }
