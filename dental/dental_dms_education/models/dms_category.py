# -*- coding: utf-8 -*-
from odoo import fields, models


class DmsCategory(models.Model):
    """Education topics are ordinary DMS categories (reused taxonomy) flagged as such."""
    _inherit = 'dms.category'

    dental_is_education_topic = fields.Boolean(string='Patient Education Topic', index=True)
    dental_product_ids = fields.Many2many(
        'product.template', 'dms_category_dental_product_rel', 'category_id', 'product_id',
        string='Dental Treatments', domain=[('is_dental_treatment', '=', True)],
        help='Treatments for which the videos of this topic are recommended.')
    dental_treatment_category_ids = fields.Many2many(
        'dental.treatment.category', 'dms_category_dental_treatment_category_rel', 'category_id', 'treatment_category_id',
        string='Treatment Categories',
        help='Fallback: recommend this topic for any treatment of these categories.')
    dental_topic_icon = fields.Char(string='Icon', default='fa-tooth',
                                    help='Font Awesome icon shown on clinic screens, e.g. fa-tooth')
