# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class DentalPrescriptionLine(models.Model):
    _name = 'dental.prescription.line'
    _description = 'Prescription Line Item'
    _order = 'id asc'

    prescription_id = fields.Many2one(
        'dental.prescription',
        string='Prescription Reference',
        required=True,
        ondelete='cascade',
        index=True
    )
    patient_id = fields.Many2one(
        'res.partner',
        string='Patient',
        related='prescription_id.patient_id',
        store=True,
        readonly=True
    )
    dentist_id = fields.Many2one(
        'hr.employee',
        string='Dentist',
        related='prescription_id.dentist_id',
        store=True,
        readonly=True
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
        required=True,
        help='Quantity per administration, e.g., 1 tablet, 500mg, 10ml'
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
        required=True,
        help='Treatment course in days'
    )
    quantity = fields.Float(
        string='Prescribed Qty',
        required=True,
        default=1.0,
        help='Total quantity prescribed to the patient'
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='medicine_id.uom_id',
        readonly=True
    )
    instructions = fields.Char(
        string='Instructions',
        default='After meals',
        help='Administration instructions, e.g., After food, Before bed, Rinse 30 secs'
    )
    dispensed_qty = fields.Float(
        string='Dispensed Qty',
        default=0.0,
        readonly=True,
        help='Quantity already dispensed across pharmacy dispensing records.'
    )
    remaining_qty = fields.Float(
        string='Remaining Qty',
        compute='_compute_remaining_qty',
        store=True,
        help='Quantity yet to be dispensed.'
    )
    state = fields.Selection(
        string='Status',
        related='prescription_id.state',
        store=True
    )
    has_allergy_conflict = fields.Boolean(
        string='Allergy Conflict',
        compute='_compute_allergy_conflict',
        store=True,
        help='Indicates if this medicine matches any documented allergy for this patient.'
    )
    allergy_conflict_note = fields.Char(
        string='Allergy Warning',
        compute='_compute_allergy_conflict',
        store=True,
        help='Details of allergy conflict for clinical reference.'
    )

    @api.depends('quantity', 'dispensed_qty')
    def _compute_remaining_qty(self):
        for line in self:
            line.remaining_qty = max(0.0, line.quantity - line.dispensed_qty)

    @api.depends('medicine_id', 'prescription_id.patient_id.allergies', 'patient_id.allergies')
    def _compute_allergy_conflict(self):
        for line in self:
            patient = line.prescription_id.patient_id or line.patient_id
            allergy_text = ""
            if patient and patient.allergies:
                import re
                allergy_text = re.sub(r'<[^>]+>', ' ', str(patient.allergies)).lower()

            if allergy_text and line.medicine_id:
                med_name = (line.medicine_id.name or "").lower()
                generic_name = (line.medicine_id.generic_name or "").lower()

                allergy_keywords = [
                    'penicillin', 'amoxicillin', 'ampicillin', 'augmentin', 'clavulanic',
                    'nsaid', 'aspirin', 'ibuprofen', 'ketorolac', 'diclofenac', 'mefenamic',
                    'paracetamol', 'acetaminophen',
                    'sulfa', 'sulfonamide',
                    'metronidazole', 'flagyl',
                    'codeine', 'tramadol', 'opioid',
                    'erythromycin', 'azithromycin', 'clindamycin',
                    'latex', 'lidocaine', 'lignocaine'
                ]

                matched = []
                for kw in allergy_keywords:
                    if kw in allergy_text:
                        if kw in med_name or kw in generic_name:
                            matched.append(kw.capitalize())

                if generic_name and len(generic_name) > 3:
                    for part in generic_name.replace('+', ' ').replace('(', ' ').replace(')', ' ').split():
                        part_clean = part.strip().lower()
                        if len(part_clean) > 3 and part_clean in allergy_text and part_clean.capitalize() not in matched:
                            matched.append(part_clean.capitalize())

                if matched:
                    match_str = ", ".join(matched)
                    line.has_allergy_conflict = True
                    line.allergy_conflict_note = f"⚠️ ALLERGY WARNING: Documented patient allergy to {match_str}!"
                else:
                    line.has_allergy_conflict = False
                    line.allergy_conflict_note = False
            else:
                line.has_allergy_conflict = False
                line.allergy_conflict_note = False

    @api.onchange('dose', 'frequency', 'duration', 'dosage_form')
    def _onchange_frequency_duration(self):
        multiplier_map = {
            'od': 1,
            'bid': 2,
            'tid': 3,
            'qid': 4,
            'q4h': 6,
            'q6h': 4,
            'q8h': 3,
            'prn': 1,
            'stat': 1,
        }
        mult = multiplier_map.get(self.frequency, 1)
        dur = self.duration or 1

        # Extract numeric unit count from dose string if present (e.g. "2 tabs" -> 2)
        dose_count = 1
        if self.dose:
            import re
            match = re.search(r'^(\d+)', str(self.dose).strip())
            if match:
                try:
                    dose_count = max(1, int(match.group(1)))
                except (ValueError, TypeError):
                    dose_count = 1

        form = self.medicine_id.dosage_form if self.medicine_id else (self.dosage_form or False)
        if form in ('tablet', 'capsule'):
            self.quantity = float(dose_count * mult * dur)
        elif form in ('mouthwash', 'syrup', 'gel', 'paste', 'spray', 'drops'):
            self.quantity = 1.0

    @api.onchange('medicine_id')
    def _onchange_medicine_id(self):
        warning = None
        if self.medicine_id:
            form = self.medicine_id.dosage_form
            if form == 'tablet':
                self.dose = '1 tablet'
                self.route = 'oral'
                self.instructions = 'After meals'
            elif form == 'capsule':
                self.dose = '1 capsule'
                self.route = 'oral'
                self.instructions = 'After meals'
            elif form == 'mouthwash':
                self.dose = '15 ml'
                self.route = 'topical'
                self.instructions = 'Rinse mouth for 1 minute twice daily'
            elif form == 'gel':
                self.dose = 'Apply thin layer'
                self.route = 'topical'
                self.instructions = 'Apply to affected area after meals'
            elif form == 'syrup':
                self.dose = '10 ml'
                self.route = 'oral'
                self.instructions = 'After meals'
            elif form == 'injection':
                self.dose = '1 cartridge'
                self.route = 'other'
                self.instructions = 'Clinical administration'

            # Auto calculate quantity
            self._onchange_frequency_duration()

            # Check Patient Allergy Conflict
            self._compute_allergy_conflict()
            if self.has_allergy_conflict:
                patient = self.prescription_id.patient_id or self.patient_id
                warning = {
                    'title': _('CLINICAL ALLERGY ALERT!'),
                    'message': _(
                        "CRITICAL PATIENT SAFETY WARNING:\n\n"
                        "Patient %(patient)s has a documented allergy matching %(med)s!\n"
                        "Warning Details: %(note)s\n\n"
                        "Please verify patient safety before confirming this medication."
                    ) % {
                        'patient': patient.name if patient else 'Patient',
                        'med': self.medicine_id.display_name,
                        'note': self.allergy_conflict_note,
                    }
                }

        if warning:
            return {'warning': warning}
