# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from markupsafe import Markup


class DentalSecondOpinion(models.Model):
    _inherit = 'dental.second.opinion'

    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Referral Discuss Channel',
        copy=False,
        help="Linked Discuss channel for specialist-dentist case evaluation and messaging."
    )
    discuss_channel_count = fields.Integer(
        string='Referral Discussions',
        compute='_compute_discuss_channel_count'
    )

    def _compute_discuss_channel_count(self):
        for rec in self:
            count = self.env['discuss.channel'].search_count([('dental_second_opinion_id', '=', rec.id)])
            rec.discuss_channel_count = count

    def action_open_referral_channel(self):
        """Open or create a dedicated channel between referring doctor and specialist."""
        self.ensure_one()
        if self.discuss_channel_id:
            return self.discuss_channel_id.action_open_dental_channel()

        channel_name = f"Referral {self.name} - {self.patient_id.name}"
        req_partner = self.requesting_doctor_id.user_id.partner_id if hasattr(self, 'requesting_doctor_id') and self.requesting_doctor_id and self.requesting_doctor_id.user_id else self.env['res.partner']
        spec_partner = self.specialist_id.user_id.partner_id if hasattr(self, 'specialist_id') and self.specialist_id and self.specialist_id.user_id else self.env['res.partner']

        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='referral',
            name=channel_name,
            partners=req_partner | spec_partner | self.env.user.partner_id,
            company_id=self.company_id.id if hasattr(self, 'company_id') and self.company_id else False,
            is_phi=True,
            extra_vals={
                'dental_second_opinion_id': self.id,
                'dental_patient_id': self.patient_id.id if hasattr(self, 'patient_id') else False,
                'dental_case_id': self.case_id.id if hasattr(self, 'case_id') and self.case_id else False,
                'dental_department': 'general',
            }
        )
        self.discuss_channel_id = channel

        intro_html = _(
            "<div class='o_dental_discuss_referral_intro' style='padding: 8px; border-left: 4px solid #D9534F; background-color: #fdf7f7;'>"
            "<strong>👨‍⚕️ Specialist Clinical Referral Discussion</strong><br/>"
            "Referral: <b>%(ref)s</b> | Patient: <b>%(patient)s</b><br/>"
            "Referring Doctor: %(req_doc)s | Specialist: %(spec)s<br/>"
            "Clinical Question: <em>%(question)s</em><br/>"
            "<em>Secure second opinion evaluation channel</em>"
            "</div>",
            ref=self.name,
            patient=self.patient_id.name if hasattr(self, 'patient_id') and self.patient_id else _('Patient'),
            req_doc=self.requesting_doctor_id.name if hasattr(self, 'requesting_doctor_id') and self.requesting_doctor_id else _('Dentist'),
            spec=self.specialist_id.name if hasattr(self, 'specialist_id') and self.specialist_id else _('Specialist'),
            question=self.clinical_question or _('Review of dental findings and treatment recommendation')
        )
        channel.post_dental_message(intro_html, author_partner=self.env.user.partner_id)

        self.message_post(
            body=Markup(_("🔒 <strong>Specialist Referral Discuss Channel</strong> initialized.")),
            subtype_xmlid='mail.mt_note'
        )
        return channel.action_open_dental_channel()

    def action_submit(self):
        """Extended submit: notifies specialist in Discuss when referral is submitted."""
        res = super().action_submit()
        for rec in self:
            rec.action_open_referral_channel()
        return res
