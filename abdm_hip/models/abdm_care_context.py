from odoo import api, fields, models
from odoo.exceptions import UserError

HI_TYPE_SELECTION = [
    ('OPConsultation', 'OP Consultation'),
    ('Prescription', 'Prescription'),
    ('DiagnosticReport', 'Diagnostic Report'),
    ('DischargeSummary', 'Discharge Summary'),
    ('ImmunizationRecord', 'Immunization Record'),
    ('HealthDocumentRecord', 'Health Document'),
    ('WellnessRecord', 'Wellness Record'),
    ('Invoice', 'Invoice'),
]


class AbdmCareContext(models.Model):
    """One episode of care (e.g. a dental case) that can be linked to an ABHA.

    ABDM never stores records: it only knows that "patient X has care context
    REF at facility Y". The records themselves are built on demand by the
    source record (``res_model`` / ``res_id``) when a consented request comes.
    """
    _name = 'abdm.care.context'
    _description = 'ABDM Care Context'
    _order = 'id desc'
    _rec_name = 'display'

    reference = fields.Char(required=True, index=True, readonly=True,
                            help='Care context reference shared with ABDM (unique in the facility).')
    display = fields.Char(required=True, help='Label the patient sees in the ABHA app.')
    partner_id = fields.Many2one('res.partner', string='Patient', required=True, index=True,
                                 ondelete='restrict', readonly=True)
    company_id = fields.Many2one('res.company', string='Facility', required=True, readonly=True,
                                 default=lambda self: self.env.company)
    hip_id = fields.Char(related='company_id.abdm_hip_id', string='HFR ID')
    res_model = fields.Char(required=True, readonly=True, index=True)
    res_id = fields.Many2oneReference(model_field='res_model', required=True, readonly=True, index=True)
    hi_types = fields.Char(string='Record Types', readonly=True,
                           help='Comma-separated ABDM health-information types.')
    state = fields.Selection([
        ('not_linked', 'Not Linked'),
        ('linking', 'Linking...'),
        ('linked', 'Linked'),
        ('error', 'Error'),
    ], default='not_linked', required=True, index=True, readonly=True)
    linked_date = fields.Datetime(readonly=True)
    link_method = fields.Selection([
        ('hip', 'By the clinic'),
        ('patient', 'By the patient (ABHA app)'),
    ], readonly=True)
    linked_abha_address = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)
    last_notified = fields.Datetime(string='Last New-Data Notification', readonly=True)

    _reference_uniq = models.Constraint('UNIQUE(company_id, reference)',
                                        'Care context reference must be unique per facility.')
    _source_uniq = models.Constraint('UNIQUE(res_model, res_id)',
                                     'A record can only be one care context.')

    def _source(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id).exists()

    def _hi_type_list(self):
        return [t for t in (self.hi_types or '').split(',') if t]

    def action_open_source(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model,
                'res_id': self.res_id, 'view_mode': 'form'}

    def action_link(self):
        return self._source()._abdm_link_care_context() if self._source() else False

    def action_notify_new_data(self):
        for cc in self:
            self.env['abdm.gateway']._hip_notify_context(cc)
        return True

    def _set_linked(self, method, abha_address=None):
        self.write({'state': 'linked', 'linked_date': fields.Datetime.now(), 'link_method': method,
                    'linked_abha_address': abha_address or self.partner_id.abha_address,
                    'error_message': False})
        for cc in self:
            source = cc._source()
            if source and hasattr(source, 'message_post'):
                source.message_post(body=self.env._(
                    "Linked to ABHA %s (care context %s).", cc.partner_id.abha_number or abha_address, cc.reference))

    def _abdm_records(self, hi_types=None, date_from=None, date_to=None):
        """FHIR records of this care context, filtered by type and date."""
        self.ensure_one()
        source = self._source()
        if not source:
            return []
        return source._abdm_health_records(hi_types=hi_types, date_from=date_from, date_to=date_to)


class AbdmCareContextMixin(models.AbstractModel):
    """Inherit on any record that is one episode of care (dental case, admission...).

    Implement ``_abdm_health_records(hi_types, date_from, date_to)`` returning
    ``[{'hi_type', 'reference', 'date', 'bundle'}]``; override the ``_abdm_cc_*``
    hooks when the defaults do not fit.
    """
    _name = 'abdm.care.context.mixin'
    _description = 'ABDM Care Context Source'

    abdm_care_context_id = fields.Many2one('abdm.care.context', compute='_compute_abdm_care_context',
                                           string='ABDM Care Context')
    abdm_link_state = fields.Selection([
        ('not_linked', 'Not Linked'),
        ('linking', 'Linking...'),
        ('linked', 'Linked'),
        ('error', 'Error'),
    ], string='ABDM Link', compute='_compute_abdm_care_context')

    def _compute_abdm_care_context(self):
        contexts = self.env['abdm.care.context'].sudo().search([
            ('res_model', '=', self._name), ('res_id', 'in', self.ids)])
        by_id = {cc.res_id: cc for cc in contexts}
        for rec in self:
            cc = by_id.get(rec.id)
            rec.abdm_care_context_id = cc.id if cc else False
            rec.abdm_link_state = cc.state if cc else 'not_linked'

    # --- hooks -----------------------------------------------------------
    def _abdm_cc_patient(self):
        return self.partner_id

    def _abdm_cc_company(self):
        return self.company_id if 'company_id' in self._fields and self.company_id else self.env.company

    def _abdm_cc_reference(self):
        return self.display_name

    def _abdm_cc_display(self):
        return self.display_name

    def _abdm_cc_hi_types(self):
        return ['OPConsultation']

    def _abdm_health_records(self, hi_types=None, date_from=None, date_to=None):
        raise NotImplementedError()

    # --- helpers ---------------------------------------------------------
    def _abdm_ensure_care_context(self):
        """Create or refresh the care context of each record."""
        CareContext = self.env['abdm.care.context'].sudo()
        result = CareContext
        for rec in self:
            vals = {
                'display': rec._abdm_cc_display(),
                'hi_types': ','.join(rec._abdm_cc_hi_types()),
            }
            cc = rec.abdm_care_context_id.sudo()
            if cc:
                cc.write(vals)
            else:
                cc = CareContext.create(dict(
                    vals,
                    reference=rec._abdm_cc_reference(),
                    partner_id=rec._abdm_cc_patient().id,
                    company_id=rec._abdm_cc_company().id,
                    res_model=rec._name,
                    res_id=rec.id,
                ))
            result |= cc
        self.invalidate_recordset(['abdm_care_context_id'])
        return result

    def _abdm_link_care_context(self):
        """Clinic-initiated linking of these records to the patient's ABHA."""
        for rec in self:
            patient = rec._abdm_cc_patient()
            if not patient.abha_number and not patient.abha_address:
                raise UserError(self.env._(
                    "%s has no ABHA yet. Create or verify the ABHA on the patient first.", patient.display_name))
            company = rec._abdm_cc_company()
            if not company.abdm_hip_id:
                raise UserError(self.env._(
                    "The facility %s has no ABDM Facility ID (HFR) yet. "
                    "Enter it in Settings > ABDM.", company.display_name))
            if not rec._abdm_health_records():
                raise UserError(self.env._(
                    "Nothing to share yet for %s: complete an examination or issue a prescription first.",
                    rec.display_name))
        contexts = self._abdm_ensure_care_context()
        self.env['abdm.gateway']._hip_link_care_contexts(contexts)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'info', 'title': self.env._('Linking with ABDM'),
                       'message': self.env._('Request sent. The status changes to "Linked" when ABDM confirms.'),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }

    def action_abdm_link(self):
        return self._abdm_link_care_context()

    def action_abdm_open_care_context(self):
        self.ensure_one()
        cc = self.abdm_care_context_id
        if not cc:
            return False
        return {'type': 'ir.actions.act_window', 'res_model': 'abdm.care.context',
                'res_id': cc.id, 'view_mode': 'form'}

    @api.ondelete(at_uninstall=False)
    def _abdm_unlink_care_context(self):
        linked = self.env['abdm.care.context'].sudo().search([
            ('res_model', '=', self._name), ('res_id', 'in', self.ids), ('state', '=', 'linked')])
        if linked:
            raise UserError(self.env._(
                "These records are linked to the patient's ABHA and cannot be deleted. Archive or cancel them instead."))
