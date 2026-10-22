# -*- encoding: utf-8 -*-
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EhHrFaceEnrolment(models.TransientModel):
    _name = 'eh.hr.face.enrolment'
    _description = 'Face Enrolment Wizard'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
    )
    consent_state = fields.Selection(
        related='employee_id.eh_face_consent_state',
        readonly=True,
    )
    consent_text = fields.Text(
        string='Consent text',
        compute='_compute_consent_text',
        store=False,
    )
    consent_acknowledged = fields.Boolean(
        string='Employee acknowledged consent',
        default=False,
    )
    samples_json = fields.Text(
        string='Captured samples (JSON)',
        help="Filled in by the OWL widget after the operator captures three to five samples.",
    )
    sample_count = fields.Integer(
        string='Sample count',
        compute='_compute_sample_count',
    )
    captured_via = fields.Selection(
        [
            ('hr_admin', 'HR administrator'),
            ('kiosk_screen', 'Kiosk screen'),
            ('portal', 'Self-service portal'),
        ],
        string='Captured via',
        default='hr_admin',
        required=True,
    )

    @api.depends('employee_id')
    def _compute_consent_text(self):
        for wizard in self:
            company = wizard.employee_id.company_id or self.env.company
            wizard.consent_text = company.eh_hr_consent_text_face or ''

    @api.depends('samples_json')
    def _compute_sample_count(self):
        for wizard in self:
            try:
                samples = json.loads(wizard.samples_json or '[]')
                wizard.sample_count = len(samples) if isinstance(samples, list) else 0
            except (ValueError, TypeError):
                wizard.sample_count = 0

    def action_grant_consent_and_enrol(self):
        self.ensure_one()
        if not self.consent_acknowledged:
            raise UserError(_("Tick the consent acknowledgement box before enrolling."))
        if not self.employee_id:
            raise UserError(_("Select an employee."))
        try:
            samples = json.loads(self.samples_json or '[]')
        except (ValueError, TypeError) as err:
            raise UserError(_("Captured samples are not valid JSON: %s") % err)
        if not isinstance(samples, list) or len(samples) < 1:
            raise UserError(_("Capture at least one sample before enrolling. Three to five recommended."))

        Consent = self.env['eh.hr.consent'].sudo()
        existing = Consent.search([
            ('employee_id', '=', self.employee_id.id),
            ('consent_type', '=', 'face'),
            ('state', '=', 'granted'),
        ], limit=1)
        if existing:
            consent = existing
        else:
            consent = Consent.create({
                'employee_id': self.employee_id.id,
                'consent_type': 'face',
                'granted_via': self.captured_via,
                'consent_text': self.consent_text,
                'company_id': self.employee_id.company_id.id or self.env.company.id,
            })
            consent.action_grant()

        Template = self.env['eh.hr.face.template'].sudo()
        created = self.env['eh.hr.face.template']
        for sample in samples:
            embedding = sample.get('embedding') if isinstance(sample, dict) else sample
            quality = sample.get('quality') if isinstance(sample, dict) else None
            if not isinstance(embedding, list):
                continue
            tpl = Template.create({
                'employee_id': self.employee_id.id,
                'consent_id': consent.id,
                'embedding': json.dumps(embedding),
                'embedding_dim': len(embedding),
                'quality_score': quality,
                'captured_via': self.captured_via,
                'company_id': self.employee_id.company_id.id or self.env.company.id,
            })
            created |= tpl

        self.env['eh.hr.kiosk.event'].sudo().log(
            'consent_grant',
            employee_id=self.employee_id.id,
            notes='Enrolment via wizard, %d sample(s) stored' % len(created),
            ref_model='eh.hr.consent',
            ref_id=consent.id,
            company_id=consent.company_id.id,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Face enrolled'),
                'message': _("Stored %(count)s sample(s) for %(name)s. Match confidence improves with three to five samples in varied lighting.") % {
                    'count': len(created),
                    'name': self.employee_id.name,
                },
                'type': 'success',
                'sticky': False,
            },
        }
