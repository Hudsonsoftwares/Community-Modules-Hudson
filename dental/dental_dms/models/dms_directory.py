# -*- coding: utf-8 -*-
from odoo import fields, models

from .const import DOC_TYPES


class DmsDirectory(models.Model):
    """Additive markers so the integration can find the folders it manages.

    Nothing of the DMS directory behaviour is changed: these are plain stored fields.
    """
    _inherit = 'dms.directory'

    dental_folder_role = fields.Selection(
        [('root', 'Dental Root'), ('category', 'Dental Category'), ('subject', 'Dental Subject')],
        string='Dental Folder Role', index=True, copy=False, readonly=True,
        help='Set on folders created by the dental integration: the per-branch root, '
             'one category folder per document type and one sub-folder per patient / employee / record.')
    dental_doc_type = fields.Selection(DOC_TYPES, string='Dental Document Type', index=True, copy=False, readonly=True)
    dental_patient_id = fields.Many2one('res.partner', string='Dental Patient', index=True, copy=False, readonly=True,
                                        ondelete='cascade')
