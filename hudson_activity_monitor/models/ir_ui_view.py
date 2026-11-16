from odoo import fields, models


class IrUiView(models.Model):
    """Odoo 20 Community has no Gantt view type (web_gantt is Enterprise).
    hudson_attendance_enhancement / hudson_rental declare the same type; selection_add
    entries merge, so declaring it here too keeps this module independent of them.
    The client side is our own js_class ``activity_gantt``."""
    _inherit = 'ir.ui.view'

    type = fields.Selection(selection_add=[('gantt', 'Gantt')])

    def _get_view_info(self):
        return {'gantt': {'icon': 'view_timeline'}} | super()._get_view_info()

    def _validate_tag_gantt(self, node, name_manager, node_info):
        pass


class IrActionsActWindowView(models.Model):
    _inherit = 'ir.actions.act_window.view'

    view_mode = fields.Selection(selection_add=[('gantt', 'Gantt')], ondelete={'gantt': 'cascade'})
