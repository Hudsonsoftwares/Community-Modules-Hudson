# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError

class DentalCase(models.Model):
    _inherit = 'dental.case'

    prescription_ids = fields.One2many(
        'dental.prescription',
        'case_id',
        string='Prescriptions'
    )
    prescription_count = fields.Integer(
        string='Prescription Count',
        compute='_compute_prescription_count'
    )

    history_prescription_ids = fields.Many2many(
        'dental.prescription',
        string='All Prescriptions',
        compute='_compute_history_prescription_ids',
        help="The patient's prescriptions across all cases, within the user's access rights."
    )

    @api.depends('prescription_ids')
    def _compute_prescription_count(self):
        for record in self:
            record.prescription_count = len(record.prescription_ids)

    previous_prescription_ids = fields.Many2many(
        'dental.prescription',
        string='Previous Prescriptions',
        compute='_compute_history_prescription_ids',
        help="The patient's prescriptions from other cases (earlier visits), newest first."
    )

    def _compute_history_prescription_ids(self):
        Prescription = self.env['dental.prescription']
        for record in self:
            if not record.patient_id:
                record.history_prescription_ids = record.previous_prescription_ids = False
                continue
            history = Prescription.search([('patient_id', '=', record.patient_id.id)])
            record.history_prescription_ids = history
            record.previous_prescription_ids = history.filtered(lambda rx: rx.case_id != record._origin)

    def action_view_prescriptions(self):
        self.ensure_one()
        return {
            'name': _('Prescriptions for Case %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.prescription',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {
                'default_case_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_dentist_id': self.doctor_id.id if self.doctor_id else False,
            }
        }

    def action_new_prescription(self):
        self.ensure_one()
        return {
            'name': _('New Prescription for %s', self.patient_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.prescription',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_case_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_dentist_id': self.doctor_id.id if self.doctor_id else False,
                'default_appointment_id': (self.current_visit_id or self.appointment_id).id,
            }
        }

    # ------------------------------------------------------------------
    # Today's prescription, written directly on the case's Prescriptions tab
    # (lines are added like sales order lines; values go to the visit's draft prescription)
    # ------------------------------------------------------------------
    current_prescription_id = fields.Many2one(
        'dental.prescription', string="Today's Prescription", compute='_compute_current_prescription',
        help='Draft prescription of the current visit that the Prescriptions tab edits.')
    rx_line_ids = fields.One2many(
        'dental.prescription.line', string='Medicines', compute='_compute_current_prescription', readonly=False)
    rx_diagnosis = fields.Char(string='Indication', compute='_compute_current_prescription', readonly=False)
    rx_clinical_notes = fields.Text(string='Advice to Patient', compute='_compute_current_prescription', readonly=False)
    rx_template_id = fields.Many2one(
        'dental.prescription.template', string='Add Regimen', compute='_compute_current_prescription', readonly=False,
        help='Adds the medicines of a standard regimen (e.g. post-extraction) to today\'s prescription.')
    rx_branch_has_pharmacy = fields.Boolean(related='company_id.dental_has_pharmacy', string='Branch Has Pharmacy')

    _RX_INLINE_FIELDS = {'rx_line_ids': 'line_ids', 'rx_diagnosis': 'diagnosis', 'rx_clinical_notes': 'clinical_notes'}

    @api.depends('prescription_ids.state', 'prescription_ids.line_ids', 'prescription_ids.diagnosis',
                 'prescription_ids.clinical_notes', 'current_visit_id')
    def _compute_current_prescription(self):
        for case in self:
            rx = case._find_visit_prescription()
            case.current_prescription_id = rx
            case.rx_line_ids = rx.line_ids
            case.rx_diagnosis = rx.diagnosis
            case.rx_clinical_notes = rx.clinical_notes
            case.rx_template_id = False

    def _find_visit_prescription(self):
        """Draft prescription of the current visit (the one still being written)."""
        self.ensure_one()
        drafts = self.prescription_ids.filtered(lambda rx: rx.state == 'draft')
        visit = self.current_visit_id or self.appointment_id
        if visit:
            drafts = drafts.filtered(lambda rx: rx.appointment_id == visit or not rx.appointment_id)
        return drafts.sorted(lambda rx: rx.id, reverse=True)[:1]

    def _get_visit_prescription(self):
        """Draft prescription of the current visit, created on first use."""
        self.ensure_one()
        rx = self._find_visit_prescription()
        if rx:
            return rx
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("Case %s is closed; reopen it to prescribe.", self.name))
        Prescription = self.env['dental.prescription']
        Prescription.check_access('create')
        visit = self.current_visit_id or self.appointment_id
        # Case doctor is hr.employee.public; prescriptions use hr.employee (same ids)
        dentist = self.env['hr.employee'].browse(self.doctor_id.id) if self.doctor_id else \
            self.env['hr.employee'].browse(Prescription._default_dentist_id())
        if not dentist:
            raise UserError(_("Set the doctor of case %s before prescribing.", self.name))
        rx = Prescription.create({
            'patient_id': self.patient_id.id,
            'case_id': self.id,
            'appointment_id': visit.id if visit else False,
            'dentist_id': dentist.id,
            'company_id': (self.company_id or self.env.company).id,
        })
        self.invalidate_recordset(['current_prescription_id'])
        return rx

    @api.onchange('rx_template_id')
    def _onchange_rx_template_id(self):
        template = self.rx_template_id
        if not template:
            return
        self.rx_line_ids = [Command.create({
            'medicine_id': t_line.medicine_id.id,
            'dose': t_line.dose,
            'route': t_line.route,
            'frequency': t_line.frequency,
            'duration': t_line.duration,
            'quantity': t_line.quantity,
            'instructions': t_line.instructions,
        }) for t_line in template.line_ids]
        if not self.rx_diagnosis:
            self.rx_diagnosis = template.indication or template.name
        self.rx_template_id = False

    def write(self, vals):
        rx_vals = {}
        if any(key in vals for key in self._RX_INLINE_FIELDS) or 'rx_template_id' in vals:
            vals = dict(vals)
            vals.pop('rx_template_id', None)
            rx_vals = {self._RX_INLINE_FIELDS[key]: vals.pop(key) for key in list(vals) if key in self._RX_INLINE_FIELDS}
        res = super().write(vals) if vals else True
        if rx_vals:
            for case in self:
                rx = case._find_visit_prescription()
                if not rx and not self._rx_vals_have_content(rx_vals):
                    continue
                (rx or case._get_visit_prescription()).write(rx_vals)
            self.invalidate_recordset(['current_prescription_id', *self._RX_INLINE_FIELDS])
        return res

    @api.model
    def _rx_vals_have_content(self, rx_vals):
        """Avoid creating an empty prescription when nothing was really entered."""
        commands = rx_vals.get('line_ids') or []
        new_lines = any(isinstance(c, (list, tuple)) and c and c[0] == Command.CREATE for c in commands)
        return new_lines or bool(rx_vals.get('diagnosis') or rx_vals.get('clinical_notes'))

    def action_rx_finalize(self):
        """Finish today's prescription: to the pharmacy queue (sales order created) when the branch has a
        pharmacy, otherwise issued and emailed to the patient as a PDF to buy outside."""
        self.ensure_one()
        rx = self._find_visit_prescription()
        if not rx or not rx.line_ids:
            raise UserError(_("Add at least one medicine to today's prescription first."))
        rx.action_confirm()
        if rx.state == 'confirmed':
            message = _("Prescription %s sent to the pharmacy.", rx.name)
        elif rx.patient_id.email:
            message = _("Prescription %(rx)s issued and emailed to %(email)s.", rx=rx.name, email=rx.patient_id.email)
        else:
            message = _("Prescription %s issued. The patient has no email address: print it for the patient.", rx.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'message': message, 'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    def action_rx_open_current(self):
        """Today's prescription on its own page (preview, print, more options)."""
        self.ensure_one()
        rx = self._find_visit_prescription()
        if not rx:
            raise UserError(_("Add a medicine to start today's prescription."))
        return rx.action_open_prescription()

    def action_complete_consultation(self):
        """Finishing the visit releases the doctor's prescriptions: draft prescriptions with
        medicines are confirmed, so they reach the pharmacy queue, or are issued to the
        patient when the branch has no in-house pharmacy."""
        drafts = self.mapped('prescription_ids').filtered(lambda rx: rx.state == 'draft' and rx.line_ids)
        if drafts:
            drafts.action_confirm()
        return super().action_complete_consultation()
