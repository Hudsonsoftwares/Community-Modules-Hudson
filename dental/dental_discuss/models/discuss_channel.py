# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from markupsafe import Markup


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    dental_channel_type = fields.Selection([
        ('clinical', 'Dentist-to-Dentist Clinical Consult'),
        ('coordination', 'Receptionist-to-Doctor Coordination'),
        ('department', 'Department Channel'),
        ('lab', 'Dental Laboratory Discussion'),
        ('pharmacy', 'Dental Pharmacy Discussion'),
        ('referral', 'Specialist Referral & Opinion'),
        ('announcement', 'Administrative Announcement (Read-Only)'),
        ('general', 'General Dental Hospital'),
    ], string='Dental Channel Type', default=None, index=True,
       help="Categorization for Dental Hospital ERP communication workflows.")

    dental_department = fields.Selection([
        ('general', 'General Dentistry'),
        ('ortho', 'Orthodontics'),
        ('endo', 'Endodontics'),
        ('perio', 'Periodontics & Implantology'),
        ('prosth', 'Prosthodontics & Aesthetics'),
        ('oral_surgery', 'Oral & Maxillofacial Surgery'),
        ('pediatric', 'Pediatric Dentistry'),
        ('reception', 'Front Desk & Reception'),
        ('lab', 'Dental Laboratory'),
        ('pharmacy', 'Hospital Pharmacy'),
        ('management', 'Clinic Management'),
    ], string='Dental Department', index=True)

    company_id = fields.Many2one(
        'res.company',
        string='Clinic / Branch',
        index=True,
        help="Branch owning this channel. Leave empty for hospital-wide channels."
    )

    is_confidential_phi = fields.Boolean(
        string='Confidential PHI',
        default=False,
        index=True,
        help="Indicates whether this channel discusses Protected Health Information (PHI). "
             "Restricts access strictly to authorized healthcare personnel."
    )

    # Linked Clinical & Operational Records
    dental_patient_id = fields.Many2one(
        'res.partner',
        string='Dental Patient',
        domain=[('is_dental_patient', '=', True)],
        index=True,
        help="Linked dental patient."
    )
    dental_case_id = fields.Many2one(
        'dental.case',
        string='Dental Case',
        check_company=True,
        index=True,
        help="Linked dental case history."
    )
    dental_appointment_id = fields.Many2one(
        'dental.appointment',
        string='Appointment',
        check_company=True,
        index=True,
        help="Linked dental appointment."
    )
    dental_examination_id = fields.Many2one(
        'dental.clinical.examination',
        string='Clinical Consultation',
        check_company=True,
        index=True,
        help="Linked clinical examination."
    )
    dental_lab_order_id = fields.Many2one(
        'dental.lab.order',
        string='Lab Work Order',
        check_company=True,
        index=True,
        help="Linked dental laboratory work order."
    )
    dental_prescription_id = fields.Many2one(
        'dental.prescription',
        string='Prescription',
        check_company=True,
        index=True,
        help="Linked pharmacy prescription."
    )
    dental_second_opinion_id = fields.Many2one(
        'dental.second.opinion',
        string='Specialist Referral',
        check_company=True,
        index=True,
        help="Linked second opinion / specialist referral."
    )

    @api.model
    def get_or_create_dental_channel(self, channel_type, name, partners=None, users=None,
                                     company_id=None, group_id=None, is_readonly=False,
                                     is_phi=False, extra_vals=None):
        """Reusable factory to locate or create a dental discussion channel and invite members."""
        domain = [('dental_channel_type', '=', channel_type)]
        if extra_vals:
            for field in ('dental_case_id', 'dental_appointment_id', 'dental_lab_order_id',
                          'dental_prescription_id', 'dental_second_opinion_id', 'dental_department'):
                if field in extra_vals and extra_vals[field]:
                    domain.append((field, '=', extra_vals[field]))

        if company_id:
            domain.append(('company_id', '=', company_id))
        else:
            domain.append(('company_id', '=', False))

        channel = self.search(domain, limit=1)
        if not channel:
            vals = {
                'name': name,
                'channel_type': 'channel' if group_id or not partners else 'group',
                'dental_channel_type': channel_type,
                'company_id': company_id or False,
                'is_readonly': is_readonly,
                'is_confidential_phi': is_phi,
            }
            if group_id:
                vals['group_public_id'] = group_id
            if extra_vals:
                vals.update(extra_vals)

            channel = self.sudo().create(vals)

        # Add requested members
        target_partners = partners or self.env['res.partner']
        if users:
            target_partners |= users.mapped('partner_id')
        if target_partners:
            channel.sudo()._add_members(partners=target_partners)

        return channel

    def post_dental_message(self, body_html, subject=None, author_partner=None):
        """Posts a message to the channel and triggers bus/push updates."""
        self.ensure_one()
        post_kwargs = {
            'body': Markup(body_html),
            'message_type': 'comment',
            'subtype_xmlid': 'mail.mt_comment',
        }
        if subject:
            post_kwargs['subject'] = subject
        if author_partner:
            post_kwargs['author_id'] = author_partner.id

        return self.sudo().message_post(**post_kwargs)

    def action_open_dental_channel(self):
        """Action for smart buttons and wizards to open this channel in Discuss."""
        self.ensure_one()
        # Ensure current user is a member so it appears in their channel panel
        if self.env.user.partner_id not in self.channel_member_ids.mapped('partner_id'):
            self.sudo()._add_members(users=self.env.user)
        return self.open_chat_window_action()

    def action_log_to_record_chatter(self):
        """Opens wizard to log decisions or notes from this channel to the linked clinical record chatter."""
        self.ensure_one()
        return {
            'name': _('Log Channel Discussion to Clinical Record Chatter'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.log.chatter.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_channel_id': self.id,
                'default_patient_id': self.dental_patient_id.id if self.dental_patient_id else False,
                'default_case_id': self.dental_case_id.id if self.dental_case_id else False,
                'default_appointment_id': self.dental_appointment_id.id if self.dental_appointment_id else False,
                'default_lab_order_id': self.dental_lab_order_id.id if self.dental_lab_order_id else False,
                'default_prescription_id': self.dental_prescription_id.id if self.dental_prescription_id else False,
                'default_second_opinion_id': self.dental_second_opinion_id.id if self.dental_second_opinion_id else False,
            }
        }
