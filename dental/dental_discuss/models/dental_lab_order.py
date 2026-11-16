# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from markupsafe import Markup


class DentalLabOrder(models.Model):
    _inherit = 'dental.lab.order'

    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Lab Discuss Channel',
        copy=False,
        help="Linked Discuss channel for technician-dentist prosthetics coordination."
    )
    discuss_channel_count = fields.Integer(
        string='Lab Discussions',
        compute='_compute_discuss_channel_count'
    )

    def _compute_discuss_channel_count(self):
        for rec in self:
            count = self.env['discuss.channel'].search_count([('dental_lab_order_id', '=', rec.id)])
            rec.discuss_channel_count = count

    def action_open_lab_channel(self):
        """Open or create a dedicated channel between doctor and dental laboratory."""
        self.ensure_one()
        if self.discuss_channel_id:
            return self.discuss_channel_id.action_open_dental_channel()

        channel_name = f"Lab Order {self.name} - {self.patient_id.name}"
        dentist = self.dentist_id if hasattr(self, 'dentist_id') and self.dentist_id else (
            self.doctor_id if hasattr(self, 'doctor_id') and self.doctor_id else False
        )
        doctor_partner = dentist.sudo().user_id.partner_id if dentist and dentist.sudo().user_id else self.env['res.partner']
        technician_partner = self.technician_id.partner_id if hasattr(self, 'technician_id') and self.technician_id else self.env['res.partner']

        # Get Lab Managers as auto-members if applicable
        lab_manager_group = self.env.ref('dental_lab.group_dental_lab_manager', raise_if_not_found=False)
        manager_partners = lab_manager_group.user_ids.mapped('partner_id') if lab_manager_group else self.env['res.partner']

        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='lab',
            name=channel_name,
            partners=doctor_partner | technician_partner | manager_partners | self.env.user.partner_id,
            company_id=self.company_id.id if hasattr(self, 'company_id') and self.company_id else False,
            is_phi=True,
            extra_vals={
                'dental_lab_order_id': self.id,
                'dental_patient_id': self.patient_id.id,
                'dental_case_id': self.case_id.id if hasattr(self, 'case_id') and self.case_id else False,
                'dental_department': 'lab',
            }
        )
        self.discuss_channel_id = channel

        # Post introductory details
        intro_html = _(
            "<div class='o_dental_discuss_lab_intro' style='padding: 8px; border-left: 4px solid #F0AD4E; background-color: #fdfaf5;'>"
            "<strong>🔬 Dental Laboratory Work Order Discussion</strong><br/>"
            "Order: <b>%(order)s</b> | Patient: <b>%(patient)s</b><br/>"
            "Due Date: %(due)s | Priority: %(priority)s<br/>"
            "<em>Discuss impressions, shade matching, margin fit, and dispatch scheduling here.</em>"
            "</div>",
            order=self.name,
            patient=self.patient_id.name,
            due=fields.Date.to_string(self.due_date) if hasattr(self, 'due_date') and self.due_date else _('Not set'),
            priority=self.priority if hasattr(self, 'priority') else 'Normal'
        )
        channel.post_dental_message(intro_html, author_partner=self.env.user.partner_id)

        self.message_post(
            body=Markup(_("💬 <strong>Laboratory Discussion Channel</strong> established in Discuss.")),
            subtype_xmlid='mail.mt_note'
        )
        return channel.action_open_dental_channel()
