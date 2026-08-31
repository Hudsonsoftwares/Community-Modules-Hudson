from odoo import api, fields, models

class HudsonSignItemType(models.Model):
    _name = "hudson.sign.item.type"
    _description = "Signature Item Type"

    name = fields.Char(string="Field Name", required=True)
    item_type = fields.Selection([
        ('signature', 'Signature'),
        ('initial', 'Initial'),
        ('text', 'Text'),
        ('multiline', 'Multiline Text'),
        ('checkbox', 'Checkbox'),
        ('radio', 'Radio'),
        ('selection', 'Selection'),
        ('strikethrough', 'Strikethrough'),
        ('stamp', 'Stamp'),
        ('date', 'Date'),
    ], string="Type", required=True)
    
    linked_to = fields.Many2one('ir.model', string="Linked to")
    linked_field = fields.Many2one('ir.model.fields', string="Linked field", domain="[('model_id', '=', linked_to)]")
    update_field = fields.Boolean(string="Update Field")
    
    # New fields for UI match
    placeholder = fields.Char(string="Placeholder")
    tip = fields.Char(string="Tip", help="Fill in")
    mandatory = fields.Boolean(string="Mandatory", default=True)
    is_read_only = fields.Boolean(string="Read Only")
    is_shared = fields.Boolean(string="Shared")
