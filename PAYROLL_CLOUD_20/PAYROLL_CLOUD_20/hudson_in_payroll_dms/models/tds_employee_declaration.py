# -*- coding: utf-8 -*-
import logging
import os
from datetime import date

from odoo import SUPERUSER_ID, api, fields, models
from odoo.tools import BinaryBytes

_logger = logging.getLogger(__name__)

PAYROLL_FOLDER = 'Payroll'
PROOF_FOLDER = 'Tax Proofs'

# Proof fields of the declaration and the section shown in the document name, in display order
PROOF_FIELDS = [
    ('decl_80c_attachment_ids', '80C'),
    ('decl_80d_attachment_ids', '80D'),
    ('decl_80ccd1b_attachment_ids', '80CCD(1B)'),
    ('decl_hra_attachment_ids', 'HRA'),
    ('decl_lta_attachment_ids', 'LTA'),
    ('decl_24b_attachment_ids', '24(b)'),
    ('decl_80e_attachment_ids', '80E'),
    ('decl_80g_attachment_ids', '80G'),
    ('decl_80gg_attachment_ids', '80GG'),
    ('decl_80dd_attachment_ids', '80DD'),
    ('decl_80u_attachment_ids', '80U'),
    ('decl_57iia_attachment_ids', '57(iia)'),
    ('decl_80cch_attachment_ids', '80CCH'),
    ('prev_employer_attachment_ids', 'Previous Employer'),
]
OTHER_PROOF_LABEL = 'Proof'

# Proofs are in Documents from their submission on; locked once verified
STORED_STATES = ('proof_submitted', 'proof_under_review', 'proof_verified', 'approved', 'rejected')
LOCKED_STATES = ('proof_verified', 'approved')
SYNC_FIELDS = {'state', 'attachment_ids', 'declaration_line_ids', 'employee_id', 'financial_year_id'} | {
    fname for fname, _label in PROOF_FIELDS}


class HdsInTaxProofDocument(models.Model):
    """Link between a declaration proof file and its copy in the employee's Documents folder."""
    _name = 'hds.in.tax.proof.document'
    _description = 'Tax Proof in Documents'

    declaration_id = fields.Many2one('tds.employee.declaration', required=True, ondelete='cascade', index=True)
    attachment_id = fields.Many2one('ir.attachment', string="Proof File", ondelete='set null', index=True)
    dms_file_id = fields.Many2one('dms.file', string="Document", ondelete='set null')


class TdsEmployeeDeclaration(models.Model):
    _inherit = 'tds.employee.declaration'

    # ------------------------------------------------------------------
    # Declaration lifecycle
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        declarations = super().create(vals_list)
        declarations.filtered(lambda decl: decl.state in STORED_STATES)._hds_dms_sync_proofs()
        return declarations

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('hds_dms_proof_sync') and SYNC_FIELDS & set(vals):
            self._hds_dms_sync_proofs()
        return res

    # ------------------------------------------------------------------
    # Synchronisation
    # ------------------------------------------------------------------
    def _hds_dms_sync_proofs(self):
        """Bring the employee's Documents copies in line with the declaration's proofs.
        Never blocks the declaration: a failure is logged and retried on the next save."""
        for decl in self.sudo().with_context(hds_dms_proof_sync=True):
            if not decl.company_id.hds_dms_store_tax_proofs:
                continue
            try:
                with self.env.cr.savepoint():
                    decl._hds_dms_sync_declaration_proofs()
            except Exception as error:
                _logger.warning("Payroll Documents: tax proofs of declaration %s not stored: %s",
                                decl.display_name, error)

    def _hds_dms_wanted_proofs(self):
        """{attachment: section label} for every proof file currently on the declaration: the proof
        fields and the declaration lines. (The hidden 'Supporting Proof Documents' pool only ever
        collects files, so it still holds replaced or removed proofs: it is not used.)"""
        self.ensure_one()
        wanted = {}
        for fname, label in PROOF_FIELDS:
            if fname in self._fields:
                for attachment in self[fname]:
                    wanted.setdefault(attachment, label)
        for attachment in self.declaration_line_ids.mapped('attachment_ids'):
            wanted.setdefault(attachment, OTHER_PROOF_LABEL)
        return wanted

    def _hds_dms_sync_declaration_proofs(self):
        self.ensure_one()
        Link = self.env['hds.in.tax.proof.document'].sudo()
        links = Link.search([('declaration_id', '=', self.id)])
        wanted = self._hds_dms_wanted_proofs() if self.state in STORED_STATES else {}
        links_by_attachment = {link.attachment_id.id: link for link in links if link.attachment_id}

        folder = None
        kept = self.env['dms.file']
        for attachment, label in wanted.items():
            link = links_by_attachment.get(attachment.id)
            dms_file = link.dms_file_id.sudo().with_context(active_test=False).exists() if link else None
            if dms_file:
                if dms_file.is_trashed:
                    dms_file.with_user(SUPERUSER_ID).action_restore()
            else:
                content = attachment.raw
                content = bytes(content) if content else b''
                if not content:
                    # File not readable (e.g. missing from the file storage): no empty document; retried on the next save
                    _logger.warning("Payroll Documents: tax proof %s (%s) has no content, not copied.",
                                    attachment.id, attachment.name)
                    continue
                if folder is None:
                    folder = self._hds_dms_proof_folder()
                dms_file = self._hds_dms_copy_proof(folder, attachment, label, content)
                if link:
                    link.dms_file_id = dms_file
                else:
                    Link.create({'declaration_id': self.id, 'attachment_id': attachment.id,
                                 'dms_file_id': dms_file.id})
            kept |= dms_file

        # Proofs removed from the declaration (or declaration back to draft): copies to the Trash
        for link in links:
            dms_file = link.dms_file_id.sudo().with_context(active_test=False).exists()
            if dms_file and dms_file not in kept:
                self._hds_dms_trash_proof(dms_file)
            if not link.attachment_id:
                link.unlink()

        # Locked once verified (only Documents managers can change them); unlocked otherwise
        for dms_file in kept:
            if self.state in LOCKED_STATES:
                if not dms_file.locked_by:
                    dms_file.with_user(SUPERUSER_ID).lock()
            elif dms_file.locked_by.id == SUPERUSER_ID:
                dms_file.with_user(SUPERUSER_ID).unlock()

    def _hds_dms_copy_proof(self, folder, attachment, label, content):
        """A copy of the proof file (deleting it in Documents never touches the declaration)."""
        name = self._hds_dms_unique_name(folder, f"{label} - {attachment.name or 'proof'}".replace('/', '-'))
        File = self.env['dms.file'].with_user(SUPERUSER_ID).sudo().with_context(no_document=True)
        return File.create({
            'name': name,
            'directory_id': folder.id,
            'content': BinaryBytes(content, name),
            'company_id': folder.company_id.id or self.company_id.id,
        })

    @api.model
    def _hds_dms_trash_proof(self, dms_file):
        """Move a copy to the Documents Trash. A file locked by a user is left as it is."""
        if dms_file.is_trashed:
            return
        try:
            with self.env.cr.savepoint():
                if dms_file.locked_by.id == SUPERUSER_ID:
                    dms_file.with_user(SUPERUSER_ID).unlock()
                dms_file.with_user(SUPERUSER_ID).action_send_to_trash()
        except Exception as error:
            _logger.warning("Payroll Documents: tax proof file %s (%s) not moved to the Trash: %s",
                            dms_file.id, dms_file.name, error)

    # ------------------------------------------------------------------
    # Folders and names
    # ------------------------------------------------------------------
    def _hds_dms_proof_folder(self):
        """Employee folder / Payroll / <tax year> / Tax Proofs (created when missing; they inherit the
        employee folder's access, so the employee sees their own proofs)."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        if not employee.dms_directory_id:
            employee._setup_dms_folder_and_permissions()
        if not employee.dms_directory_id:
            raise ValueError("The employee %s has no Documents folder." % employee.name)
        folder = employee.dms_directory_id
        Payslip = self.env['hr.payslip']
        for name in (PAYROLL_FOLDER, self._hds_dms_tax_year_label(), PROOF_FOLDER):
            folder = Payslip._hds_dms_subfolder(folder, name)
        return folder

    def _hds_dms_tax_year_label(self):
        """'2026-27', the same folder as the payslips of that tax year."""
        self.ensure_one()
        fy = self.financial_year_id
        start, end = fy.start_date, fy.end_date
        if not start or not end:
            day = fields.Date.context_today(self)
            start = date(day.year if day.month >= 4 else day.year - 1, 4, 1)
            end = date(start.year + 1, 3, 31)
        return str(start.year) if start.year == end.year else f"{start.year}-{str(end.year)[-2:]}"

    @api.model
    def _hds_dms_unique_name(self, folder, name):
        """File names are unique per Documents folder: 'name (2).pdf' when already taken."""
        taken = set(self.env['dms.file'].sudo().with_context(active_test=False).search([
            ('directory_id', '=', folder.id)]).mapped('name'))
        if name not in taken:
            return name
        base, ext = os.path.splitext(name)
        index = 2
        while f"{base} ({index}){ext}" in taken:
            index += 1
        return f"{base} ({index}){ext}"
