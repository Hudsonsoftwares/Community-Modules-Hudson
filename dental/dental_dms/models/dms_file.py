# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .const import DOC_TYPES


class DmsFile(models.Model):
    """Dental relationship fields on DMS files.

    Purely additive: the file content, storage, revisions, approvals, sharing and every other DMS
    behaviour stay those of the Document module. These fields only describe *what* the file is
    about so dental screens can find it.
    """
    _inherit = 'dms.file'

    dental_source_model = fields.Char(string='Source Model', index=True, readonly=True, copy=False)
    dental_source_id = fields.Integer(string='Source Record ID', index=True, readonly=True, copy=False)
    dental_source_ref = fields.Reference(selection='_selection_dental_source_ref', string='Source Record',
                                         compute='_compute_dental_source_ref')
    dental_doc_type = fields.Selection(DOC_TYPES, string='Dental Document Type', index=True, copy=False)
    dental_patient_id = fields.Many2one('res.partner', string='Patient', index=True, copy=False,
                                        domain=[('is_dental_patient', '=', True)], ondelete='set null')
    dental_case_id = fields.Many2one('dental.case', string='Dental Case', index=True, copy=False, ondelete='set null')
    dental_appointment_id = fields.Many2one('dental.appointment', string='Appointment', index=True, copy=False,
                                            ondelete='set null')
    dental_examination_id = fields.Many2one('dental.clinical.examination', string='Consultation / Examination',
                                            index=True, copy=False, ondelete='set null')
    dental_treatment_plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', index=True,
                                               copy=False, ondelete='set null')
    dental_employee_id = fields.Many2one('hr.employee', string='Staff Member', index=True, copy=False,
                                         ondelete='set null')
    dental_tooth_reference = fields.Char(string='Tooth / Teeth', copy=False,
                                         help='FDI tooth number(s) the document relates to, e.g. "36" or "11,21".')
    dental_document_date = fields.Date(string='Document Date', copy=False)
    dental_notes = fields.Text(string='Clinical Notes', copy=False)

    # Dental records whose read access a linked document follows (patient privacy).
    _DENTAL_PRIVACY_FIELDS = ('dental_case_id', 'dental_examination_id', 'dental_treatment_plan_id',
                              'dental_appointment_id', 'dental_employee_id')

    def _check_access(self, operation):
        """Patient privacy on direct access by id.

        The ``dental_dms_file_*_privacy`` ir.access rows already filter every search. The DMS security
        mixin, however, makes ``filtered_domain`` return all records under sudo, so Odoo skips ir.access
        domains when records are read by id. For documents linked to a dental record only, re-apply
        the rule explicitly: the user must be able to read the linked case / consultation / plan /
        appointment / employee. Files without dental links keep the plain DMS behaviour.
        """
        result = super()._check_access(operation)
        if self.env.su or operation == 'create' or not self._ids:
            return result
        forbidden = result[0] if result else self.browse()
        denied = (self - forbidden)._dental_privacy_denied()
        if not denied:
            return result
        forbidden |= denied
        if result:
            return forbidden, result[1]
        return forbidden, lambda: AccessError(_(
            'You are not allowed to access these documents because you cannot access the dental '
            'record they belong to: %s', ', '.join(denied.sudo().mapped('name'))))

    def check_access(self, operation):
        # has_access() caches per-record access through sudo().filtered_domain(), which the DMS mixin
        # short-circuits; enforce the dental privacy rule here so that downloads (/web/content goes
        # through check_access) and write / unlink are protected as well.
        super().check_access(operation)
        if operation != 'create':
            self._dental_privacy_check()

    def read(self, fields=None, load='_classic_read'):
        # Odoo's fetch() re-reads "forbidden" records in sudo when has_access() says yes, which the DMS
        # mixin always does; check dental privacy before any by-id read (RPC read and web_read).
        self._dental_privacy_check()
        return super().read(fields, load=load)

    def _dental_privacy_check(self):
        if self.env.su or not self._ids:
            return
        denied = self._dental_privacy_denied()
        if denied:
            raise AccessError(_(
                'You are not allowed to access these documents because you cannot access the dental '
                'record they belong to: %s', ', '.join(denied.sudo().mapped('name'))))

    def _filtered_access(self, operation):
        # Same reason as _check_access: Odoo's own filtering relies on sudo().filtered_domain().
        result = super()._filtered_access(operation)
        if self.env.su or operation == 'create' or not result:
            return result
        return result - result._dental_privacy_denied()

    def _dental_privacy_denied(self):
        """Subset of ``self`` linked to a dental record the current user cannot read."""
        if self.env.su or not self._ids:
            return self.browse()
        candidates = self.sudo().exists()
        denied_ids = set()
        for fname in self._DENTAL_PRIVACY_FIELDS:
            linked = candidates.filtered(fname)
            if not linked:
                continue
            allowed_ids = set(linked.mapped(fname).with_env(self.env)._filtered_access('read').ids)
            denied_ids.update(linked.filtered(lambda f: f[fname].id not in allowed_ids).ids)
        return self.browse(list(denied_ids))

    # ------------------------------------------------------------------
    # Files uploaded / moved directly in the DMS into a dental folder
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._dental_sync_from_directory()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('directory_id'):
            self._dental_sync_from_directory()
        return res

    def _dental_sync_from_directory(self):
        """Inherit the document type and patient of the dental folder the file is in (when not set)."""
        for record in self.sudo():
            directory = record.directory_id
            if not directory.dental_doc_type:
                continue
            vals = {}
            if not record.dental_doc_type:
                vals['dental_doc_type'] = directory.dental_doc_type
            if not record.dental_patient_id and directory.dental_patient_id:
                vals['dental_patient_id'] = directory.dental_patient_id.id
            if vals:
                super(DmsFile, record.with_context(dms_skip_log=True)).write(vals)

    @api.model
    def _selection_dental_source_ref(self):
        return [(model, self.env[model]._description) for model in self.env
                if hasattr(self.env[model], '_dental_dms_folder_type')]

    @api.depends('dental_source_model', 'dental_source_id')
    def _compute_dental_source_ref(self):
        for rec in self:
            ref = False
            if rec.dental_source_model in self.env and rec.dental_source_id:
                ref = f'{rec.dental_source_model},{rec.dental_source_id}'
            rec.dental_source_ref = ref

    def action_dental_open_source(self):
        self.ensure_one()
        if not self.dental_source_ref:
            raise UserError(_('This document is not linked to a dental record.'))
        record = self.dental_source_ref
        record.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'res_model': record._name,
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }
