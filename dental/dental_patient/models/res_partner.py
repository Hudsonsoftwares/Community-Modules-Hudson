from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext
from datetime import date
from dateutil.relativedelta import relativedelta

ALLERGY_STATUS = [
    ('unknown', 'Not Recorded'),
    ('none', 'No Known Allergies'),
    ('known', 'Known Allergies'),
]
# Free-text entries that mean "no known allergies" rather than an actual allergy
NO_ALLERGY_VALUES = {
    'nil', 'none', 'no', 'n/a', 'na', '-', 'nka', 'nkda', 'nil known', 'none known',
    'no known allergies', 'no known allergy', 'no known drug allergies', 'no allergies', 'no allergy',
}


def clean_allergy_text(value):
    """Plain allergy text, or '' when the entry is empty or only says 'no known allergies'."""
    text = html2plaintext(value or '').strip() if value else ''
    return '' if text.lower().rstrip('.') in NO_ALLERGY_VALUES else text


class ResPartner(models.Model):
    _inherit = 'res.partner'
    # Find patients by Patient ID or phone in every patient field and search (e.g. at another branch)
    _rec_names_search = ('complete_name', 'email', 'ref', 'vat', 'dental_patient_id', 'phone')

    is_dental_patient = fields.Boolean(
        string='Is Dental Patient', 
        default=False,
        help="Enable this option to mark this contact as a dental patient and display dental-specific information."
    )
    dental_patient_id = fields.Char(string='Patient ID', readonly=True, copy=False, default='New')
    
    date_of_birth = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender')
    
    blood_group = fields.Selection([
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-')
    ], string='Blood Group')
    
    guardian_id = fields.Many2one('res.partner', string='Guardian')
    emergency_contact = fields.Char(string='Emergency Contact')
    
    active_clinic_id = fields.Many2one(
        'res.company', 
        string='Active Clinic/Branch',
        default=lambda self: self.env.company
    )
    
    # Medical History
    medical_history = fields.Html(string='Medical History')
    allergies = fields.Html(string='Allergies')
    # Explicit status: an empty allergy field must never be read as "no allergies"
    allergy_status = fields.Selection(ALLERGY_STATUS, string='Allergy Status', default='unknown', tracking=True,
                                      help="Not Recorded: the patient has not been asked yet.\n"
                                           "No Known Allergies: confirmed with the patient.\n"
                                           "Known Allergies: listed in Allergies.")
    allergy_verified_by = fields.Many2one('res.users', string='Allergies Verified By', readonly=True, copy=False)
    allergy_verified_date = fields.Datetime(string='Allergies Verified On', readonly=True, copy=False)
    existing_conditions = fields.Html(string='Existing Conditions')
    current_medications = fields.Html(string='Current Medications')
    previous_surgeries = fields.Html(string='Previous Surgeries')
    
    # Dental History
    dental_history = fields.Html(string='Dental History')
    previous_dental_treatments = fields.Html(string='Previous Dental Treatments')
    last_dental_visit = fields.Date(string='Last Dental Visit')
    oral_hygiene = fields.Selection([
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], string='Oral Hygiene')
    smoking_tobacco_history = fields.Selection([
        ('none', 'None'),
        ('occasional', 'Occasional'),
        ('frequent', 'Frequent')
    ], string='Smoking/Tobacco History')
    brushing_frequency = fields.Selection([
        ('rarely', 'Rarely'),
        ('once', 'Once daily'),
        ('twice', 'Twice daily')
    ], string='Brushing Frequency')
    
    clinical_alerts = fields.Html(string='Clinical Alerts')

    @api.depends('date_of_birth')
    def _compute_age(self):
        for record in self:
            if record.date_of_birth:
                record.age = relativedelta(date.today(), record.date_of_birth).years
            else:
                record.age = 0

    @api.constrains('allergy_status', 'allergies')
    def _check_allergy_status(self):
        for partner in self:
            text = clean_allergy_text(partner.allergies)
            if partner.allergy_status == 'known' and not text:
                raise ValidationError(_("%s: list the known allergies, or set the allergy status to "
                                        "'No Known Allergies' or 'Not Recorded'.", partner.display_name))
            if partner.allergy_status == 'none' and text:
                raise ValidationError(_("%s: allergies are listed, so the allergy status cannot be "
                                        "'No Known Allergies'.", partner.display_name))

    @api.onchange('allergies')
    def _onchange_allergies_status(self):
        text = clean_allergy_text(self.allergies)
        if text:
            self.allergy_status = 'known'
        elif self.allergy_status == 'known':
            self.allergy_status = 'unknown'

    def _prepare_allergy_vals(self, vals):
        """Derive the status from the allergy text when only the text is written, and stamp who
        confirmed the allergy information and when."""
        if 'allergies' not in vals and 'allergy_status' not in vals:
            return vals
        vals = dict(vals)
        if 'allergies' in vals and 'allergy_status' not in vals:
            raw = vals['allergies']
            if clean_allergy_text(raw):
                vals['allergy_status'] = 'known'
            elif raw and html2plaintext(raw).strip():
                vals['allergy_status'] = 'none'       # e.g. "NKDA"
            else:
                vals['allergy_status'] = 'unknown'
        if vals.get('allergy_status') in ('none', 'known'):
            vals.update(allergy_verified_by=self.env.user.id, allergy_verified_date=fields.Datetime.now())
        elif vals.get('allergy_status') == 'unknown':
            vals.update(allergy_verified_by=False, allergy_verified_date=False)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._prepare_allergy_vals(vals) for vals in vals_list]
        for vals in vals_list:
            is_patient = vals.get('is_dental_patient', self.env.context.get('default_is_dental_patient', False))
            if is_patient and vals.get('dental_patient_id', _('New')) == _('New'):
                vals['dental_patient_id'] = self.env['ir.sequence'].next_by_code('dental.patient') or _('New')
            if is_patient:
                vals['company_id'] = False   # patients are shared by all branches (dental_base/SECURITY.md)
        return super(ResPartner, self).create(vals_list)

    def write(self, vals):
        vals = self._prepare_allergy_vals(vals)
        # Patients are shared by all branches: never tie one to a single branch
        if vals.get('is_dental_patient'):
            return super().write(dict(vals, company_id=False))
        if vals.get('company_id') and 'is_dental_patient' not in vals:
            patients = self.filtered('is_dental_patient')
            if patients:
                super(ResPartner, patients).write(dict(vals, company_id=False))
                return super(ResPartner, self - patients).write(vals)
        return super().write(vals)

    @api.onchange('name', 'date_of_birth', 'phone')
    def _onchange_check_duplicate_patient(self):
        if not self.is_dental_patient:
            return
            
        domain = [('is_dental_patient', '=', True)]
        origin_id = self._origin.id if self._origin else False
        if origin_id:
            domain.append(('id', '!=', origin_id))
            
        if self.phone:
            duplicate = self.env['res.partner'].search(domain + [('phone', '=', self.phone)], limit=1)
            if duplicate:
                return {
                    'warning': {
                        'title': _('Duplicate Patient Warning'),
                        'message': _('A patient with phone number %s already exists: %s') % (self.phone, duplicate.name)
                    }
                }
                
        if self.name and self.date_of_birth:
            duplicate = self.env['res.partner'].search(domain + [
                ('name', '=ilike', self.name),
                ('date_of_birth', '=', self.date_of_birth)
            ], limit=1)
            if duplicate:
                return {
                    'warning': {
                        'title': _('Duplicate Patient Warning'),
                        'message': _('A patient with the same name and Date of Birth already exists: %s') % duplicate.name
                    }
                }

    def action_book_appointment(self):
        self.ensure_one()
        # Overridden with full logic in dental_appointment
        return True

    def action_open_guided_booking_flow(self):
        self.ensure_one()
        # Overridden with full logic in dental_appointment
        return True

    def action_print_patient_id_card(self):
        """Generate and print the physical CR80 Patient ID Card."""
        self.ensure_one()
        return self.env.ref('dental_patient.action_report_dental_patient_id_card').report_action(self)
