# pyrefly: ignore [missing-import]
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


DIAGNOSIS_CATEGORIES = [
    ('caries', 'Caries & Hard Tissue'),
    ('pulpal', 'Pulpal'),
    ('periapical', 'Periapical'),
    ('periodontal', 'Periodontal & Gingival'),
    ('oral_mucosa', 'Oral Mucosa'),
    ('occlusion', 'Occlusion & Orthodontic'),
    ('tmj', 'TMJ & Orofacial Pain'),
    ('developmental', 'Developmental & Eruption'),
    ('trauma', 'Trauma'),
    ('prosthetic', 'Missing Teeth & Prosthetic'),
    ('other', 'Other'),
]

# Common dental diagnoses (ICD-10 codes) offered on a new database: (code, name, category)
STANDARD_DIAGNOSES = [
    ('K02.0', 'Caries limited to enamel', 'caries'),
    ('K02.1', 'Caries of dentine', 'caries'),
    ('K02.2', 'Caries of cementum (root caries)', 'caries'),
    ('K02.3', 'Arrested dental caries', 'caries'),
    ('K03.0', 'Excessive attrition of teeth', 'caries'),
    ('K03.1', 'Abrasion of teeth', 'caries'),
    ('K03.2', 'Erosion of teeth', 'caries'),
    ('K03.6', 'Deposits (accretions) on teeth', 'periodontal'),
    ('K04.01', 'Reversible pulpitis', 'pulpal'),
    ('K04.02', 'Irreversible pulpitis', 'pulpal'),
    ('K04.1', 'Necrosis of pulp', 'pulpal'),
    ('K04.4', 'Acute apical periodontitis', 'periapical'),
    ('K04.5', 'Chronic apical periodontitis', 'periapical'),
    ('K04.6', 'Periapical abscess with sinus', 'periapical'),
    ('K04.7', 'Periapical abscess without sinus', 'periapical'),
    ('K04.8', 'Radicular cyst', 'periapical'),
    ('K05.0', 'Acute gingivitis', 'periodontal'),
    ('K05.1', 'Chronic gingivitis', 'periodontal'),
    ('K05.2', 'Acute periodontitis / periodontal abscess', 'periodontal'),
    ('K05.3', 'Chronic periodontitis', 'periodontal'),
    ('K06.0', 'Gingival recession', 'periodontal'),
    ('K06.1', 'Gingival enlargement', 'periodontal'),
    ('K08.1', 'Loss of teeth due to accident, extraction or periodontal disease', 'prosthetic'),
    ('K08.3', 'Retained dental root', 'prosthetic'),
    ('K01.1', 'Impacted tooth', 'developmental'),
    ('K00.6', 'Disturbance in tooth eruption', 'developmental'),
    ('K07.2', 'Anomalies of dental arch relationship (malocclusion)', 'occlusion'),
    ('K07.3', 'Anomalies of tooth position (crowding, spacing)', 'occlusion'),
    ('K07.6', 'Temporomandibular joint disorder', 'tmj'),
    ('S02.5', 'Fracture of tooth', 'trauma'),
    ('K12.0', 'Recurrent oral aphthae', 'oral_mucosa'),
    ('B37.0', 'Oral candidiasis', 'oral_mucosa'),
    ('K13.2', 'Leukoplakia of oral mucosa', 'oral_mucosa'),
    ('K12.2', 'Cellulitis and abscess of mouth', 'oral_mucosa'),
    ('K10.3', 'Alveolitis of jaws (dry socket)', 'other'),
    ('K08.8', 'Dentine hypersensitivity / other disorders of teeth', 'other'),
]


class DentalDiagnosisMaster(models.Model):
    _name = 'dental.diagnosis'
    _description = 'Diagnosis Master'
    _order = 'category, code, name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(string='Diagnosis Name', required=True)
    code = fields.Char(string='Diagnosis Code')
    category = fields.Selection(DIAGNOSIS_CATEGORIES, string='Category',
                                help='Groups diagnoses so the dentist can find them quickly while examining.')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for diag in self:
            diag.display_name = f"{diag.code} {diag.name}" if diag.code else diag.name

    @api.model
    def _load_standard_diagnoses(self):
        """Add the common dental diagnoses that are not in the master yet (matched by code or name).

        Runs once when the module is installed and on the upgrade that introduced it; diagnoses the
        clinic created or archived are never duplicated or reactivated.
        """
        existing = self.with_context(active_test=False).search([])
        codes = {(d.code or '').strip().upper() for d in existing if d.code}
        names = {(d.name or '').strip().lower() for d in existing}
        missing = [{'code': code, 'name': name, 'category': category}
                   for code, name, category in STANDARD_DIAGNOSES
                   if code.upper() not in codes and name.lower() not in names]
        return self.create(missing) if missing else self.browse()


class DentalPatientDiagnosis(models.Model):
    _name = 'dental.patient.diagnosis'
    _description = 'Patient Diagnosis'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']

    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    case_id = fields.Many2one('dental.case', string='Dental Case', tracking=True, check_company=True)
    examination_id = fields.Many2one('dental.clinical.examination', string='Examination', tracking=True, check_company=True)
    doctor_id = fields.Many2one('hr.employee.public', string='Doctor', tracking=True)
    diagnosis_id = fields.Many2one('dental.diagnosis', string='Diagnosis', required=True, tracking=True)
    tooth_reference = fields.Char(string='Tooth Reference', tracking=True)
    notes = fields.Text(string='Notes')
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    status = fields.Selection([
        ('suspected', 'Suspected'),
        ('confirmed', 'Confirmed'),
        ('resolved', 'Resolved')
    ], string='Status', default='confirmed', tracking=True)
    diagnosis_code = fields.Char(related='diagnosis_id.code', string='Code')
    diagnosis_name = fields.Char(related='diagnosis_id.name', string='Diagnosis Name')
    tooth_name = fields.Char(string='Tooth', compute='_compute_tooth_name',
                             help='Name of the tooth (or the list of teeth) the diagnosis applies to.')

    @api.depends('case_id.company_id', 'examination_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('case_id', 'examination_id')

    @api.depends('tooth_reference')
    def _compute_tooth_name(self):
        from .dental_tooth_finding import TOOTH_NAMES
        for diag in self:
            teeth = diag._tooth_numbers()
            if len(teeth) == 1:
                diag.tooth_name = TOOTH_NAMES.get(teeth[0], (_("Tooth %s", teeth[0]),))[0]
            elif teeth:
                diag.tooth_name = _("Teeth %s", ", ".join(teeth))
            else:
                diag.tooth_name = _("General")

    def _tooth_numbers(self):
        self.ensure_one()
        return [t.strip() for t in (self.tooth_reference or '').replace(';', ',').split(',') if t.strip()]

    def _tooth_sort_key(self):
        """Chart reading order (18..11, 21..28, then 48..41, 31..38); general diagnoses last."""
        teeth = self._tooth_numbers()
        if not teeth or not teeth[0].isdigit() or len(teeth[0]) != 2:
            return (9, 99)
        quadrant, position = int(teeth[0][0]), int(teeth[0][1])
        # Patient-right quadrants (1/5, 4/8) are read towards the midline, the others away from it
        rank = {1: 0, 5: 0, 2: 1, 6: 1, 4: 2, 8: 2, 3: 3, 7: 3}.get(quadrant, 8)
        return (rank, -position if quadrant in (1, 5, 4, 8) else position)

    def action_mark_confirmed(self):
        self.write({'status': 'confirmed'})

    def action_mark_resolved(self):
        self.write({'status': 'resolved'})

    def action_reopen(self):
        self.write({'status': 'confirmed'})

    @api.constrains('tooth_reference')
    def _check_tooth_reference(self):
        from .dental_tooth_finding import TOOTH_NAMES
        for diag in self.filtered('tooth_reference'):
            teeth = [t.strip() for t in diag.tooth_reference.replace(';', ',').split(',') if t.strip()]
            invalid = [t for t in teeth if t not in TOOTH_NAMES]
            if invalid:
                raise ValidationError(_("Invalid tooth number(s) %(teeth)s. Use FDI notation, e.g. 36 or 11, 21.",
                                        teeth=', '.join(invalid)))

    @api.constrains('examination_id', 'case_id', 'patient_id')
    def _check_examination_consistency(self):
        for diag in self.filtered('examination_id'):
            if diag.examination_id.patient_id != diag.patient_id or (
                    diag.case_id and diag.examination_id.case_id != diag.case_id):
                raise ValidationError(_("A diagnosis must belong to the same patient and case as its examination."))

    @api.model
    def _find_latest_examination(self, case_input, create=True):
        """Examination of the case's current visit (created on first use when ``create``).

        A diagnosis recorded on a follow-up visit is linked to that visit's examination, never to
        an earlier visit's one, so the history of previous visits stays untouched.
        """
        if not case_input:
            return False
        cid = case_input.id if hasattr(case_input, 'id') else case_input
        if not cid or not isinstance(cid, int):
            return False
        case = self.env['dental.case'].browse(cid)
        if not case.exists():
            return False
        exam = case._find_visit_examination()
        if exam or not create or case.state in ('completed', 'cancelled'):
            return exam
        return case._get_visit_examination()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        case_id = res.get('case_id') or self.env.context.get('default_case_id')
        if not case_id and self.env.context.get('active_model') == 'dental.case':
            case_id = self.env.context.get('active_id')

        exam_id = res.get('examination_id') or self.env.context.get('default_examination_id')
        if not exam_id and self.env.context.get('active_model') == 'dental.clinical.examination':
            exam_id = self.env.context.get('active_id')

        if case_id:
            res['case_id'] = case_id
            case = self.env['dental.case'].browse(case_id)
            if case.exists():
                if 'patient_id' in fields_list and not res.get('patient_id') and case.patient_id:
                    res['patient_id'] = case.patient_id.id
                if 'doctor_id' in fields_list and not res.get('doctor_id') and case.doctor_id:
                    res['doctor_id'] = case.doctor_id.id
                if 'examination_id' in fields_list and not exam_id:
                    exam = self._find_latest_examination(case, create=False)
                    if exam:
                        res['examination_id'] = exam.id
                        exam_id = exam.id

        if exam_id and 'examination_id' in fields_list:
            res['examination_id'] = exam_id
            exam = self.env['dental.clinical.examination'].browse(exam_id)
            if exam.exists():
                if 'case_id' in fields_list and not res.get('case_id') and exam.case_id:
                    res['case_id'] = exam.case_id.id
                if 'patient_id' in fields_list and not res.get('patient_id') and exam.patient_id:
                    res['patient_id'] = exam.patient_id.id
                if 'doctor_id' in fields_list and not res.get('doctor_id') and exam.doctor_id:
                    res['doctor_id'] = exam.doctor_id.id

        return res

    @api.onchange('case_id')
    def _onchange_case_id(self):
        case = self.case_id
        if not case:
            return
        if case.patient_id:
            self.patient_id = case.patient_id
        if not self.doctor_id and case.doctor_id:
            self.doctor_id = case.doctor_id
        if not self.examination_id:
            exam = self._find_latest_examination(case, create=False)
            if exam:
                self.examination_id = exam

    @api.onchange('examination_id')
    def _onchange_examination_id(self):
        exam = self.examination_id
        if exam:
            if not self.patient_id and exam.patient_id:
                self.patient_id = exam.patient_id
            if not self.doctor_id and exam.doctor_id:
                self.doctor_id = exam.doctor_id
            if not self.case_id and exam.case_id:
                self.case_id = exam.case_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('case_id') and not vals.get('examination_id'):
                exam = self._find_latest_examination(vals['case_id'])
                if exam:
                    vals['examination_id'] = exam.id
            elif vals.get('examination_id') and not vals.get('case_id'):
                exam = self.env['dental.clinical.examination'].browse(vals['examination_id'])
                if exam.exists() and exam.case_id:
                    vals['case_id'] = exam.case_id.id
        return super().create(vals_list)
