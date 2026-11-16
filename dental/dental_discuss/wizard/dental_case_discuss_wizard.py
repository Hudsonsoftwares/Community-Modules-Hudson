# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from markupsafe import Markup


class DentalCaseDiscussWizard(models.TransientModel):
    _name = 'dental.case.discuss.wizard'
    _description = 'Start Dentist-to-Dentist Peer Consultation'

    case_id = fields.Many2one('dental.case', string='Dental Case', required=True)
    patient_id = fields.Many2one('res.partner', string='Patient', required=True)
    doctor_id = fields.Many2one('hr.employee.public', string='Attending Dentist')
    colleague_doctor_ids = fields.Many2many(
        'hr.employee.public',
        string='Consulting Dentists / Specialists',
        domain=[('is_dentist', '=', True)],
        required=True,
        help="Select one or more dentist colleagues to review and discuss this clinical case."
    )
    clinical_inquiry = fields.Text(
        string='Clinical Inquiry / Case Summary',
        required=True,
        help="Summarize the diagnosis, proposed treatment, or questions for peer review."
    )
    priority = fields.Selection([
        ('routine', 'Routine Consultation'),
        ('urgent', 'Urgent / Complex Case'),
    ], string='Priority', default='routine', required=True)

    def action_start_consultation(self):
        self.ensure_one()
        case = self.case_id
        
        # Collect partners
        colleague_users = self.colleague_doctor_ids.sudo().mapped('user_id')
        invited_partners = colleague_users.mapped('partner_id') | self.env.user.partner_id
        if self.doctor_id and self.doctor_id.sudo().user_id:
            invited_partners |= self.doctor_id.sudo().user_id.partner_id

        channel_name = f"Case {case.name} - {self.patient_id.name}"
        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='clinical',
            name=channel_name,
            partners=invited_partners,
            company_id=case.company_id.id if hasattr(case, 'company_id') and case.company_id else False,
            is_phi=True,
            extra_vals={
                'dental_case_id': case.id,
                'dental_patient_id': self.patient_id.id,
                'dental_department': 'general',
            }
        )
        case.discuss_channel_id = channel

        priority_label = "🔴 URGENT" if self.priority == 'urgent' else "🔵 Routine"
        inquiry_html = _(
            "<div class='o_dental_discuss_inquiry' style='padding: 8px; border-left: 4px solid #714B67; background-color: #faf5f8;'>"
            "<strong>🦷 Dentist-to-Dentist Clinical Consult Requested (%(priority)s)</strong><br/>"
            "Attending Doctor: %(doctor)s<br/>"
            "Invited Colleagues: %(colleagues)s<br/>"
            "<b>Clinical Inquiry:</b><br/>"
            "%(inquiry)s"
            "</div>",
            priority=priority_label,
            doctor=self.doctor_id.name if self.doctor_id else self.env.user.name,
            colleagues=", ".join(self.colleague_doctor_ids.mapped('name')),
            inquiry=self.clinical_inquiry.replace("\n", "<br/>")
        )
        channel.post_dental_message(inquiry_html, author_partner=self.env.user.partner_id)

        # Record in Case chatter
        case.message_post(
            body=Markup(_(
                "🔒 <strong>Peer Consultation Initialized</strong> with Dr. %(doctors)s.<br/>"
                "Inquiry: %(inquiry)s",
                doctors=", ".join(self.colleague_doctor_ids.mapped('name')),
                inquiry=self.clinical_inquiry
            )),
            subtype_xmlid='mail.mt_note'
        )

        return channel.action_open_dental_channel()
