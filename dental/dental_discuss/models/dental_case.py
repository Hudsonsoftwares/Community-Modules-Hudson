# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from markupsafe import Markup


class DentalCase(models.Model):
    _inherit = 'dental.case'

    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Case Discussion Channel',
        copy=False,
        help="Linked Discuss channel for clinical peer consultations and treatment planning discussions."
    )
    discuss_channel_count = fields.Integer(
        string='Case Discussions',
        compute='_compute_discuss_channel_count'
    )

    def _compute_discuss_channel_count(self):
        for rec in self:
            count = self.env['discuss.channel'].search_count([('dental_case_id', '=', rec.id)])
            rec.discuss_channel_count = count

    def action_open_case_channel(self):
        """Open existing case channel or create a clinical discussion thread."""
        self.ensure_one()
        if self.discuss_channel_id:
            return self.discuss_channel_id.action_open_dental_channel()

        channel_name = f"Case {self.name} - {self.patient_id.name}"
        doctor_partner = self.doctor_id.sudo().user_id.partner_id if self.doctor_id and self.doctor_id.sudo().user_id else self.env['res.partner']
        
        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='clinical',
            name=channel_name,
            partners=doctor_partner | self.env.user.partner_id,
            company_id=self.company_id.id if hasattr(self, 'company_id') and self.company_id else False,
            is_phi=True,
            extra_vals={
                'dental_case_id': self.id,
                'dental_patient_id': self.patient_id.id,
                'dental_department': 'general',
            }
        )
        self.discuss_channel_id = channel
        
        # Post initial case introduction
        welcome_msg = _(
            "<div class='o_dental_discuss_case_intro' style='padding: 8px; border-left: 4px solid #714B67; background-color: #faf5f8;'>"
            "<strong>🦷 Clinical Case Discussion Started</strong><br/>"
            "Case: <b>%(case)s</b> | Patient: <b>%(patient)s</b><br/>"
            "Chief Complaint: %(complaint)s<br/>"
            "Attending Doctor: %(doctor)s<br/>"
            "<em>Protected Health Information - Confidential Medical Record Discussion</em>"
            "</div>",
            case=self.name,
            patient=self.patient_id.name,
            complaint=self.chief_complaint or _('General Consultation'),
            doctor=self.doctor_id.name if self.doctor_id else _('Unassigned')
        )
        channel.post_dental_message(welcome_msg, author_partner=self.env.user.partner_id)

        # Audit trail on record chatter
        self.message_post(
            body=Markup(_("🔒 <strong>Clinical Discuss Channel</strong> initialized for peer review and consultation.")),
            subtype_xmlid='mail.mt_note'
        )
        return channel.action_open_dental_channel()

    def action_open_case_discuss_wizard(self):
        """Launches peer consultation wizard allowing doctor to invite specific colleagues or specialists."""
        self.ensure_one()
        return {
            'name': _('Start Clinical Peer Consultation'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.case.discuss.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id if self.doctor_id else False,
            }
        }
