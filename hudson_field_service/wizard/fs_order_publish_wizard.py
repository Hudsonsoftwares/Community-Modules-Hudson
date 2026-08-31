# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _

class FsOrderPublishWizard(models.TransientModel):
    _name = 'fs.order.publish.wizard'
    _description = 'Publish Field Service Order Validation Wizard'

    order_ids = fields.Many2many('field.service.order', string='Orders to Publish')
    warning_message = fields.Text(string='Warning', readonly=True)

    def action_proceed_anyway(self):
        self.ensure_one()
        # Force publish the orders, bypassing the check
        for order in self.order_ids:
            if not order.is_published:
                order.is_published = True
                if order.employee_id and (order.employee_id.work_contact_id or order.employee_id.user_id.partner_id):
                    template = self.env.ref('hudson_field_service.mail_template_field_service_publish', raise_if_not_found=False)
                    if template:
                        template.send_mail(order.id, force_send=False)
        return {'type': 'ir.actions.act_window_close'}
