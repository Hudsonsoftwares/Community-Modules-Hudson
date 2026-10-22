# -*- encoding: utf-8 -*-
import json

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EhHrFaceTemplate(models.Model):
    _name = 'eh.hr.face.template'
    _description = 'Face Recognition Template'
    _inherit = ['mail.thread']
    _order = 'captured_on desc, id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    consent_id = fields.Many2one(
        'eh.hr.consent',
        string='Consent record',
        required=True,
        ondelete='restrict',
        domain="[('employee_id', '=', employee_id), ('consent_type', '=', 'face')]",
        tracking=True,
        help="The consent record under which this template was captured. Required by privacy design: no template exists without a granted consent.",
    )
    # The vector a kiosk matches against: with a device token it clocks this
    # employee in or out, so it is readable by the Admin role only, as on the
    # form. The auditor and the manager read the template as metadata. The
    # enrolment wizard and the match route handle it as superuser.
    embedding = fields.Text(
        string='Embedding',
        required=True,
        groups='eh_hr_attendance_base.group_eh_hr_admin',
        help="JSON-serialised 128-dim float array produced by face-api.js. Storing as Text rather than Binary keeps the database introspectable for diagnostics.",
    )
    embedding_dim = fields.Integer(string='Embedding length', default=128, readonly=True)
    model_name = fields.Char(
        string='Recognition model',
        default='face-api.js / face_recognition',
        readonly=True,
        help="Identity of the model that produced the embedding. Stored so future model upgrades can be reconciled (re-enrolment may be required if the dimension or training set changes).",
    )
    model_version = fields.Char(string='Model version')
    captured_on = fields.Datetime(
        string='Captured on',
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
    captured_via = fields.Selection(
        [
            ('kiosk_screen', 'Kiosk screen'),
            ('hr_admin', 'HR administrator'),
            ('portal', 'Self-service portal'),
        ],
        string='Captured via',
        default='hr_admin',
        readonly=True,
    )
    quality_score = fields.Float(
        string='Quality score',
        digits=(4, 4),
        help="Optional. Higher is better. The kiosk only stores templates above the company's quality floor.",
    )
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    @api.depends('employee_id', 'captured_on')
    def _compute_name(self):
        for record in self:
            who = record.employee_id.name or _('No employee')
            stamp = fields.Datetime.to_string(record.captured_on) if record.captured_on else ''
            record.name = ' / '.join(part for part in (who, stamp) if part) or _('New template')

    @api.constrains('embedding', 'embedding_dim')
    def _check_embedding(self):
        for record in self:
            if not record.embedding:
                raise ValidationError(_("Embedding is required."))
            try:
                values = json.loads(record.embedding)
            except (ValueError, TypeError) as err:
                raise ValidationError(_("Embedding must be a valid JSON array of floats: %s") % err)
            if not isinstance(values, list):
                raise ValidationError(_("Embedding must be a JSON list."))
            if record.embedding_dim and len(values) != record.embedding_dim:
                raise ValidationError(
                    _("Embedding length %(actual)s does not match declared dimension %(expected)s.") % {
                        'actual': len(values),
                        'expected': record.embedding_dim,
                    }
                )
            if not all(isinstance(v, (int, float)) for v in values):
                raise ValidationError(_("Embedding values must be numeric."))

    @api.constrains('consent_id')
    def _check_consent_face_type(self):
        for record in self:
            if record.consent_id.consent_type != 'face':
                raise ValidationError(_("A face template's consent record must be of type 'face'."))
            if record.consent_id.employee_id != record.employee_id:
                raise ValidationError(_("Consent record's employee must match the template's employee."))

    def action_deactivate(self):
        self.write({'active': False})

    def action_reactivate(self):
        for record in self:
            if record.consent_id.state != 'granted':
                raise ValidationError(_("Cannot reactivate a template whose consent is not in granted state."))
            record.active = True

    def get_embedding_as_list(self):
        self.ensure_one()
        return json.loads(self.embedding)
