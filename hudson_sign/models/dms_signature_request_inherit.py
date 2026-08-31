from odoo import api, fields, models

class DMSFileSignatureRequest(models.Model):
    _inherit = "dms.file.signature.request"

    template_id = fields.Many2one("hudson.sign.template", string="Template")
    hudson_request_id = fields.Many2one("hudson.sign.request", string="Group Request", ondelete="cascade")
    color = fields.Integer(compute="_compute_color", string="Color")

    @api.depends('state')
    def _compute_color(self):
        for req in self:
            if req.state == 'signed':
                req.color = 10
            elif req.state == 'sent':
                req.color = 0
            else:
                req.color = 2
    
    def action_download(self):
        self.ensure_one()
        if not self.revision_id or not self.revision_id.content:
            return
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/dms.file.revision/{self.revision_id.id}/content?download=true',
            'target': 'self',
        }
        
    def action_resend(self):
        for record in self:
            if record.state != 'signed':
                record.send_signature_email()
