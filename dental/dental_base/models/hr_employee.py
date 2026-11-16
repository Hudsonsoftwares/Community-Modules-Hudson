from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    dental_role = fields.Selection([
        ('dentist', 'Dentist'),
        ('assistant', 'Dental Assistant'),
        ('receptionist', 'Receptionist'),
        ('lab_tech', 'Lab Technician'),
        ('pharmacist', 'Pharmacist'),
        ('manager', 'Clinic Manager'),
        ('admin', 'Dental Administrator'),
    ], string='Dental Role', tracking=True, help='Assigned role within the Dental Clinic system')


    registration_number = fields.Char(
        string='Dental License / Reg No.',
        tracking=True,
        help='Dental Council / State Board registration number for practicing dentists',
    )
    specialization = fields.Char(
        string='Specialization',
        help='e.g., Orthodontics, Endodontics, Periodontics, Prosthodontics, Pedodontics, Oral Surgery, General Dentistry',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Currency',
        readonly=True,
    )
    consultation_fee = fields.Monetary(
        string='Standard Consultation Fee',
        currency_field='currency_id',
        help='Default consultation charge for this doctor',
    )
    max_appointments_per_day = fields.Integer(
        string='Max Appointments / Day',
        default=0,
        tracking=True,
        help='Maximum number of appointments this doctor can take in a single day. 0 means no limit.',
    )
    signature_image = fields.Binary(
        string='Doctor Signature Image',
        attachment=True,
        help='Scanned signature image used for digital prescriptions and treatment consents',
    )
    digital_stamp = fields.Binary(
        string='Digital Clinic Stamp',
        attachment=True,
        help='Digital official stamp used for certifications and official reports',
    )
    is_dentist = fields.Boolean(
        string='Is Dentist',
        compute='_compute_is_dentist',
        store=True,
        help='Technical flag to filter doctors and dentists across clinical appointments and treatments',
    )

    # ---------------------------------------------------------
    # Role-Specific Profile Fields
    # ---------------------------------------------------------
    # 1. Dental Assistant
    assistant_qualification = fields.Char(
        string='Qualification',
        help='Dental Assistant qualification (e.g., Certified Dental Assistant (CDA), Diploma in Dental Assisting)',
    )
    assistant_skills = fields.Char(
        string='Skills',
        help='e.g., Chairside Assisting, Instrument Sterilization, X-Ray Imaging, Impression Pouring',
    )
    assigned_dentist_id = fields.Many2one(
        'hr.employee',
        string='Assigned Dentist',
        domain="[('dental_role', '=', 'dentist')]",
        help='Primary dentist this assistant is assigned to work with',
    )

    # 2. Receptionist
    reception_counter = fields.Char(
        string='Counter / Desk Assignment',
        help='Assigned front desk counter or workstation (e.g., Front Desk Counter 1, Patient Check-in)',
    )

    # 3. Lab Technician
    lab_qualification = fields.Char(
        string='Qualification',
        help='Lab Technician credentials (e.g., Degree/Diploma in Dental Technology)',
    )
    lab_assignment = fields.Char(
        string='Lab Assignment',
        help='Assigned laboratory or fabrication station (e.g., In-House Dental Lab, Prosthetics Section, CAD/CAM)',
    )
    lab_specialization = fields.Char(
        string='Specialization',
        help='e.g., Crown & Bridge, Ceramics, Orthodontic Appliances, Cast Partial Dentures, CAD/CAM Milling',
    )

    # 4. Pharmacist
    pharmacy_license = fields.Char(
        string='Pharmacy License',
        help='State Pharmacy Council License or Pharmacist Registration Number',
    )
    pharmacist_qualification = fields.Char(
        string='Qualification',
        help='Pharmacy degree or diploma (e.g., B.Pharm, D.Pharm, Pharm.D)',
    )
    pharmacy_assignment = fields.Char(
        string='Pharmacy Assignment',
        help='Assigned clinic dispensary or pharmacy counter (e.g., Main Clinic Pharmacy, OPD Dispensary)',
    )

    # 5. Clinic Manager
    managed_branch_ids = fields.Many2many(
        'res.company',
        'employee_managed_company_rel',
        'employee_id',
        'company_id',
        string='Branch Management',
        help='Clinic branches managed by this manager',
    )
    manager_approval_limit = fields.Monetary(
        string='Operational Approval Limit',
        currency_field='currency_id',
        help='Maximum expenditure or operational refund limit the manager can approve',
    )
    manager_permissions = fields.Selection([
        ('full_ops', 'Full Clinic Operations & Staff Management'),
        ('clinical_ops', 'Clinical & Facility Management Only'),
        ('admin_billing', 'Front-Desk, Scheduling & Billing Approvals'),
    ], string='Operational Permissions', default='full_ops')

    # 6. Dental Administrator
    admin_branch_access_ids = fields.Many2many(
        'res.company',
        'employee_admin_company_rel',
        'employee_id',
        'company_id',
        string='Branch Access',
        help='Branches accessible for administrative configuration and audit',
    )
    admin_system_role = fields.Selection([
        ('super_admin', 'Full Dental System Administrator'),
        ('branch_admin', 'Branch Operations & Staff Administrator'),
        ('it_compliance', 'IT, Data Security & Audit Administrator'),
    ], string='Administrative Permissions', default='super_admin')
    admin_notes = fields.Text(
        string='Administrative Scope & Access Privileges',
        help='Summary of administrative scope, role duties, and granted privileges',
    )

    resume_attachment = fields.Binary(
        string='Resume / CV Document',
        attachment=True,
        help='Upload Employee CV or Resume document (PDF, DOCX, etc.)',
    )
    resume_filename = fields.Char(string='Resume Filename')
    resume_upload_date = fields.Date(
        string='Upload Date',
        default=fields.Date.context_today,
    )
    resume_notes = fields.Text(
        string='Resume Summary / Notes',
        help='Brief summary of employee background, education, and credentials',
    )

    @api.onchange('resume_attachment')
    def _onchange_resume_attachment(self):
        if self.resume_attachment:
            self.resume_upload_date = fields.Date.context_today(self)
        else:
            self.resume_upload_date = False

    @api.constrains('max_appointments_per_day')
    def _check_max_appointments_per_day(self):
        for employee in self:
            if employee.max_appointments_per_day < 0:
                raise ValidationError(_('Max Appointments / Day cannot be negative (use 0 for no limit).'))

    @api.depends('dental_role')
    def _compute_is_dentist(self):
        for employee in self:
            employee.is_dentist = (employee.dental_role == 'dentist')

    def action_open_dental_user_access(self):
        """Open the linked user's form, where access rights (groups) are managed.

        Permissions live on res.users only (Staff & Doctors > Users & Access Rights);
        the employee Designation never grants access by itself.
        """
        self.ensure_one()
        if not self.env.user.has_group('dental_base.group_dental_admin'):
            raise AccessError(_('Only Dental Administrators can manage access rights.'))
        if not self.user_id:
            raise UserError(_('%s has no linked system user.', self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Access Rights: %s', self.user_id.name),
            'res_model': 'res.users',
            'res_id': self.user_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    is_dentist = fields.Boolean(readonly=True)
    dental_role = fields.Selection(selection=[], readonly=True)
    registration_number = fields.Char(readonly=True)
    specialization = fields.Char(readonly=True)
    consultation_fee = fields.Monetary(currency_field='currency_id', readonly=True)
    max_appointments_per_day = fields.Integer(readonly=True)
    assistant_qualification = fields.Char(readonly=True)
    assistant_skills = fields.Char(readonly=True)
    assigned_dentist_id = fields.Many2one('hr.employee.public', readonly=True)
    reception_counter = fields.Char(readonly=True)
    lab_qualification = fields.Char(readonly=True)
    lab_assignment = fields.Char(readonly=True)
    lab_specialization = fields.Char(readonly=True)
    pharmacy_license = fields.Char(readonly=True)
    pharmacist_qualification = fields.Char(readonly=True)
    pharmacy_assignment = fields.Char(readonly=True)
    managed_branch_ids = fields.Many2many('res.company', 'employee_public_managed_company_rel', readonly=True)
    manager_approval_limit = fields.Monetary(currency_field='currency_id', readonly=True)
    manager_permissions = fields.Selection(selection=[], readonly=True)
    admin_branch_access_ids = fields.Many2many('res.company', 'employee_public_admin_company_rel', readonly=True)
    admin_system_role = fields.Selection(selection=[], readonly=True)
    admin_notes = fields.Text(readonly=True)
    resume_attachment = fields.Binary(readonly=True)
    resume_filename = fields.Char(readonly=True)
    resume_upload_date = fields.Date(readonly=True)
    resume_notes = fields.Text(readonly=True)
