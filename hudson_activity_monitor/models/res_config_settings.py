from odoo import fields, models

P = 'hudson_activity_monitor.'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Stored as system parameters (no new res.company columns). Booleans are phrased
    # so that False is the default, because unticking deletes the parameter.
    activity_idle_minutes = fields.Integer('Idle After (minutes)', default=5, config_parameter=P + 'idle_minutes')
    activity_upload_interval = fields.Integer('Upload Every (seconds)', default=120,
                                              config_parameter=P + 'upload_interval')
    activity_hide_titles = fields.Boolean('Do Not Collect Window Titles', config_parameter=P + 'hide_titles')
    activity_private_apps = fields.Char('Private Applications', config_parameter=P + 'private_apps',
                                        help="Comma-separated process names (e.g. WhatsApp.exe, "
                                             "com.apple.MobileSMS) whose window titles are never collected.")
    activity_only_checked_in = fields.Boolean('Track Only While Checked In', config_parameter=P + 'only_checked_in')
    activity_block_quit = fields.Boolean('Employees Cannot Quit the Agent', config_parameter=P + 'block_quit')
    activity_retention_days = fields.Integer('Keep Detailed Activity (days)', default=90,
                                             config_parameter=P + 'retention_days')
    activity_public_url = fields.Char('Server Address for Agents', config_parameter=P + 'public_url',
                                      help="Address employees' computers use to reach Odoo, e.g. "
                                           "https://erp.example.com. Defaults to web.base.url.")
