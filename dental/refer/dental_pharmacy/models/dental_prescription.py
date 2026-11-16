# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.tools import html2plaintext

class DentalPrescription(models.Model):
    _name = 'dental.prescription'
    _description = 'Dental Clinical Prescription'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'prescription_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Prescription Number',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    patient_id = fields.Many2one(
        'res.partner',
        string='Patient',
        required=True,
        domain=[('is_dental_patient', '=', True)],
        tracking=True,
        index=True
    )
    patient_dental_id = fields.Char(
        string='Patient ID',
        related='patient_id.dental_patient_id',
        readonly=True
    )
    patient_age = fields.Integer(
        string='Age',
        related='patient_id.age',
        readonly=True
    )
    patient_gender = fields.Selection(
        string='Gender',
        related='patient_id.gender',
        readonly=True
    )
    patient_phone = fields.Char(
        string='Phone',
        related='patient_id.phone',
        readonly=True
    )
    patient_allergies = fields.Html(
        string='Allergies & Medical Alerts',
        related='patient_id.allergies',
        readonly=True
    )
    # Drives the allergy banner: an empty HTML editor value ("<p><br></p>") must not show an empty alert
    patient_allergy_status = fields.Selection(related='patient_id.allergy_status', string='Allergy Status')
    patient_allergies_text = fields.Char(string='Known Allergies', compute='_compute_patient_allergies_text')

    @api.depends('patient_id.allergies')
    def _compute_patient_allergies_text(self):
        for rx in self:
            text = html2plaintext(rx.patient_id.allergies or '').strip() if rx.patient_id.allergies else ''
            rx.patient_allergies_text = ' '.join(text.split()) or False
    dentist_id = fields.Many2one(
        'hr.employee',
        string='Prescribing Dentist',
        required=True,
        domain="[('is_dentist', '=', True)]",
        default=lambda self: self._default_dentist_id(),
        tracking=True,
        index=True
    )
    dentist_reg_no = fields.Char(
        string='License / Reg No.',
        related='dentist_id.registration_number',
        readonly=True
    )
    dentist_specialization = fields.Char(
        string='Specialization',
        related='dentist_id.specialization',
        readonly=True
    )
    dentist_signature = fields.Binary(
        string='Doctor Signature',
        related='dentist_id.signature_image',
        readonly=True
    )
    case_id = fields.Many2one(
        'dental.case',
        string='Dental Case',
        domain="[('patient_id', '=', patient_id)]",
        tracking=True,
        index=True,
        check_company=True,
    )
    appointment_id = fields.Many2one(
        'dental.appointment',
        string='Related Appointment',
        domain="[('patient_id', '=', patient_id)]",
        tracking=True,
        check_company=True,
    )
    prescription_date = fields.Date(
        string='Prescription Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    template_id = fields.Many2one(
        'dental.prescription.template',
        string='Prescription Protocol / Template',
        help='Select standard clinical regimen to auto-fill medications and instructions'
    )
    diagnosis = fields.Char(
        string='Indication / Diagnosis',
        tracking=True,
        help='Primary diagnosis or clinical reason for prescribing (e.g., Acute Apical Periodontitis, Post-Op Pain)'
    )
    clinical_notes = fields.Text(
        string='Clinical Advice / Special Instructions',
        help='Advice given to patient regarding diet, rest, hygiene, or warnings.'
    )
    medication_summary = fields.Text(
        string='Medicines',
        compute='_compute_medication_summary',
        help='One line per prescribed medicine with dose, frequency, duration and quantity.'
    )
    medicine_count = fields.Integer(string='Number of Medicines', compute='_compute_medication_summary')
    has_allergy_warning = fields.Boolean(
        string='Has Allergy Warning',
        compute='_compute_allergy_warning'
    )
    allergy_warning_msg = fields.Char(
        string='Allergy Warning Message',
        compute='_compute_allergy_warning'
    )
    stock_alert_count = fields.Integer(
        string='Stock Alerts',
        compute='_compute_stock_alert_summary',
        help='Number of prescribed medicines that are out of stock or short in the pharmacy.'
    )
    stock_alert_message = fields.Char(
        string='Stock Alert',
        compute='_compute_stock_alert_summary'
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Sent to Pharmacy'),
        ('issued', 'Issued to Patient'),
        ('partially_dispensed', 'Partially Dispensed'),
        ('fully_dispensed', 'Fully Dispensed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True, index=True)

    line_ids = fields.One2many(
        'dental.prescription.line',
        'prescription_id',
        string='Prescribed Medicines',
        copy=True
    )
    dispense_ids = fields.One2many(
        'dental.pharmacy.dispense',
        'prescription_id',
        string='Dispensing Records'
    )
    fulfillment = fields.Selection([
        ('pharmacy', 'In-house Pharmacy'),
        ('patient', 'Patient (outside pharmacy)'),
    ], string='Medicines Supplied By', readonly=True, copy=False, tracking=True,
        help='Set when the prescription is confirmed: dispensed and billed by the in-house pharmacy, '
             'or handed to the patient to buy outside (not billed by the clinic).')
    branch_has_pharmacy = fields.Boolean(related='company_id.dental_has_pharmacy', string='Branch Has Pharmacy')
    issued_date = fields.Datetime(string='Issued to Patient On', readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True, copy=False, index='btree_not_null',
                                    help='Medicine order for the pharmacy. Shows stock availability; nothing is reserved or blocked.')
    company_id = fields.Many2one(
        'res.company',
        string='Clinic Branch',
        default=lambda self: self.env.company,
        required=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True
    )
    total_prescribed_qty = fields.Float(
        string='Total Prescribed Qty',
        compute='_compute_quantities',
        store=True
    )
    total_dispensed_qty = fields.Float(
        string='Total Dispensed Qty',
        compute='_compute_quantities',
        store=True
    )
    total_remaining_qty = fields.Float(
        string='Total Remaining Qty',
        compute='_compute_quantities',
        store=True
    )
    dispense_count = fields.Integer(
        string='Dispense Count',
        compute='_compute_dispense_count'
    )
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_invoice_count'
    )

    def _default_dentist_id(self):
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
            ('is_dentist', '=', True)
        ], limit=1)
        if not employee:
            employee = self.env['hr.employee'].sudo().search([
                ('user_id', '=', self.env.uid)
            ], limit=1)
        return employee.id if employee else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.prescription') or _('New')
            if vals.get('template_id') and not vals.get('line_ids'):
                template = self.env['dental.prescription.template'].browse(vals['template_id'])
                if template:
                    if not vals.get('diagnosis') and template.indication:
                        vals['diagnosis'] = template.indication
                    if not vals.get('clinical_notes') and template.notes:
                        vals['clinical_notes'] = template.notes
                    lines = []
                    for t_line in template.line_ids:
                        lines.append((0, 0, {
                            'medicine_id': t_line.medicine_id.id,
                            'dose': t_line.dose,
                            'route': t_line.route,
                            'frequency': t_line.frequency,
                            'duration': t_line.duration,
                            'quantity': t_line.quantity,
                            'instructions': t_line.instructions,
                        }))
                    vals['line_ids'] = lines
        return super().create(vals_list)

    @api.depends('line_ids.quantity', 'line_ids.dispensed_qty')
    def _compute_quantities(self):
        for rx in self:
            prescribed = sum(rx.line_ids.mapped('quantity'))
            dispensed = sum(rx.line_ids.mapped('dispensed_qty'))
            rx.total_prescribed_qty = prescribed
            rx.total_dispensed_qty = dispensed
            rx.total_remaining_qty = max(0.0, prescribed - dispensed)

    def _compute_dispense_count(self):
        for rx in self:
            rx.dispense_count = len(rx.dispense_ids)

    @api.depends('line_ids.medicine_id', 'line_ids.dose', 'line_ids.frequency', 'line_ids.duration',
                 'line_ids.quantity', 'line_ids.instructions')
    def _compute_medication_summary(self):
        """One line per medicine, e.g. 'Amoxicillin 500 mg: 1 tab, Three times daily (TDS / TID), 5 days, qty 15 (After meals)'."""
        for rx in self:
            rows = []
            for line in rx.line_ids:
                name = line.medicine_id.display_name or _('Medicine')
                if line.strength and line.strength not in name:
                    name = f"{name} {line.strength}"
                details = [line.dose, line.frequency_label,
                           line.duration and _('%s days', line.duration),
                           line.quantity and _('qty %s', f"{line.quantity:g}")]
                row = f"{name}: {', '.join(d for d in details if d)}"
                if line.instructions:
                    row += f" ({line.instructions})"
                rows.append(row)
            rx.medication_summary = '\n'.join(rows) or False
            rx.medicine_count = len(rx.line_ids)

    def action_open_prescription(self):
        """Open the prescription on its own page (from the case's prescription history)."""
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.prescription',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.depends('line_ids.stock_alert', 'line_ids.medicine_id')
    def _compute_stock_alert_summary(self):
        for rx in self:
            short = rx.line_ids.filtered(lambda l: l.stock_alert in ('out', 'insufficient'))
            low = rx.line_ids.filtered(lambda l: l.stock_alert == 'low')
            rx.stock_alert_count = len(short)
            parts = []
            if short:
                parts.append(_('Not available / short: %s', ', '.join(
                    '%s (%s)' % (l.medicine_id.name, l.stock_alert_note) for l in short)))
            if low:
                parts.append(_('Running low: %s', ', '.join(low.mapped('medicine_id.name'))))
            rx.stock_alert_message = ' | '.join(parts) or False

    def _compute_invoice_count(self):
        for rx in self:
            invoices = rx.dispense_ids.mapped('invoice_id').filtered(lambda inv: inv)
            rx.invoice_count = len(invoices)

    @api.depends('line_ids.has_allergy_conflict', 'line_ids.medicine_id', 'patient_id.allergies', 'patient_allergies')
    def _compute_allergy_warning(self):
        for rx in self:
            patient = rx.patient_id
            allergy_text = ""
            if patient and patient.allergies:
                import re
                allergy_text = re.sub(r'<[^>]+>', ' ', str(patient.allergies)).lower()

            conflicted = False
            conflicted_names = []
            for line in rx.line_ids:
                if line.has_allergy_conflict and line.medicine_id:
                    conflicted = True
                    conflicted_names.append(line.medicine_id.name)
                elif allergy_text and line.medicine_id:
                    med_name = (line.medicine_id.name or "").lower()
                    generic_name = (line.medicine_id.generic_name or "").lower()
                    for kw in ['penicillin', 'amoxicillin', 'ampicillin', 'augmentin', 'clavulanic',
                               'nsaid', 'aspirin', 'ibuprofen', 'ketorolac', 'diclofenac', 'mefenamic',
                               'paracetamol', 'sulfa', 'metronidazole', 'codeine', 'tramadol', 'clindamycin', 'latex']:
                        if kw in allergy_text and (kw in med_name or kw in generic_name):
                            conflicted = True
                            conflicted_names.append(line.medicine_id.name)
                            break

            if conflicted:
                rx.has_allergy_warning = True
                rx.allergy_warning_msg = f"⚠️ CRITICAL ALERT: Patient has documented allergy matching prescribed medication(s): {', '.join(set(conflicted_names))}"
            else:
                rx.has_allergy_warning = False
                rx.allergy_warning_msg = False

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            if self.template_id.indication:
                self.diagnosis = self.template_id.indication
            if self.template_id.notes:
                self.clinical_notes = self.template_id.notes
            lines = []
            for t_line in self.template_id.line_ids:
                lines.append((0, 0, {
                    'medicine_id': t_line.medicine_id.id,
                    'dose': t_line.dose,
                    'route': t_line.route,
                    'frequency': t_line.frequency,
                    'duration': t_line.duration,
                    'quantity': t_line.quantity,
                    'instructions': t_line.instructions,
                }))
            if lines:
                self.line_ids = lines

    @api.onchange('case_id')
    def _onchange_case_id(self):
        case = self.case_id
        if not case:
            return
        if case.company_id:
            # A prescription belongs to the branch of its case
            self.company_id = case.company_id
        if case.patient_id:
            self.patient_id = case.patient_id
        if not self.dentist_id and case.doctor_id:
            # Case doctor is hr.employee.public; prescriptions use hr.employee (same ids)
            self.dentist_id = self.env['hr.employee'].browse(case.doctor_id.id)
        if not self.appointment_id and case.appointment_id:
            self.appointment_id = case.appointment_id

    @api.onchange('patient_id')
    def _onchange_patient_id(self):
        if self.patient_id and self.case_id and self.case_id.patient_id != self.patient_id:
            self.case_id = False
        if self.patient_id and self.appointment_id and self.appointment_id.patient_id != self.patient_id:
            self.appointment_id = False
        # Trigger allergy check on existing lines if patient changes
        for line in self.line_ids:
            line._onchange_medicine_id()

    def action_confirm(self):
        for record in self:
            # Security verification
            if not (self.env.user.has_group('dental_base.group_dental_dentist') or
                    self.env.user.has_group('dental_base.group_dental_manager') or
                    self.env.user.has_group('dental_base.group_dental_admin')):
                raise ValidationError(_("Only dentists and clinic managers are authorized to confirm clinical prescriptions."))

            if not record.line_ids:
                raise ValidationError(_("Please add at least one medicine before confirming the prescription."))

            for line in record.line_ids:
                if line.quantity <= 0:
                    raise ValidationError(_("Prescribed quantity for %s must be greater than zero.") % line.medicine_id.display_name)

            if record.company_id.dental_has_pharmacy:
                record.write({'state': 'confirmed', 'fulfillment': 'pharmacy'})
                order = record._create_sale_order()
                record.message_post(body=_("Prescription confirmed by %(user)s and sent to the pharmacy for dispensing (sales order %(so)s).",
                                           user=self.env.user.name, so=order.name or '-'))
            else:
                # Branch without a pharmacy: the patient buys the medicines outside
                record.message_post(body=_("Prescription confirmed by %s.") % self.env.user.name)
                record._issue_to_patient(reason=_("%s has no in-house pharmacy.", record.company_id.name))

    # ---------------------------------------------------------
    # Issue to patient (no in-house pharmacy, or patient buys outside)
    # ---------------------------------------------------------
    def _check_can_hand_over(self):
        user = self.env.user
        if not user.has_groups('dental_base.group_dental_dentist,dental_base.group_dental_receptionist,'
                               'dental_base.group_dental_manager,dental_pharmacy.group_dental_pharmacist'):
            raise AccessError(_("You are not allowed to issue prescriptions to patients."))
        # Only prescriptions the user can actually see (branch / record rules)
        self.check_access('read')

    def _issue_to_patient(self, reason=None):
        """Hand the prescription to the patient: no pharmacy dispensing, no medicine billing."""
        template = self.env.ref('dental_pharmacy.mail_template_prescription_to_patient', raise_if_not_found=False)
        for rx in self.sudo():
            rx.write({'state': 'issued', 'fulfillment': 'patient', 'issued_date': fields.Datetime.now()})
            rx._cancel_sale_order()
            note = _("Prescription issued to the patient to buy the medicines outside. "
                     "Medicines are not billed by the clinic; the front desk bills the visit only.")
            if reason:
                note = "%s %s" % (reason, note)
            rx.message_post(body=note)
            rx._send_to_patient(template)

    def _send_to_patient(self, template=None):
        """Email the prescription PDF when the patient has an email; otherwise ask the desk to print it."""
        template = template or self.env.ref('dental_pharmacy.mail_template_prescription_to_patient', raise_if_not_found=False)
        sent = self.env['dental.prescription']
        for rx in self.sudo():
            if template and rx.patient_id.email:
                rx.message_post_with_source(template, message_type='comment', subtype_xmlid='mail.mt_comment',
                                            partner_ids=rx.patient_id.ids)
                sent |= rx
            else:
                rx.message_post(body=_("Patient has no email address: print the prescription and hand it over at the front desk."))
        return sent

    def action_issue_to_patient(self):
        """Patient prefers to buy outside (or the pharmacy cannot supply): take it out of the pharmacy queue."""
        self._check_can_hand_over()
        for rx in self:
            if rx.state != 'confirmed' or rx.total_dispensed_qty > 0:
                raise UserError(_("Only prescriptions waiting at the pharmacy with nothing dispensed yet can be issued to the patient (%s).", rx.name))
        self._issue_to_patient(reason=_("Issued to the patient by %s.", self.env.user.name))
        return self._hand_over_notification(_("Prescription issued to the patient."))

    def action_send_to_patient(self):
        self._check_can_hand_over()
        if any(rx.state != 'issued' for rx in self):
            raise UserError(_("Only prescriptions issued to the patient can be sent."))
        sent = self._send_to_patient()
        if not sent:
            return self._hand_over_notification(_("The patient has no email address. Print the prescription instead."), 'warning')
        return self._hand_over_notification(_("Prescription emailed to the patient."))

    def action_print_for_patient(self):
        self._check_can_hand_over()
        return self.env.ref('dental_pharmacy.action_report_dental_prescription').report_action(self)

    def _hand_over_notification(self, message, kind='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': kind, 'message': message, 'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    def action_cancel(self):
        for record in self:
            if record.total_dispensed_qty > 0:
                raise UserError(_("Cannot cancel prescription %s because medicines have already been dispensed. "
                                  "Authorized returns must be processed in the Dispensing module first.") % record.name)
            record.state = 'cancelled'
            record._cancel_sale_order()
            record.message_post(body=_("Prescription cancelled by %s.") % self.env.user.name)

    def action_draft(self):
        for record in self:
            if record.total_dispensed_qty > 0:
                raise UserError(_("Cannot reset to draft because medications have already been dispensed."))
            record.state = 'draft'
            # A fresh quotation is created on the next confirmation, with the corrected medicines
            record._cancel_sale_order()

    # ---------------------------------------------------------
    # Sales order: the commercial side of the prescription
    # ---------------------------------------------------------
    def _prepare_sale_order_vals(self):
        self.ensure_one()
        return {
            'partner_id': self.patient_id.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'client_order_ref': self.name,
            'dental_prescription_id': self.id,
            'note': self.diagnosis or False,
            'order_line': [(0, 0, {
                'product_id': line.medicine_id.id,
                'product_uom_qty': line.quantity,
                'dental_prescription_line_id': line.id,
            }) for line in self.line_ids if line.medicine_id],
        }

    def _create_sale_order(self):
        """Quotation for the prescribed medicines.

        It is informational, not a hard link: nothing is reserved, stock is never checked
        or blocked, and the pharmacy dispenses from it. Its lines show the forecast stock.
        """
        self.ensure_one()
        if self.sale_order_id and self.sale_order_id.state != 'cancel':
            return self.sale_order_id
        # Prescribers have no sales rights; the order is created on their behalf
        order = self.env['sale.order'].sudo().with_company(self.company_id).create(self._prepare_sale_order_vals())
        self.sudo().sale_order_id = order
        return order

    def _cancel_sale_order(self):
        """Drop the quotation while nothing was delivered or invoiced from it."""
        for rx in self.sudo():
            order = rx.sale_order_id
            if not order or order.state == 'cancel':
                continue
            if any(line.qty_delivered or line.qty_invoiced for line in order.order_line):
                rx.message_post(body=_("Sales order %s already has deliveries or invoices and was kept.", order.name))
                continue
            order._action_cancel()
            rx.message_post(body=_("Sales order %s cancelled.", order.name))

    def _confirm_sale_order_for_dispense(self):
        """Confirm the quotation when the pharmacy dispenses. The pharmacy's own transfer is the
        delivery, so no extra delivery order is generated (skip_procurement)."""
        self.ensure_one()
        order = self.sale_order_id.sudo()
        if not order or order.state == 'cancel':
            order = self._create_sale_order().sudo()
        if order.state in ('draft', 'sent'):
            order.with_context(skip_procurement=True).action_confirm()
        return order

    def action_view_sale_order(self):
        self.ensure_one()
        return {
            'name': _('Sales Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }

    def _update_dispensing_state(self):
        for rx in self:
            self._compute_quantities()
            if rx.state == 'cancelled':
                continue
            if rx.total_dispensed_qty == 0:
                rx.state = 'confirmed'
            elif rx.total_remaining_qty <= 0:
                rx.state = 'fully_dispensed'
            else:
                rx.state = 'partially_dispensed'

    def action_dispense(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'partially_dispensed'):
            raise UserError(_("Only confirmed or partially dispensed prescriptions can be dispensed."))
        if self.total_remaining_qty <= 0:
            raise UserError(_("All prescribed items for this prescription have already been fully dispensed."))

        # Seamless 1-Click Dispense: Check or create draft dispense order with lines pre-populated
        dispense = self.env['dental.pharmacy.dispense'].search([
            ('prescription_id', '=', self.id),
            ('state', '=', 'draft')
        ], limit=1)

        if not dispense:
            dispense = self.env['dental.pharmacy.dispense'].create({
                'prescription_id': self.id,
                'patient_id': self.patient_id.id,
                'company_id': self.company_id.id,
                'sale_type': 'prescription',
            })
            dispense._onchange_prescription_id()

        return {
            'name': _('Dispense Prescription %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.pharmacy.dispense',
            'res_id': dispense.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_dispenses(self):
        self.ensure_one()
        return {
            'name': _('Dispensing Records for %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.pharmacy.dispense',
            'view_mode': 'list,form',
            'domain': [('prescription_id', '=', self.id)],
            'context': {'default_prescription_id': self.id},
        }

    def action_view_invoices(self):
        self.ensure_one()
        invoice_ids = self.dispense_ids.mapped('invoice_id').ids
        return {
            'name': _('Linked Invoices for %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoice_ids)],
        }
