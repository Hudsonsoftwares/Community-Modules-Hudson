# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class DentalConsentWizard(models.TransientModel):
    _name = 'dental.consent.wizard'
    _description = 'Sign Treatment Consent Wizard'

    plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', required=True, readonly=True)
    patient_id = fields.Many2one('res.partner', string='Patient', required=True)
    doctor_partner_id = fields.Many2one('res.partner', string='Treating Dentist / Doctor')
    treatment_id = fields.Many2one('product.template', string='Treatment', domain="[('is_dental_treatment', '=', True)]")
    template_id = fields.Many2one('hudson.sign.template', string='Consent Template', required=True)
    sign_mode = fields.Selection([
        ('sign_now', 'Sign Now (In-Clinic Tablet / Screen)'),
        ('send_mail', 'Send via Email to Patient'),
    ], string='Signing Mode', default='sign_now', required=True)
    subject = fields.Char(string='Subject', default='Dental Treatment Informed Consent')
    message = fields.Text(string='Message / Instructions')

    @api.onchange('treatment_id')
    def _onchange_treatment_id(self):
        if self.treatment_id:
            tmpl = self.treatment_id.consent_template_id or self.env['hudson.sign.template'].search([('treatment_id', '=', self.treatment_id.id)], limit=1)
            if tmpl:
                self.template_id = tmpl
            self.subject = _("Informed Consent - %s", self.treatment_id.name)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id and not self.treatment_id and self.template_id.treatment_id:
            self.treatment_id = self.template_id.treatment_id

    def action_confirm_sign(self):
        self.ensure_one()
        if not self.template_id:
            raise UserError(_("Please select a consent template."))

        template = self.template_id
        template._check_has_fields()

        roles = template.sign_item_ids.role_id.sorted('sequence')
        signers = []
        patient_partner = self.patient_id
        doctor_partner = self.doctor_partner_id or self.env.user.partner_id

        # Make sure patient has dummy or real email for signer record if missing
        if not (patient_partner.email or '').strip():
            patient_partner.sudo().write({'email': f"patient_{patient_partner.id}@clinic.local"})

        for role in roles:
            role_name_lower = (role.name or '').lower()
            if 'dentist' in role_name_lower or 'doctor' in role_name_lower:
                signers.append((role, doctor_partner))
            else:
                signers.append((role, patient_partner))

        # Fallback if no specific role matched or single role
        if not signers and roles:
            signers = [(roles[0], patient_partner)]

        # Prepare send options
        options = {
            'subject': self.subject or _("Consent - %s", template.name),
            'message': self.message or f"Consent request for {self.patient_id.name} - Plan {self.plan_id.name}",
            'is_sign_now': (self.sign_mode == 'sign_now'),
            'signing_order': False,
            'reminders': False,
            'reminder_days': 7,
            'valid_until': False,
            'hide_certificate_key': True,
        }

        # Send/create signature request through Hudson Sign
        action = template._send_signature_request(signers, options)

        # Link generated signature request to dental treatment plan
        hudson_request = self.env['hudson.sign.request'].search([
            ('template_id', '=', template.id),
        ], order='create_date desc, id desc', limit=1)
        if hudson_request:
            hudson_request.write({
                'dental_treatment_plan_id': self.plan_id.id,
            })
            # Also ensure revision content is strictly populated from template
            if hudson_request.revision_id and not hudson_request.revision_id.content and template.attachment_id:
                raw_b = bytes(template.attachment_id.raw) if template.attachment_id.raw else b''
                if raw_b:
                    b64_str = base64.b64encode(raw_b).decode('ascii')
                    hudson_request.revision_id.sudo().write({'content': b64_str})

            # Also tag the revision/file in DMS under the patient and treatment plan
            if hudson_request.revision_id and hudson_request.revision_id.file_id:
                dms_file = hudson_request.revision_id.file_id
                if not dms_file.content and template.attachment_id:
                    raw_b = bytes(template.attachment_id.raw) if template.attachment_id.raw else b''
                    if raw_b:
                        b64_str = base64.b64encode(raw_b).decode('ascii')
                        dms_file.sudo().write({'content': b64_str})
                dms_file.write({
                    'dental_treatment_plan_id': self.plan_id.id,
                    'dental_patient_id': self.patient_id.id,
                    'dental_case_id': self.plan_id.case_id.id if self.plan_id.case_id else False,
                    'dental_doc_type': 'consent',
                })

        # Post message in chatter
        self.plan_id.message_post(
            body=_("Consent process initiated for treatment <b>%s</b> using template <i>%s</i> (Mode: %s).",
                   self.treatment_id.name if self.treatment_id else template.name,
                   template.name,
                   'Sign Now' if self.sign_mode == 'sign_now' else 'Sent via Email')
        )

        # If sign_now and an act_url was returned, open signing screen immediately
        if self.sign_mode == 'sign_now' and isinstance(action, dict) and action.get('type') == 'ir.actions.act_url':
            return action

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Consent Request Created"),
                'message': _("Consent form for %s has been created successfully.", self.patient_id.name),
                'type': 'success',
                'sticky': False,
            }
        }
