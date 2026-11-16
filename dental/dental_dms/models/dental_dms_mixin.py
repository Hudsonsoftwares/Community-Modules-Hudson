# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

from .const import CONSENT_KEYWORDS, IMAGING_KEYWORDS, IMAGING_MIMETYPES, IMAGING_MIMETYPES_PREFIX


class DentalDmsDocumentMixin(models.AbstractModel):
    """Behaviour added to every business record whose documents are filed in the DMS.

    A model becomes a "dental document source" by inheriting this mixin and, when needed,
    overriding the three ``_dental_dms_*`` hooks:

    * ``_dental_dms_folder_type(attachment)``: document category (False = do not file)
    * ``_dental_dms_links()``: dms.file relationship values (patient, case, ...)
    * ``_dental_dms_document_domain()``: which dms.files the smart button shows
    """
    _name = 'dental.dms.document.mixin'
    _description = 'Dental Documents Mixin'

    _dental_dms_default_type = 'patient'

    dental_document_count = fields.Integer(string='Documents', compute='_compute_dental_document_count')

    # ------------------------------------------------------------------ hooks
    def _dental_dms_routable_fields(self):
        """Binary fields (res_field) whose attachment is a real document worth filing."""
        return set()

    def _dental_dms_folder_type(self, attachment):
        self.ensure_one()
        return self._dental_dms_guess_type(attachment, self._dental_dms_default_type)

    @api.model
    def _dental_dms_guess_type(self, attachment, default):
        """Refine a clinical category from the file itself (images / X-rays, consent forms)."""
        name = (attachment.name or '').lower()
        if any(word in name for word in CONSENT_KEYWORDS):
            return 'consent'
        mimetype = attachment.mimetype or ''
        if default in ('clinical', 'treatment', 'patient') and (
                mimetype.startswith(IMAGING_MIMETYPES_PREFIX) or mimetype in IMAGING_MIMETYPES
                or any(word in name for word in IMAGING_KEYWORDS)):
            return 'imaging'
        return default

    def _dental_dms_m2o(self, field_name, comodel):
        field = self._fields.get(field_name)
        if field and field.type == 'many2one' and field.comodel_name == comodel:
            return self[field_name].id
        return False

    def _dental_dms_links(self):
        self.ensure_one()
        tooth = False
        for fname in ('tooth_reference', 'tooth_number'):
            if fname in self._fields and self[fname]:
                tooth = self[fname]
                break
        return {
            'dental_patient_id': self._dental_dms_m2o('patient_id', 'res.partner'),
            'dental_case_id': self._dental_dms_m2o('case_id', 'dental.case'),
            'dental_appointment_id': self._dental_dms_m2o('appointment_id', 'dental.appointment'),
            'dental_examination_id': self._dental_dms_m2o('examination_id', 'dental.clinical.examination'),
            'dental_treatment_plan_id': (self._dental_dms_m2o('treatment_plan_id', 'dental.treatment.plan')
                                         or self._dental_dms_m2o('plan_id', 'dental.treatment.plan')),
            'dental_tooth_reference': tooth,
        }

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return [('dental_source_model', '=', self._name), ('dental_source_id', '=', self.id)]

    # ------------------------------------------------------------------ UI
    def _compute_dental_document_count(self):
        DmsFile = self.env['dms.file']
        for record in self:
            record.dental_document_count = DmsFile.search_count(record._dental_dms_document_domain()) \
                if record.id else 0

    def action_dental_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dental_dms.action_dental_documents_record')
        action.update({
            'name': _('Documents - %s', self.display_name),
            'domain': self._dental_dms_document_domain(),
            'context': {'create': False, 'dental_dms_res_model': self._name, 'dental_dms_res_id': self.id},
        })
        return action

    def action_dental_add_document(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Document'),
            'res_model': 'dental.dms.upload.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id,
                        'default_doc_type': self._dental_dms_folder_type(self.env['ir.attachment'])},
        }
