# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, models
from odoo.addons.dms.tools import file as dms_file_tools

from .const import DOC_TYPES, FOLDER_PERMISSIONS, PERM_LETTERS, ROOT_FOLDER_NAME

_logger = logging.getLogger(__name__)

# Fields written on a dms.file from the source record (see dental.dms.document.mixin._dental_dms_links)
LINK_FIELDS = (
    'dental_patient_id', 'dental_case_id', 'dental_appointment_id', 'dental_examination_id',
    'dental_treatment_plan_id', 'dental_employee_id', 'dental_tooth_reference', 'dental_document_date',
)
# Extra values the "Add Document" wizard can pass through the context
EXTRA_FIELDS = ('dental_document_date', 'dental_notes', 'dental_tooth_reference')
_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_name(name, default='Document'):
    """Return a name the DMS accepts as a file / folder name on every OS."""
    name = _INVALID_NAME_CHARS.sub('-', name or '').strip().strip('.')
    return name[:200] or default


class DentalDmsService(models.AbstractModel):
    """Integration layer between dental records and the Document Management System.

    Only uses public DMS APIs: dms.directory / dms.file / dms.directory.permission create & search,
    the enterprise per-company storage helper and the DMS ``unique_name`` tool. Files are created
    with ``attachment_id`` so the DMS serves the original attachment: nothing is copied.
    """
    _name = 'dental.dms.service'
    _description = 'Dental Document Routing Service'

    # ------------------------------------------------------------------
    # Configuration hooks (extended by dental_dms_* modules)
    # ------------------------------------------------------------------
    @api.model
    def _get_doc_types(self):
        return dict(self.env['dms.file']._fields['dental_doc_type']._description_selection(self.env))

    @api.model
    def _get_folder_permissions(self):
        """Return {doc_type: {dms.access.group xmlid: permission letters}}."""
        return {key: dict(value) for key, value in FOLDER_PERMISSIONS.items()}

    @api.model
    def _get_category_sequence(self):
        return [key for key, _label in DOC_TYPES]

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------
    @api.model
    def _get_root_folder(self, company):
        Directory = self.env['dms.directory'].sudo().with_context(active_test=False)
        root = Directory.search([('dental_folder_role', '=', 'root'), ('company_id', '=', company.id)], limit=1)
        if root:
            if root.is_trashed:
                root.write({'is_trashed': False})
            return root
        storage = Directory._get_or_create_company_storage(company)
        name = ROOT_FOLDER_NAME
        if Directory.search_count([('is_root_directory', '=', True), ('storage_id', '=', storage.id),
                                   ('name', '=', name)]):
            name = f'{ROOT_FOLDER_NAME} ({company.name})'
        return Directory.with_context(check_name=False).create({
            'name': name,
            'is_root_directory': True,
            'storage_id': storage.id,
            'company_id': company.id,
            'dental_folder_role': 'root',
        })

    @api.model
    def _get_category_folder(self, company, doc_type):
        Directory = self.env['dms.directory'].sudo().with_context(active_test=False)
        root = self._get_root_folder(company)
        folder = Directory.search([('parent_id', '=', root.id), ('dental_folder_role', '=', 'category'),
                                   ('dental_doc_type', '=', doc_type)], limit=1)
        if folder:
            return folder
        label = self._get_doc_types().get(doc_type, doc_type)
        names = root.child_directory_ids.mapped('name')
        folder = Directory.with_context(check_name=False).create({
            'name': dms_file_tools.unique_name(label, names) if label in names else label,
            'parent_id': root.id,
            'company_id': company.id,
            'dental_folder_role': 'category',
            'dental_doc_type': doc_type,
        })
        self._sync_folder_permissions(folder)
        return folder

    @api.model
    def _ensure_category_folders(self, company):
        for doc_type in self._get_doc_types():
            folder = self._get_category_folder(company, doc_type)
            self._sync_folder_permissions(folder)

    @api.model
    def _sync_folder_permissions(self, folder):
        """Make sure the category folder carries the permission lines of the matrix (idempotent).

        Lines are added, never removed, so permissions granted manually by a DMS manager are kept.
        """
        matrix = self._get_folder_permissions().get(folder.dental_doc_type, {})
        Permission = self.env['dms.directory.permission'].sudo()
        for group_xmlid, letters in matrix.items():
            group = self.env.ref(group_xmlid if '.' in group_xmlid else f'dental_dms.{group_xmlid}',
                                 raise_if_not_found=False)
            if not group:
                continue
            vals = {}
            for letter in letters:
                for perm in PERM_LETTERS.get(letter, ()):
                    vals[perm] = True
            line = Permission.search([('directory_id', '=', folder.id), ('group_id', '=', group.id)], limit=1)
            if line:
                missing = {k: v for k, v in vals.items() if not line[k]}
                if missing:
                    line.write(missing)
            else:
                Permission.create(dict(vals, directory_id=folder.id, group_id=group.id))

    @api.model
    def _get_subject(self, record, links):
        """Return (res_model, res_id, folder name, patient) of the per-subject sub-folder, or False."""
        patient = self.env['res.partner'].browse(links.get('dental_patient_id') or [])
        if patient:
            code = patient.dental_patient_id if patient.dental_patient_id not in (False, 'New') else False
            name = f'{code} - {patient.name}' if code else f'{patient.name} (#{patient.id})'
            return 'res.partner', patient.id, name, patient
        employee = self.env['hr.employee'].browse(links.get('dental_employee_id') or [])
        if employee:
            return 'hr.employee', employee.id, f'{employee.name} (#{employee.id})', False
        if record and record._name not in ('res.partner',):
            return record._name, record.id, record.display_name or f'{record._description} #{record.id}', False
        return False

    @api.model
    def _get_target_folder(self, company, doc_type, record, links):
        category = self._get_category_folder(company, doc_type)
        if doc_type == 'admin':
            return category
        subject = self._get_subject(record, links)
        if not subject:
            return category
        res_model, res_id, name, patient = subject
        Directory = self.env['dms.directory'].sudo().with_context(active_test=False)
        folder = Directory.search([('parent_id', '=', category.id), ('res_model', '=', res_model),
                                   ('res_id', '=', res_id)], limit=1)
        if folder:
            return folder
        name = clean_name(name, default=f'#{res_id}')
        names = category.child_directory_ids.mapped('name')
        if name in names:
            name = dms_file_tools.unique_name(name, names)
        return Directory.with_context(check_name=False).create({
            'name': name,
            'parent_id': category.id,
            'company_id': company.id,
            'res_model': res_model,
            'res_id': res_id,
            'dental_folder_role': 'subject',
            'dental_doc_type': doc_type,
            'dental_patient_id': patient.id if patient else False,
        })

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    @api.model
    def _is_dental_source(self, res_model):
        return bool(res_model) and res_model in self.env and hasattr(self.env[res_model], '_dental_dms_folder_type')

    @api.model
    def _route_attachment(self, attachment, doc_type=None, extra=None):
        """File one ir.attachment of a dental record into the DMS. Returns the dms.file or False.

        Never raises: document filing must not block a clinical or billing workflow.
        """
        try:
            with self.env.cr.savepoint():
                return self._route_attachment_unsafe(attachment, doc_type=doc_type, extra=extra)
        except Exception:  # noqa: BLE001
            _logger.exception('Dental DMS: could not file attachment %s (%s,%s)',
                              attachment.id, attachment.res_model, attachment.res_id)
            return False

    @api.model
    def _route_attachment_unsafe(self, attachment, doc_type=None, extra=None):
        attachment = attachment.sudo()
        if not attachment.res_id or not self._is_dental_source(attachment.res_model):
            return False
        Model = self.env[attachment.res_model].sudo()
        if attachment.res_field and attachment.res_field not in Model._dental_dms_routable_fields():
            return False
        record = Model.browse(attachment.res_id).exists()
        if not record:
            return False
        doc_type = doc_type or record._dental_dms_folder_type(attachment)
        if not doc_type:
            return False
        links = record._dental_dms_links()
        vals = {k: v for k, v in links.items() if k in LINK_FIELDS and v}
        for key in EXTRA_FIELDS:
            if extra and extra.get(key):
                vals[key] = extra[key]
        vals.update({
            'dental_source_model': record._name,
            'dental_source_id': record.id,
            'dental_doc_type': doc_type,
        })
        if 'dental_document_date' not in vals:
            vals['dental_document_date'] = (attachment.create_date or attachment.write_date or
                                             self.env.cr.now()).date()

        DmsFile = self.env['dms.file'].sudo().with_context(active_test=False, dms_skip_log=True)
        # 1. Already in the DMS (e.g. routed by a dms.folder.rule): only add the dental links.
        existing = DmsFile.search([('attachment_id', '=', attachment.id)])
        if existing:
            for dms_file in existing:
                missing = {k: v for k, v in vals.items() if not dms_file[k]}
                if missing:
                    dms_file.write(missing)
            return existing[:1]
        # 2. Same content already filed for the same patient (e.g. the copy that dental_core pushes on
        #    the patient when a dental.patient.document is uploaded): do not file it twice.
        if vals.get('dental_patient_id') and attachment.checksum:
            twin = DmsFile.search([('dental_patient_id', '=', vals['dental_patient_id']),
                                   ('attachment_id.checksum', '=', attachment.checksum)], limit=1)
            if twin:
                return twin
        company = (record.company_id if 'company_id' in record._fields and record.company_id else False) \
            or attachment.company_id or self.env.company
        folder = self._get_target_folder(company, doc_type, record, links)
        name = clean_name(attachment.name, default=_('Document'))
        names = folder.sudo().file_ids.mapped('name')
        if name in names:
            extension = name.rsplit('.', 1)[1] if '.' in name else False
            name = dms_file_tools.unique_name(name, names, extension)
        vals.update({'name': name, 'directory_id': folder.id, 'attachment_id': attachment.id})
        dms_file = DmsFile.create(vals)
        _logger.info('Dental DMS: filed attachment %s of %s,%s into %s',
                     attachment.id, record._name, record.id, folder.complete_name)
        return dms_file

    @api.model
    def _route_existing_attachments(self, models_list=None, limit=None):
        """File historical attachments of every dental source model (used at install / on demand)."""
        sources = models_list or [m for m in self.env if self._is_dental_source(m)]
        Attachment = self.env['ir.attachment'].sudo()
        count = 0
        for res_model in sources:
            routable = list(self.env[res_model]._dental_dms_routable_fields())
            domain = [('res_model', '=', res_model), ('res_id', '!=', False), ('type', '=', 'binary')]
            domain += ['|', ('res_field', '=', False), ('res_field', 'in', routable)] if routable \
                else [('res_field', '=', False)]
            for attachment in Attachment.search(domain, order='id', limit=limit):
                if self._route_attachment(attachment):
                    count += 1
        return count

    @api.model
    def _store_document(self, record, name, raw, doc_type=None, mimetype=None, extra=None):
        """Create an attachment on ``record`` (as the current user) and file it. Returns the dms.file."""
        vals = {'name': name, 'raw': raw, 'res_model': record._name, 'res_id': record.id}
        if mimetype:
            vals['mimetype'] = mimetype
        attachment = self.env['ir.attachment'].with_context(
            dental_dms_doc_type=doc_type, dental_dms_extra=extra or {}).create(vals)
        return self.env['dms.file'].sudo().search([('attachment_id', '=', attachment.id)], limit=1) \
            or self.sudo()._route_attachment(attachment, doc_type=doc_type, extra=extra)
