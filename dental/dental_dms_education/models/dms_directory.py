# -*- coding: utf-8 -*-
from odoo import fields, models


class DmsDirectory(models.Model):
    _inherit = 'dms.directory'

    dental_doc_type = fields.Selection(selection_add=[('education', 'Patient Education Library')],
                                       ondelete={'education': 'set null'})
    dental_edu_topic_id = fields.Many2one('dms.category', string='Education Topic', index=True, copy=False,
                                          readonly=True, ondelete='set null')
