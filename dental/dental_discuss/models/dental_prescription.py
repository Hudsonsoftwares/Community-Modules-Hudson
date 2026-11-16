# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from markupsafe import Markup


class DentalPrescription(models.Model):
    _inherit = 'dental.prescription'

    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Pharmacy Discuss Channel',
        copy=False,
        help="Linked Discuss channel for pharmacist-dentist clinical medication coordination."
    )
    discuss_channel_count = fields.Integer(
        string='Pharmacy Discussions',
        compute='_compute_discuss_channel_count'
    )

    def _compute_discuss_channel_count(self):
        for rec in self:
            count = self.env['discuss.channel'].search_count([('dental_prescription_id', '=', rec.id)])
            rec.discuss_channel_count = count

    def action_open_pharmacy_channel(self):
        """Open or create a dedicated channel between doctor and dispensing pharmacy."""
        self.ensure_one()
        if self.discuss_channel_id:
            return self.discuss_channel_id.action_open_dental_channel()

        channel_name = f"Rx {self.name} - {self.patient_id.name}"
        dentist = self.dentist_id if hasattr(self, 'dentist_id') and self.dentist_id else (
            self.doctor_id if hasattr(self, 'doctor_id') and self.doctor_id else False
        )
        doctor_partner = dentist.sudo().user_id.partner_id if dentist and dentist.sudo().user_id else self.env['res.partner']

        # Get Pharmacists as auto-members
        pharmacy_group = self.env.ref('dental_pharmacy.group_dental_pharmacist', raise_if_not_found=False)
        pharmacy_partners = pharmacy_group.user_ids.mapped('partner_id') if pharmacy_group else self.env['res.partner']

        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='pharmacy',
            name=channel_name,
            partners=doctor_partner | pharmacy_partners | self.env.user.partner_id,
            company_id=self.company_id.id if hasattr(self, 'company_id') and self.company_id else False,
            is_phi=True,
            extra_vals={
                'dental_prescription_id': self.id,
                'dental_patient_id': self.patient_id.id,
                'dental_case_id': self.case_id.id if hasattr(self, 'case_id') and self.case_id else False,
                'dental_department': 'pharmacy',
            }
        )
        self.discuss_channel_id = channel

        # Post introductory details
        allergies_text = self.patient_allergies or _('None recorded')
        intro_html = _(
            "<div class='o_dental_discuss_pharmacy_intro' style='padding: 8px; border-left: 4px solid #5BC0DE; background-color: #f4fafc;'>"
            "<strong>💊 Hospital Pharmacy Prescription Discussion</strong><br/>"
            "Prescription: <b>%(rx)s</b> | Patient: <b>%(patient)s</b><br/>"
            "Prescribing Doctor: %(doctor)s<br/>"
            "Allergies / Alerts: %(allergies)s<br/>"
            "<em>Discuss dosage clarifications, stock alternatives, and dispensing notes here.</em>"
            "</div>",
            rx=self.name,
            patient=self.patient_id.name,
            doctor=self.doctor_id.name if hasattr(self, 'doctor_id') and self.doctor_id else _('Doctor'),
            allergies=allergies_text
        )
        channel.post_dental_message(intro_html, author_partner=self.env.user.partner_id)

        self.message_post(
            body=Markup(_("💬 <strong>Pharmacy Consultation Channel</strong> established in Discuss.")),
            subtype_xmlid='mail.mt_note'
        )
        return channel.action_open_dental_channel()
