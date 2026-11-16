# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class DentalPrescriptionTemplate(models.Model):
    _name = 'dental.prescription.template'
    _description = 'Prescription Template'
    _order = 'sequence, name'

    name = fields.Char(
        string='Template Name',
        required=True,
        help='Clinical protocol name, e.g., Post-Extraction Standard Regimen, Acute Abscess Protocol'
    )
    code = fields.Char(
        string='Short Code',
        help='Short reference code, e.g., POST-EXT, PULP-01'
    )
    indication = fields.Char(
        string='Indication',
        help='Diagnosis or reason this template is used for; copied to the prescription'
    )
    notes = fields.Text(
        string='Clinical Advice / Special Instructions',
        help='Standard patient instructions, oral hygiene advice, diet cautions'
    )
    active = fields.Boolean(
        string='Active',
        default=True
    )
    sequence = fields.Integer(default=10)
    medicine_count = fields.Integer(string='Medicines', compute='_compute_medicine_summary')
    medicine_summary = fields.Text(string='Medicines Summary', compute='_compute_medicine_summary')
    line_ids = fields.One2many(
        'dental.prescription.template.line',
        'template_id',
        string='Prescription Items',
        copy=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Clinic Branch',
        default=lambda self: self.env.company
    )

    @api.depends('line_ids.medicine_id', 'line_ids.frequency', 'line_ids.duration')
    def _compute_medicine_summary(self):
        for template in self:
            labels = dict(template.line_ids._fields['frequency']._description_selection(self.env))
            template.medicine_count = len(template.line_ids)
            template.medicine_summary = '\n'.join(
                '%s · %s · %s' % (line.medicine_id.display_name, labels.get(line.frequency, ''), _('%s days', line.duration))
                for line in template.line_ids if line.medicine_id) or False


class DentalPrescriptionTemplateLine(models.Model):
    _name = 'dental.prescription.template.line'
    _description = 'Prescription Protocol Line Item'
    _order = 'id asc'

    template_id = fields.Many2one(
        'dental.prescription.template',
        string='Template Reference',
        required=True,
        ondelete='cascade',
        index=True
    )
    medicine_id = fields.Many2one(
        'product.product',
        string='Medicine',
        required=True,
        domain=[('is_medicine', '=', True)],
        index=True
    )
    generic_name = fields.Char(
        string='Generic Name',
        related='medicine_id.generic_name',
        readonly=True
    )
    dosage_form = fields.Selection(
        string='Form',
        related='medicine_id.dosage_form',
        readonly=True
    )
    strength = fields.Char(
        string='Strength',
        related='medicine_id.strength',
        readonly=True
    )
    dose = fields.Char(
        string='Dose',
        default='1 tab',
        required=True
    )
    route = fields.Selection([
        ('oral', 'Oral'),
        ('sublingual', 'Sublingual'),
        ('topical', 'Topical / Mouthwash'),
        ('iv', 'Intravenous (IV)'),
        ('im', 'Intramuscular (IM)'),
        ('inhalation', 'Inhalation'),
        ('other', 'Other'),
    ], string='Route', default='oral', required=True)

    frequency = fields.Selection([
        ('od', 'Once daily (OD)'),
        ('bid', 'Twice daily (BD / BID)'),
        ('tid', 'Three times daily (TDS / TID)'),
        ('qid', 'Four times daily (QDS / QID)'),
        ('q4h', 'Every 4 hours'),
        ('q6h', 'Every 6 hours'),
        ('q8h', 'Every 8 hours'),
        ('prn', 'As needed (PRN)'),
        ('stat', 'Immediately (STAT)'),
    ], string='Frequency', default='bid', required=True)

    duration = fields.Integer(
        string='Duration (Days)',
        default=5,
        required=True
    )
    quantity = fields.Float(
        string='Quantity',
        required=True,
        default=10.0
    )
    instructions = fields.Char(
        string='Instructions',
        default='After meals'
    )

    @api.onchange('frequency', 'duration', 'dosage_form')
    def _onchange_calc_qty(self):
        multiplier_map = {
            'od': 1, 'bid': 2, 'tid': 3, 'qid': 4,
            'q4h': 6, 'q6h': 4, 'q8h': 3, 'prn': 1, 'stat': 1
        }
        mult = multiplier_map.get(self.frequency, 1)
        dur = self.duration or 1
        if self.dosage_form in ('tablet', 'capsule'):
            self.quantity = mult * dur
        elif self.dosage_form in ('mouthwash', 'syrup', 'gel'):
            self.quantity = 1.0
