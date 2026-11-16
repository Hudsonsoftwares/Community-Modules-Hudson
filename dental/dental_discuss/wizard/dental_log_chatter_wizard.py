# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup


class DentalLogChatterWizard(models.TransientModel):
    _name = 'dental.log.chatter.wizard'
    _description = 'Log Channel Discussion to Clinical Record Chatter'

    channel_id = fields.Many2one('discuss.channel', string='Channel', required=True)
    patient_id = fields.Many2one('res.partner', string='Patient')
    case_id = fields.Many2one('dental.case', string='Dental Case')
    appointment_id = fields.Many2one('dental.appointment', string='Appointment')
    lab_order_id = fields.Many2one('dental.lab.order', string='Lab Work Order')
    prescription_id = fields.Many2one('dental.prescription', string='Prescription')
    second_opinion_id = fields.Many2one('dental.second.opinion', string='Second Opinion / Referral')

    log_type = fields.Selection([
        ('clinical_decision', 'Clinical Decision / Consensus'),
        ('peer_consensus', 'Peer Review Consultation Note'),
        ('lab_adjustment', 'Laboratory Specification / Shade Note'),
        ('prescription_clarification', 'Pharmacist Prescription Clarification'),
        ('operational_note', 'Front Desk Coordination Note'),
    ], string='Log Type', required=True, default='clinical_decision')

    decision_summary = fields.Text(string='Decision / Discussion Summary', required=True)
    action_plan = fields.Text(string='Agreed Action Plan / Recommendations')

    def action_log_to_chatter(self):
        self.ensure_one()
        records_to_log = []
        if self.case_id:
            records_to_log.append(self.case_id)
        if self.appointment_id:
            records_to_log.append(self.appointment_id)
        if self.lab_order_id:
            records_to_log.append(self.lab_order_id)
        if self.prescription_id:
            records_to_log.append(self.prescription_id)
        if self.second_opinion_id:
            records_to_log.append(self.second_opinion_id)

        if not records_to_log:
            raise UserError(_("No linked clinical or operational record found to log this discussion against."))

        type_dict = dict(self._fields['log_type'].selection)
        log_type_label = type_dict.get(self.log_type, _('Discussion Note'))

        plan_html = f"<br/><b>Agreed Action Plan:</b><br/>{self.action_plan.replace(chr(10), '<br/>')}" if self.action_plan else ""
        chatter_html = (
            f"<div class='o_dental_chatter_log' style='padding: 8px; border-left: 4px solid #00A09D; background-color: #f8fbfb;'>"
            f"<strong>📋 Discuss Record: {log_type_label}</strong><br/>"
            f"<b>Summary:</b> {self.decision_summary.replace(chr(10), '<br/>')}"
            f"{plan_html}<br/>"
            f"<small style='color:#666;'>Logged from Discuss Channel: #{self.channel_id.name} by {self.env.user.name}</small>"
            f"</div>"
        )

        for rec in records_to_log:
            rec.message_post(
                body=Markup(chatter_html),
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )

        # Acknowledge in the channel
        channel_confirm_html = (
            f"<div class='o_dental_channel_ack' style='color:#0e6251;'>"
            f"✅ <i>Summary logged to official record chatter by <b>{self.env.user.name}</b>.</i>"
            f"</div>"
        )
        self.channel_id.post_dental_message(channel_confirm_html)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Logged to Record Chatter'),
                'message': _('The discussion consensus was successfully logged to the clinical record chatter.'),
                'type': 'success',
                'sticky': False,
            }
        }

