from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    unsplash_access_key = fields.Char(
        string='Unsplash Access Key',
        config_parameter='knowledge_management_pro.unsplash_access_key',
        help='Your Unsplash Access Key for image search.'
    )
    unsplash_app_id = fields.Char(
        string='Unsplash Application ID',
        config_parameter='knowledge_management_pro.unsplash_app_id',
        help='Your Unsplash Application ID.'
    )
    
    auto_save_interval = fields.Integer(
        string='Auto Save Interval (seconds)',
        config_parameter='knowledge_management_pro.auto_save_interval',
        default=600,
        help='Time in seconds between automatic saves of knowledge articles.'
    )
