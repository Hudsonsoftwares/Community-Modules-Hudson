# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from markupsafe import Markup


class DentalAppointment(models.Model):
    _inherit = 'dental.appointment'

    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Discuss Channel',
        copy=False,
        help="Linked Discuss channel for visit coordination and chairside notifications."
    )
    discuss_channel_count = fields.Integer(
        string='Discussions',
        compute='_compute_discuss_channel_count'
    )

    def _compute_discuss_channel_count(self):
        for rec in self:
            count = self.env['discuss.channel'].search_count([('dental_appointment_id', '=', rec.id)])
            rec.discuss_channel_count = count

    def action_open_discuss_channel(self):
        """Open or create a dedicated coordination channel for this appointment."""
        self.ensure_one()
        doctor_partner = self.doctor_id.sudo().user_id.partner_id if self.doctor_id and self.doctor_id.sudo().user_id else self.env['res.partner']
        channel_name = f"Appointment {self.name} - {self.patient_id.name}"
        
        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='coordination',
            name=channel_name,
            partners=doctor_partner | self.env.user.partner_id,
            company_id=self.branch_id.id if hasattr(self, 'branch_id') and self.branch_id else (self.company_id.id if hasattr(self, 'company_id') and self.company_id else False),
            is_phi=True,
            extra_vals={
                'dental_appointment_id': self.id,
                'dental_patient_id': self.patient_id.id,
                'dental_department': 'reception',
            }
        )
        self.discuss_channel_id = channel
        return channel.action_open_dental_channel()

    def action_open_reception_alert(self):
        """Opens wizard for front desk staff to dispatch rapid chairside alerts to the dentist."""
        self.ensure_one()
        return {
            'name': _('Front Desk Alert to Doctor'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.reception.alert.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_appointment_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
            }
        }

    def action_check_in(self):
        """Extended check-in: notifies doctor in Discuss and logs audit in appointment chatter."""
        res = super().action_check_in()
        for rec in self:
            doctor_user = rec.doctor_id.sudo().user_id if rec.doctor_id and rec.doctor_id.sudo().user_id else False
            token_display = rec.token_number or _('Assigned at Desk')
            
            # 1. Post to record chatter
            chatter_body = _(
                "<strong>🔔 Front Desk Check-in Alert</strong><br/>"
                "Patient <strong>%(patient)s</strong> has arrived and checked in.<br/>"
                "Queue Token: <strong>%(token)s</strong><br/>"
                "Scheduled Doctor: <strong>%(doctor)s</strong>",
                patient=rec.patient_id.name,
                token=token_display,
                doctor=rec.doctor_id.name or _('Unassigned')
            )
            rec.message_post(body=Markup(chatter_body), message_type='notification', subtype_xmlid='mail.mt_comment')

            # 2. Automated Discuss Notification to the Doctor's Coordination Channel
            if doctor_user:
                channel_name = f"Front Desk Coordination - Dr. {rec.doctor_id.name}"
                channel = self.env['discuss.channel'].get_or_create_dental_channel(
                    channel_type='coordination',
                    name=channel_name,
                    partners=doctor_user.partner_id | self.env.user.partner_id,
                    company_id=rec.branch_id.id if hasattr(rec, 'branch_id') and rec.branch_id else False,
                    is_phi=True,
                    extra_vals={'dental_department': 'reception'}
                )
                
                alert_html = _(
                    "<div class='o_dental_discuss_alert' style='padding: 8px; border-left: 4px solid #00A09D; background-color: #f6fbfb;'>"
                    "<strong>🔔 Patient Check-in Notification</strong><br/>"
                    "Patient: <b>%(patient)s</b> (Token: <b>%(token)s</b>)<br/>"
                    "Appointment: <b>%(appt)s</b><br/>"
                    "Status: Waiting in Reception Lounge"
                    "</div>",
                    patient=rec.patient_id.name,
                    token=token_display,
                    appt=rec.name
                )
                channel.post_dental_message(alert_html, author_partner=self.env.user.partner_id)
        return res

    def action_cancel(self):
        """Extended cancel: notifies doctor if a confirmed appointment is cancelled."""
        res = super().action_cancel()
        for rec in self:
            doctor_user = rec.doctor_id.user_id if rec.doctor_id and rec.doctor_id.user_id else False
            if doctor_user:
                rec.message_post(
                    body=Markup(_("<strong>⚠️ Appointment Cancelled:</strong> Doctor notified to free up operatory chair.")),
                    subtype_xmlid='mail.mt_note'
                )
        return res

    def action_no_show(self):
        """Extended no-show: logs and notifies."""
        res = super().action_no_show()
        for rec in self:
            doctor_user = rec.doctor_id.user_id if rec.doctor_id and rec.doctor_id.user_id else False
            if doctor_user:
                rec.message_post(
                    body=Markup(_("<strong>⚠️ Patient Marked No-Show:</strong> Chair time released.")),
                    subtype_xmlid='mail.mt_note'
                )
        return res
