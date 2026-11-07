# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    patient_id = fields.Many2one(
        'res.partner',
        string='Patient Record',
        domain=[('is_dental_patient', '=', True)],
        tracking=True,
        index=True,
        help="Linked dental patient record in the clinic."
    )
    treatment_id = fields.Many2one(
        'product.template',
        string='Interested Treatment',
        domain=[('is_dental_treatment', '=', True)],
        tracking=True,
        help="Dental treatment or service the prospective patient is enquiring about."
    )
    preferred_doctor_id = fields.Many2one(
        'hr.employee',
        string='Preferred Dentist',
        domain=[('is_dentist', '=', True)],
        tracking=True,
        help="Specific dentist requested by the prospective patient."
    )
    preferred_date = fields.Datetime(
        string='Preferred Appointment Date/Time',
        tracking=True,
        help="Target date and time prospective patient is seeking to visit."
    )
    enquiry_date = fields.Datetime(
        string='Enquiry Date',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
        help="Date and time when this enquiry was received."
    )
    source_type = fields.Selection([
        ('walk_in', 'Walk-in'),
        ('phone', 'Phone Call'),
        ('website', 'Website'),
        ('referral', 'Patient Referral'),
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('google', 'Google / Search'),
        ('other', 'Other Source')
    ], string='Enquiry Source Channel', default='phone', tracking=True)

    referring_patient_id = fields.Many2one(
        'res.partner',
        string='Referred by Patient',
        domain=[('is_dental_patient', '=', True)],
        tracking=True,
        help="Existing dental patient who referred this enquiry."
    )

    appointment_id = fields.Many2one(
        'dental.appointment',
        string='Primary Booked Appointment',
        readonly=True,
        copy=False,
        tracking=True,
        help="Appointment created and linked from this prospective enquiry."
    )
    appointment_ids = fields.One2many(
        'dental.appointment',
        'lead_id',
        string='Linked Appointments',
        help="All dental appointments originating from or associated with this enquiry."
    )
    appointment_count = fields.Integer(
        string='Appointments Count',
        compute='_compute_appointment_count'
    )

    conversion_status = fields.Selection([
        ('new', 'New Enquiry'),
        ('contacted', 'Contacted / In Progress'),
        ('follow_up', 'Follow-up Scheduled'),
        ('appointment_scheduled', 'Appointment Scheduled'),
        ('appointment_completed', 'Appointment Completed'),
        ('cancelled', 'Lost / Cancelled')
    ], string='Enquiry Conversion Status', default='new', tracking=True)

    has_matching_patient = fields.Boolean(
        string='Matching Patient Found',
        compute='_compute_matching_patient'
    )
    matching_patient_id = fields.Many2one(
        'res.partner',
        string='Suggested Existing Patient',
        compute='_compute_matching_patient'
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('appointment_ids')
    def _compute_appointment_count(self):
        for lead in self:
            lead.appointment_count = len(lead.appointment_ids)

    @api.depends('patient_id', 'phone', 'email_from')
    def _compute_matching_patient(self):
        Partner = self.env['res.partner']
        for lead in self:
            if lead.patient_id:
                lead.has_matching_patient = True
                lead.matching_patient_id = lead.patient_id
                continue

            matched = lead._find_matching_patient()
            if matched:
                lead.has_matching_patient = True
                lead.matching_patient_id = matched
            else:
                lead.has_matching_patient = False
                lead.matching_patient_id = False

    # -------------------------------------------------------------------------
    # HELPER METHODS & PHONE/EMAIL NORMALIZATION
    # -------------------------------------------------------------------------
    def _normalize_phone_str(self, phone_str):
        if not phone_str:
            return ''
        # Keep digits and leading plus sign
        digits_only = re.sub(r'[^\d+]', '', str(phone_str))
        # If it starts with 00, replace with +
        if digits_only.startswith('00'):
            digits_only = '+' + digits_only[2:]
        return digits_only

    def _find_matching_patient(self):
        """
        Match existing patient exclusively by normalized phone/mobile or email.
        Strict rule: Do not match based only on matching name.
        """
        self.ensure_one()
        Partner = self.env['res.partner']
        candidates = Partner.browse()

        phone_clean = self._normalize_phone_str(self.phone)
        mobile_val = getattr(self, 'mobile', '')
        mobile_clean = self._normalize_phone_str(mobile_val)
        email_clean = (self.email_from or '').strip().lower()

        domain = [('is_dental_patient', '=', True)]
        has_mobile = 'mobile' in Partner._fields
        has_phone = 'phone' in Partner._fields

        # 1. Match by phone or mobile
        phone_filters = []
        if phone_clean and len(phone_clean) >= 7:
            if has_phone:
                phone_filters.append(('phone', 'ilike', phone_clean[-10:]))
            if has_mobile:
                phone_filters.append(('mobile', 'ilike', phone_clean[-10:]))
        if mobile_clean and len(mobile_clean) >= 7:
            if has_phone:
                phone_filters.append(('phone', 'ilike', mobile_clean[-10:]))
            if has_mobile:
                phone_filters.append(('mobile', 'ilike', mobile_clean[-10:]))

        if phone_filters:
            # Build OR domain
            or_conditions = list(phone_filters)
            or_domain = ['|'] * (len(or_conditions) - 1) + or_conditions
            candidates = Partner.search(domain + or_domain, limit=2)
            if len(candidates) == 1:
                return candidates[0]

        # 2. Match by email
        if email_clean and '@' in email_clean:
            email_candidates = Partner.search(domain + [('email', '=ilike', email_clean)], limit=2)
            if len(email_candidates) == 1:
                return email_candidates[0]

        return candidates[0] if len(candidates) == 1 else False

    def _prepare_dental_patient_vals(self):
        """Build partner values to create or upgrade a dental patient record cleanly."""
        self.ensure_one()
        contact_name = self.contact_name or self.partner_name or self.name or _('Patient')
        branch = self.company_id or self.env.company
        return {
            'name': contact_name,
            'is_dental_patient': True,
            'phone': self.phone or '',
            'mobile': self.mobile or '',
            'email': self.email_from or '',
            'active_clinic_id': branch.id,
            'street': self.street or '',
            'street2': self.street2 or '',
            'city': self.city or '',
            'state_id': self.state_id.id if self.state_id else False,
            'country_id': self.country_id.id if self.country_id else False,
            'zip': self.zip or '',
        }

    # -------------------------------------------------------------------------
    # ONCHANGE / SYNC WITH UTM SOURCE
    # -------------------------------------------------------------------------
    @api.onchange('source_type')
    def _onchange_source_type_sync_utm(self):
        if not self.source_type:
            return
        mapping = {
            'walk_in': 'Walk-in',
            'phone': 'Phone Call',
            'website': 'Website',
            'referral': 'Referral',
            'facebook': 'Facebook',
            'instagram': 'Instagram',
            'google': 'Google',
            'other': 'Other',
        }
        target_name = mapping.get(self.source_type)
        if target_name:
            source = self.env['utm.source'].search([('name', '=ilike', target_name)], limit=1)
            if not source:
                source = self.env['utm.source'].sudo().create({'name': target_name})
            self.source_id = source.id

    # -------------------------------------------------------------------------
    # USER ACTIONS
    # -------------------------------------------------------------------------
    def action_match_patient(self):
        """Manually or automatically link lead to a detected matching patient."""
        self.ensure_one()
        if self.patient_id:
            return True

        matched = self._find_matching_patient()
        if matched:
            self.write({
                'patient_id': matched.id,
                'partner_id': matched.id,
            })
            self.message_post(body=_(
                "Linked to existing patient record: <b>%s</b> (Patient ID: %s)"
            ) % (matched.name, matched.dental_patient_id or 'N/A'))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Patient Linked'),
                    'message': _('Successfully linked enquiry to %s') % matched.name,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            raise UserError(_(
                "No single unambiguous matching dental patient found by phone number or email address. "
                "Please search and select the Patient Record directly or proceed to Book Appointment to register them."
            ))

    def action_book_appointment(self):
        """
        Open the existing dental appointment booking workflow with patient and treatment prefilled.
        Ensures existing patient is linked or creates/promotes a partner without duplicates.
        """
        self.ensure_one()

        # 1. Resolve Patient
        patient = self.patient_id
        if not patient:
            matched = self._find_matching_patient()
            if matched:
                patient = matched
                self.write({'patient_id': matched.id, 'partner_id': matched.id})
            elif self.partner_id and self.partner_id.is_dental_patient:
                patient = self.partner_id
                self.write({'patient_id': patient.id})
            elif self.partner_id and not self.partner_id.is_dental_patient:
                # Upgrade existing partner to dental patient
                self.partner_id.write({'is_dental_patient': True})
                patient = self.partner_id
                self.write({'patient_id': patient.id})
            else:
                # Create clean new patient
                patient_vals = self._prepare_dental_patient_vals()
                patient = self.env['res.partner'].create(patient_vals)
                self.write({'patient_id': patient.id, 'partner_id': patient.id})

        # 2. Prepare Appointment Default Times
        start_time = self.preferred_date or fields.Datetime.now()
        end_time = start_time + timedelta(minutes=30)
        default_type = self.env['dental.appointment.type'].search([('active', '=', True)], limit=1)
        branch = self.company_id or (getattr(patient, 'active_clinic_id', False) and patient.active_clinic_id) or self.env.company

        # 3. Mark in-progress / contacted if currently new
        if self.conversion_status == 'new':
            self.write({'conversion_status': 'contacted'})

        form_view = self.env.ref('dental_appointment.view_dental_appointment_form', raise_if_not_found=False)

        return {
            'name': _('Book Appointment - %s') % (patient.name or self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.appointment',
            'view_mode': 'form',
            'views': [(form_view.id, 'form')] if form_view else [(False, 'form')],
            'target': 'current',
            'context': {
                'default_patient_id': patient.id,
                'default_treatment_id': self.treatment_id.id if self.treatment_id else False,
                'default_doctor_id': self.preferred_doctor_id.id if self.preferred_doctor_id else False,
                'default_appointment_type_id': default_type.id if default_type else False,
                'default_date_start': start_time,
                'default_date_end': end_time,
                'default_branch_id': branch.id,
                'default_reason': _('Enquiry: %s') % (self.name or ''),
                'default_notes': self.description or '',
                'default_lead_id': self.id,
            }
        }

    def action_schedule_followup(self):
        """Schedule an Odoo activity for this enquiry."""
        self.ensure_one()
        call_type = self.env.ref('mail.mail_activity_data_call', raise_if_not_found=False)
        return {
            'name': _('Schedule Enquiry Follow-up'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.activity',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {
                'default_res_model': 'crm.lead',
                'default_res_id': self.id,
                'default_activity_type_id': call_type.id if call_type else 2,
                'default_summary': _('Follow-up with prospective patient: %s') % (self.contact_name or self.name),
                'default_user_id': self.user_id.id or self.env.uid,
                'default_date_deadline': fields.Date.today() + timedelta(days=1),
            }
        }

    def action_view_appointments(self):
        """View all appointments originating from or linked to this enquiry."""
        self.ensure_one()
        if not self.appointment_ids:
            return self.action_book_appointment()

        tree_view = self.env.ref('dental_appointment.view_dental_appointment_tree', raise_if_not_found=False)
        form_view = self.env.ref('dental_appointment.view_dental_appointment_form', raise_if_not_found=False)

        action = {
            'name': _('Appointments - %s') % (self.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.appointment',
            'view_mode': 'list,form,calendar',
            'views': [
                (tree_view.id if tree_view else False, 'list'),
                (form_view.id if form_view else False, 'form'),
            ],
            'domain': [('lead_id', '=', self.id)],
            'context': {
                'default_lead_id': self.id,
                'default_patient_id': self.patient_id.id if self.patient_id else False,
            },
        }
        if len(self.appointment_ids) == 1:
            action['views'] = [(form_view.id if form_view else False, 'form')]
            action['res_id'] = self.appointment_ids.id
        return action
