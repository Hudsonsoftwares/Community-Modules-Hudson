# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class DentalTreatmentPlan(models.Model):
    _inherit = 'dental.treatment.plan'

    sign_request_ids = fields.One2many(
        'hudson.sign.request',
        'dental_treatment_plan_id',
        string='Consent Requests',
    )
    sign_request_count = fields.Integer(
        string='Consent Count',
        compute='_compute_sign_request_count',
    )
    consent_status = fields.Selection([
        ('not_required', 'Not Required'),
        ('to_sign', 'Consent Required'),
        ('sent', 'Consent Sent'),
        ('signed', 'Consent Signed'),
    ], string='Consent Status', compute='_compute_consent_status', store=True, tracking=True)

    @api.depends('sign_request_ids', 'sign_request_ids.state', 'line_ids.treatment_id.is_consent_required')
    def _compute_sign_request_count(self):
        for plan in self:
            plan.sign_request_count = len(plan.sign_request_ids)

    @api.depends('sign_request_ids.state', 'line_ids.treatment_id.is_consent_required')
    def _compute_consent_status(self):
        for plan in self:
            requires_consent = any(plan.line_ids.mapped('treatment_id.is_consent_required'))
            if not requires_consent:
                plan.consent_status = 'not_required'
                continue

            active_requests = plan.sign_request_ids.filtered(lambda r: r.state != 'canceled')
            if not active_requests:
                plan.consent_status = 'to_sign'
            elif any(r.state == 'signed' for r in active_requests):
                plan.consent_status = 'signed'
            else:
                plan.consent_status = 'sent'

    def action_open_consent_wizard(self):
        """Open the professional consent signing wizard."""
        self.ensure_one()
        if not self.patient_id:
            raise UserError(_("Please assign a patient to this treatment plan."))

        # Pick default treatment that requires consent or first treatment
        default_treatment = False
        consent_lines = self.line_ids.filtered(lambda l: l.treatment_id.is_consent_required)
        if consent_lines:
            default_treatment = consent_lines[0].treatment_id
        elif self.line_ids:
            default_treatment = self.line_ids[0].treatment_id

        # Determine doctor partner
        doctor_partner = False
        if self.doctor_id and self.doctor_id.sudo().user_id and self.doctor_id.sudo().user_id.partner_id:
            doctor_partner = self.doctor_id.sudo().user_id.partner_id
        elif self.env.user.partner_id:
            doctor_partner = self.env.user.partner_id

        # Resolve template for this treatment
        template = False
        if default_treatment and default_treatment.consent_template_id:
            template = default_treatment.consent_template_id
        elif default_treatment:
            template = self.env['hudson.sign.template'].search([('treatment_id', '=', default_treatment.id)], limit=1)
        if not template:
            template = self.env['hudson.sign.template'].search([], limit=1)

        return {
            'name': _("Sign Treatment Consent"),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.consent.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_plan_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_doctor_partner_id': doctor_partner.id if doctor_partner else False,
                'default_treatment_id': default_treatment.id if default_treatment else False,
                'default_template_id': template.id if template else False,
            },
        }

    def action_view_consent_requests(self):
        """View all signature requests created for this treatment plan."""
        self.ensure_one()
        return {
            'name': _("Consent Signature Requests - %s", self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'hudson.sign.request',
            'view_mode': 'list,form',
            'domain': [('dental_treatment_plan_id', '=', self.id)],
            'context': {'default_dental_treatment_plan_id': self.id},
        }

