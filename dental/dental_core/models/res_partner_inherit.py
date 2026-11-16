from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    dental_case_ids = fields.One2many('dental.case', 'patient_id', string='Dental Cases')
    dental_case_count = fields.Integer(compute='_compute_dental_case_count')
    
    dental_examination_ids = fields.One2many('dental.clinical.examination', 'patient_id', string='Clinical Examinations')
    dental_examination_count = fields.Integer(compute='_compute_dental_examination_count')
    
    dental_diagnosis_ids = fields.One2many('dental.patient.diagnosis', 'patient_id', string='Diagnoses')
    dental_diagnosis_count = fields.Integer(compute='_compute_dental_diagnosis_count')
    
    treatment_plan_ids = fields.One2many('dental.treatment.plan', 'patient_id', string='Treatment Plans')
    treatment_plan_count = fields.Integer(compute='_compute_treatment_plan_count')
    
    treatment_session_ids = fields.One2many('dental.treatment.session', 'patient_id', string='Treatment Sessions')
    treatment_session_count = fields.Integer(compute='_compute_treatment_session_count')
    
    tooth_finding_ids = fields.One2many('dental.tooth.finding', 'patient_id', string='Tooth Findings')
    tooth_finding_count = fields.Integer(compute='_compute_tooth_finding_count')

    crm_lead_ids = fields.One2many('crm.lead', 'patient_id', string='Dental Enquiries')
    crm_lead_count = fields.Integer(compute='_compute_crm_lead_count')

    patient_document_ids = fields.One2many(
        'dental.patient.document',
        'patient_id',
        string='Previous Records & X-Rays'
    )
    patient_document_count = fields.Integer(
        string='Records / X-Rays Count',
        compute='_compute_patient_document_count'
    )

    # Read-only timeline from every branch (the records above only cover the user's branches)
    dental_history_ids = fields.One2many(
        'dental.patient.history', 'patient_id', string='Treatment History (All Branches)',
        groups='dental_base.group_dental_dentist,dental_base.group_dental_manager')

    @api.depends('patient_document_ids')
    def _compute_patient_document_count(self):
        for partner in self:
            partner.patient_document_count = len(partner.patient_document_ids)

    @api.depends('crm_lead_ids')
    def _compute_crm_lead_count(self):
        for partner in self:
            partner.crm_lead_count = self.env['crm.lead'].search_count([
                '|', ('patient_id', '=', partner.id), ('partner_id', '=', partner.id)
            ])

    @api.depends('tooth_finding_ids')
    def _compute_tooth_finding_count(self):
        for partner in self:
            partner.tooth_finding_count = len(partner.tooth_finding_ids)

    @api.depends('dental_case_ids')
    def _compute_dental_case_count(self):
        for partner in self:
            partner.dental_case_count = len(partner.dental_case_ids)

    @api.depends('dental_examination_ids')
    def _compute_dental_examination_count(self):
        for partner in self:
            partner.dental_examination_count = len(partner.dental_examination_ids)

    @api.depends('dental_diagnosis_ids')
    def _compute_dental_diagnosis_count(self):
        for partner in self:
            partner.dental_diagnosis_count = len(partner.dental_diagnosis_ids)

    @api.depends('treatment_plan_ids')
    def _compute_treatment_plan_count(self):
        for partner in self:
            partner.treatment_plan_count = len(partner.treatment_plan_ids)

    @api.depends('treatment_session_ids')
    def _compute_treatment_session_count(self):
        for partner in self:
            partner.treatment_session_count = len(partner.treatment_session_ids)

    def action_view_treatment_history(self):
        self.ensure_one()
        return {
            'name': _('Treatment History of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.patient.history',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'search_default_group_by_branch': 1},
        }

    def action_view_dental_cases(self):
        self.ensure_one()
        return {
            'name': 'Dental Cases',
            'type': 'ir.actions.act_window',
            'res_model': 'dental.case',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_view_dental_examinations(self):
        self.ensure_one()
        return {
            'name': 'Clinical Examinations',
            'type': 'ir.actions.act_window',
            'res_model': 'dental.clinical.examination',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_view_dental_diagnoses(self):
        self.ensure_one()
        return {
            'name': 'Diagnoses',
            'type': 'ir.actions.act_window',
            'res_model': 'dental.patient.diagnosis',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_view_treatment_plans(self):
        self.ensure_one()
        return {
            'name': 'Treatment Plans',
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.plan',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_view_treatment_sessions(self):
        self.ensure_one()
        return {
            'name': 'Treatment Sessions',
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.session',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_view_crm_leads(self):
        self.ensure_one()
        return {
            'name': 'Patient Enquiries (CRM)',
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'view_mode': 'list,form,kanban',
            'domain': ['|', ('patient_id', '=', self.id), ('partner_id', '=', self.id)],
            'context': {
                'default_patient_id': self.id,
                'default_partner_id': self.id,
                'default_contact_name': self.name,
                'default_phone': self.phone or self.mobile,
                'default_email_from': self.email,
            },
        }

    def action_view_patient_documents(self):
        self.ensure_one()
        return {
            'name': _('Previous Records & X-Rays'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.patient.document',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }


class DentalPatientDocument(models.Model):
    _name = 'dental.patient.document'
    _description = 'Patient Medical Document & X-Ray'
    _order = 'document_date desc, id desc'

    patient_id = fields.Many2one(
        'res.partner',
        string='Patient',
        required=True,
        ondelete='cascade',
        domain="[('is_dental_patient', '=', True)]",
        index=True
    )
    name = fields.Char(
        string='Document Title / Description',
        required=True,
        help='e.g., Previous OPG Panoramic X-Ray, Past Root Canal Report, Medical Clearance, Referral...'
    )
    document_type = fields.Selection([
        ('xray', 'X-Ray / Radiology Scan (OPG, CBCT, RVG, IOPA)'),
        ('prescription', 'Past Prescription / Treatment Summary'),
        ('lab_report', 'Lab / Pathology Report'),
        ('referral', 'Referral Letter / Clinical Summary'),
        ('insurance', 'Insurance Card / Pre-Auth Document'),
        ('other', 'Other Medical Document')
    ], string='Document Type', default='xray', required=True)

    document_date = fields.Date(
        string='Scan / Document Date',
        default=fields.Date.context_today,
        required=True
    )
    file = fields.Binary(
        string='PDF / Image File',
        required=True,
        attachment=True,
        help='Upload the PDF report, X-Ray image, or scanned document brought by the patient.'
    )
    file_name = fields.Char(string='File Name')
    notes = fields.Text(string='Clinical Notes / Remarks')
    
    uploaded_by = fields.Many2one(
        'res.users',
        string='Uploaded By',
        default=lambda self: self.env.user,
        readonly=True
    )
    upload_date = fields.Datetime(
        string='Uploaded On',
        default=fields.Datetime.now,
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Clinic Branch',
        default=lambda self: self.env.company
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Sync attachment to ir.attachment for patient chatter/documents if not already linked
        for rec in records:
            if rec.file and rec.patient_id:
                fname = rec.file_name or f"{rec.name}.pdf"
                att_exists = self.env['ir.attachment'].search([
                    ('res_model', '=', 'res.partner'),
                    ('res_id', '=', rec.patient_id.id),
                    ('name', '=', fname)
                ], limit=1)
                if not att_exists:
                    import base64
                    file_content = rec.file
                    if isinstance(file_content, str):
                        try:
                            raw_content = base64.b64decode(file_content)
                        except Exception:
                            raw_content = file_content.encode('utf-8')
                    else:
                        raw_content = bytes(file_content)

                    self.env['ir.attachment'].create({
                        'name': fname,
                        'raw': raw_content,
                        'res_model': 'res.partner',
                        'res_id': rec.patient_id.id,
                        'mimetype': 'application/pdf' if fname.lower().endswith('.pdf') else False,
                        'description': f"[{rec.document_type.upper()}] {rec.name}",
                        'company_id': rec.company_id.id if rec.company_id else False,
                    })
        return records
