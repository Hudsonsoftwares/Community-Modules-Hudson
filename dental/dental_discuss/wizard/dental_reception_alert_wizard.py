# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup


class DentalReceptionAlertWizard(models.TransientModel):
    _name = 'dental.reception.alert.wizard'
    _description = 'Front Desk to Doctor Quick Alert'

    appointment_id = fields.Many2one('dental.appointment', string='Appointment', required=True)
    patient_id = fields.Many2one('res.partner', string='Patient', required=True)
    doctor_id = fields.Many2one('hr.employee.public', string='Doctor', required=True)

    alert_type = fields.Selection([
        ('arrived', 'Patient Arrived & Waiting in Reception'),
        ('chair_ready', 'Operatory Chair Ready for Patient'),
        ('running_late', 'Patient Running Late'),
        ('inquiry', 'Front Desk Inquiry / Chart Question'),
        ('emergency', 'Urgent Clinical Attention / Lobby Emergency'),
        ('custom', 'Custom Front-Desk Message'),
    ], string='Alert Type', required=True, default='arrived')

    minutes_late = fields.Integer(string='Estimated Delay (Minutes)', default=15)
    operatory_room = fields.Char(string='Chair / Operatory', default='Operatory 1')
    priority = fields.Selection([
        ('normal', 'Normal'),
        ('high', 'High Priority'),
        ('urgent', 'Urgent / Emergency'),
    ], string='Priority', required=True, default='normal')

    notes = fields.Text(string='Message / Note')

    def action_send_alert(self):
        self.ensure_one()
        appt = self.appointment_id
        doctor = self.doctor_id
        doctor_user = doctor.sudo().user_id if doctor and doctor.sudo().user_id else False

        # Format message content based on alert_type
        if self.alert_type == 'arrived':
            token_str = f" (Token: {appt.token_number})" if appt.token_number else ""
            alert_header = _("🔔 Patient Arrived & Waiting")
            alert_desc = _("Patient <b>%(pat)s</b>%(tok)s has arrived at the clinic front desk and is ready to be seen.",
                           pat=self.patient_id.name, tok=token_str)
        elif self.alert_type == 'chair_ready':
            alert_header = _("🪑 Operatory Chair Ready")
            alert_desc = _("Patient <b>%(pat)s</b> is called. <b>%(room)s</b> has been sanitized and prepped.",
                           pat=self.patient_id.name, room=self.operatory_room or _('Operatory Chair'))
        elif self.alert_type == 'running_late':
            alert_header = _("⏳ Patient Running Late")
            alert_desc = _("Patient <b>%(pat)s</b> contacted the front desk: running approximately <b>%(min)s minutes late</b>.",
                           pat=self.patient_id.name, min=self.minutes_late)
        elif self.alert_type == 'emergency':
            alert_header = _("🚨 URGENT: Lobby Clinical Emergency")
            alert_desc = _("Patient <b>%(pat)s</b> reports severe acute pain or requires immediate clinical assessment.",
                           pat=self.patient_id.name)
        elif self.alert_type == 'inquiry':
            alert_header = _("ℹ️ Front Desk Inquiry")
            alert_desc = _("Front desk request regarding patient <b>%(pat)s</b>.", pat=self.patient_id.name)
        else:
            alert_header = _("💬 Front Desk Note")
            alert_desc = _("Message regarding patient <b>%(pat)s</b>.", pat=self.patient_id.name)

        note_section = f"<br/><b>Note:</b> {self.notes}" if self.notes else ""
        priority_badge = ""
        if self.priority == 'urgent':
            priority_badge = "<span class='badge text-bg-danger' style='background-color:#d9534f; color:#fff; padding:2px 6px; border-radius:4px;'>URGENT</span> "
        elif self.priority == 'high':
            priority_badge = "<span class='badge text-bg-warning' style='background-color:#f0ad4e; color:#fff; padding:2px 6px; border-radius:4px;'>HIGH</span> "

        body_html = (
            f"<div class='o_dental_reception_alert' style='padding: 8px; border-left: 4px solid {'#d9534f' if self.priority=='urgent' else '#00a09d'}; background-color: #f9fbfb;'>"
            f"<strong>{priority_badge}{alert_header}</strong><br/>"
            f"{alert_desc}{note_section}<br/>"
            f"<small style='color:#666;'>Sent by: {self.env.user.name} (Front Desk) | Appt: {appt.name}</small>"
            f"</div>"
        )

        # 1. Post to appointment record chatter
        appt.message_post(body=Markup(body_html), message_type='notification', subtype_xmlid='mail.mt_comment')

        # 2. Dispatch to Doctor via Discuss Coordination Channel
        if doctor_user:
            channel_name = f"Front Desk Coordination - Dr. {doctor.name}"
            channel = self.env['discuss.channel'].get_or_create_dental_channel(
                channel_type='coordination',
                name=channel_name,
                partners=doctor_user.partner_id | self.env.user.partner_id,
                company_id=appt.branch_id.id if hasattr(appt, 'branch_id') and appt.branch_id else False,
                is_phi=True,
                extra_vals={'dental_department': 'reception'}
            )
            channel.post_dental_message(body_html, author_partner=self.env.user.partner_id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Alert Sent'),
                'message': _('Front-desk alert delivered to Dr. %(doctor)s.', doctor=doctor.name),
                'type': 'success',
                'sticky': False,
            }
        }
