# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    is_medicine = fields.Boolean(
        related='product_tmpl_id.is_medicine',
        string='Is Medicine',
        readonly=False,
        store=True,
        index=True
    )
    generic_name = fields.Char(
        related='product_tmpl_id.generic_name',
        string='Generic Name',
        readonly=False,
        store=True,
        index=True
    )
    medicine_category_id = fields.Many2one(
        related='product_tmpl_id.medicine_category_id',
        string='Medicine Category',
        readonly=False,
        store=True,
        index=True
    )
    dosage_form = fields.Selection(
        related='product_tmpl_id.dosage_form',
        string='Dosage Form',
        readonly=False,
        store=True
    )
    strength = fields.Char(
        related='product_tmpl_id.strength',
        string='Strength',
        readonly=False,
        store=True
    )
    dosage_unit = fields.Char(
        related='product_tmpl_id.dosage_unit',
        string='Dosage Unit',
        readonly=False,
        store=True
    )
    prescription_required = fields.Boolean(
        related='product_tmpl_id.prescription_required',
        string='Prescription Required',
        readonly=False,
        store=True
    )
    reorder_level = fields.Float(
        related='product_tmpl_id.reorder_level',
        string='Reorder Level',
        readonly=False,
        store=True
    )
    reorder_quantity = fields.Float(
        related='product_tmpl_id.reorder_quantity',
        string='Reorder Quantity',
        readonly=False,
        store=True
    )
    manufacturer_id = fields.Many2one(
        related='product_tmpl_id.manufacturer_id',
        string='Supplier / Vendor',
        readonly=False,
        store=True
    )
    stock_status = fields.Selection(
        related='product_tmpl_id.stock_status',
        string='Stock Status'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_medicine'):
                if 'is_storable' in self._fields and 'is_storable' not in vals:
                    vals['is_storable'] = True
                if 'tracking' not in vals:
                    vals['tracking'] = 'lot'
        return super().create(vals_list)

