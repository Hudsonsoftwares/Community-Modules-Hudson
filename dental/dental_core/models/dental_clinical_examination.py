from odoo import models, fields, api, _, Command
from odoo.exceptions import ValidationError

from .dental_tooth_finding import TOOTH_NAMES

NORMAL_ABNORMAL = [('normal', 'Normal'), ('abnormal', 'Abnormal')]
AMOUNT = [('none', 'None'), ('mild', 'Mild'), ('moderate', 'Moderate'), ('heavy', 'Heavy')]
RISK = [('low', 'Low'), ('moderate', 'Moderate'), ('high', 'High')]
BPE_SCORES = [('0', '0'), ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('star', '*')]

# Intraoral soft-tissue sites screened one by one (field -> label used in the summary)
INTRAORAL_SITES = {
    'io_lips': 'Lips',
    'io_buccal_mucosa': 'Labial / Buccal Mucosa',
    'io_tongue': 'Tongue',
    'io_floor_of_mouth': 'Floor of Mouth',
    'io_hard_palate': 'Hard Palate',
    'io_soft_palate': 'Soft Palate',
    'io_oropharynx': 'Oropharynx / Tonsils',
    'io_frenum': 'Frenal Attachments',
}
# BPE sextants in charting order (upper row, then lower row as seen facing the patient)
BPE_SEXTANTS = ('bpe_ur', 'bpe_ua', 'bpe_ul', 'bpe_lr', 'bpe_la', 'bpe_ll')

# Fields that mark each examination section as recorded (section -> fields)
SECTION_FIELDS = {
    'extraoral': ('eo_facial_symmetry', 'eo_facial_profile', 'eo_lip_competence', 'eo_lymph_nodes', 'eo_tmj_status',
                  'eo_mouth_opening', 'eo_muscles', 'eo_swelling', 'eo_notes'),
    'intraoral': tuple(INTRAORAL_SITES) + ('oral_hygiene', 'io_plaque', 'io_calculus', 'io_saliva', 'io_lesion_present',
                                           'soft_tissue_findings'),
    'dental': ('dentition', 'molar_relation', 'overjet', 'overbite', 'crossbite', 'crowding', 'tooth_wear', 'occlusion',
               'tooth_condition_summary', 'tooth_finding_ids'),
    'periodontal': ('perio_status', 'perio_gingival_color', 'perio_bleeding', 'gum_condition', 'perio_notes',
                    'perio_chart_ids') + BPE_SEXTANTS,
    'findings': ('clinical_findings', 'radiographic_findings', 'investigation_notes'),
    'diagnosis': ('diagnosis_ids', 'provisional_diagnosis', 'differential_diagnosis'),
    'assessment': ('clinical_impression', 'caries_risk', 'perio_risk', 'prognosis', 'treatment_urgency',
                   'recommended_treatment'),
}

# Tooth conditions counted by the DMFT index
DMFT_DECAYED = ('caries',)
DMFT_MISSING = ('missing',)
DMFT_FILLED = ('restoration', 'crown', 'root_canal')


class DentalClinicalExamination(models.Model):
    """Structured clinical examination of one visit.

    The dentist works through the sections in the order of a standard dental examination:
    extraoral, intraoral (soft tissues), dental (hard tissues and occlusion), periodontal,
    clinical findings and investigations, diagnosis and assessment. Tooth-level findings come
    from the odontogram of the case (``tooth_finding_ids``) and the periodontal chart
    (``perio_chart_ids``). ``examination_summary`` is a plain-text digest of everything recorded,
    stored so the patient's Clinical Timeline can show it.
    """
    _name = 'dental.clinical.examination'
    _description = 'Clinical Examination'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']

    name = fields.Char(string='Examination Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    case_id = fields.Many2one('dental.case', string='Dental Case', required=True, tracking=True, check_company=True)
    appointment_id = fields.Many2one('dental.appointment', string='Visit', index=True, tracking=True, check_company=True,
                                     help='The appointment (visit) this consultation was recorded in.')
    doctor_id = fields.Many2one('hr.employee.public', string='Doctor', tracking=True)
    examination_date = fields.Datetime(string='Examination Date', default=fields.Datetime.now, required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'In Progress'),
        ('done', 'Completed'),
    ], string='Examination Status', default='draft', required=True, copy=False, tracking=True)
    completed_by_id = fields.Many2one('res.users', string='Signed Off By', readonly=True, copy=False)
    completed_date = fields.Datetime(string='Signed Off On', readonly=True, copy=False)
    continued_from_id = fields.Many2one('dental.clinical.examination', string='Continued From', readonly=True, copy=False,
                                        index='btree_not_null', ondelete='set null',
                                        help='Earlier examination whose findings were carried forward into this one.')

    # Live medical alerts of the patient, shown at the top of the examination
    patient_allergy_status = fields.Selection(related='patient_id.allergy_status', string='Allergy Status')
    patient_allergies = fields.Html(related='patient_id.allergies', string='Allergies')
    patient_clinical_alerts = fields.Html(related='patient_id.clinical_alerts', string='Clinical Alerts')
    # Patient card at the top of the examination
    patient_image = fields.Image(related='patient_id.image_128', string='Patient Photo')
    patient_age = fields.Integer(related='patient_id.age', string='Patient Age')
    patient_gender = fields.Selection(related='patient_id.gender', string='Patient Gender')

    chief_complaint = fields.Text(string='Chief Complaint')
    presenting_complaint = fields.Text(string='Presenting Complaint',
                                       help='History of the presenting complaint: onset, duration, character, aggravating and relieving factors.')

    # ------------------------------------------------------------------
    # 1. Extraoral examination
    # ------------------------------------------------------------------
    eo_facial_symmetry = fields.Selection([('symmetrical', 'Symmetrical'), ('asymmetrical', 'Asymmetrical')],
                                          string='Facial Symmetry')
    eo_facial_profile = fields.Selection([('straight', 'Straight'), ('convex', 'Convex'), ('concave', 'Concave')],
                                         string='Facial Profile')
    eo_lip_competence = fields.Selection([('competent', 'Competent'), ('potentially', 'Potentially Competent'),
                                          ('incompetent', 'Incompetent')], string='Lip Competence')
    eo_swelling = fields.Boolean(string='Facial Swelling')
    eo_skin = fields.Char(string='Skin & Lips', help='Colour, lesions, scars or swelling of the face and lips.')
    eo_lymph_nodes = fields.Selection([('not_palpable', 'Not Palpable'), ('palpable', 'Palpable, Non-tender'),
                                       ('tender', 'Palpable & Tender')], string='Lymph Nodes')
    eo_lymph_nodes_detail = fields.Char(string='Lymph Node Details', help='Group, side, size, consistency, mobility.')
    eo_tmj_status = fields.Selection(NORMAL_ABNORMAL, string='TMJ')
    eo_tmj_clicking = fields.Boolean(string='Clicking')
    eo_tmj_crepitus = fields.Boolean(string='Crepitus')
    eo_tmj_pain = fields.Boolean(string='Pain / Tenderness')
    eo_tmj_deviation = fields.Boolean(string='Deviation on Opening')
    eo_mouth_opening = fields.Integer(string='Mouth Opening (mm)', help='Maximum inter-incisal opening.')
    eo_muscles = fields.Selection([('normal', 'Non-tender'), ('tender', 'Tender')], string='Muscles of Mastication')
    eo_notes = fields.Text(string='Extraoral Notes')

    # ------------------------------------------------------------------
    # 2. Intraoral examination (soft tissues and hygiene)
    # ------------------------------------------------------------------
    io_lips = fields.Selection(NORMAL_ABNORMAL, string='Lips')
    io_buccal_mucosa = fields.Selection(NORMAL_ABNORMAL, string='Labial / Buccal Mucosa')
    io_tongue = fields.Selection(NORMAL_ABNORMAL, string='Tongue')
    io_floor_of_mouth = fields.Selection(NORMAL_ABNORMAL, string='Floor of Mouth')
    io_hard_palate = fields.Selection(NORMAL_ABNORMAL, string='Hard Palate')
    io_soft_palate = fields.Selection(NORMAL_ABNORMAL, string='Soft Palate')
    io_oropharynx = fields.Selection(NORMAL_ABNORMAL, string='Oropharynx / Tonsils')
    io_frenum = fields.Selection(NORMAL_ABNORMAL, string='Frenal Attachments')
    io_saliva = fields.Selection([('normal', 'Normal'), ('reduced', 'Reduced / Dry Mouth'), ('increased', 'Increased')],
                                 string='Saliva')
    oral_hygiene = fields.Selection([
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], string='Oral Hygiene')
    io_plaque = fields.Selection(AMOUNT, string='Plaque')
    io_calculus = fields.Selection(AMOUNT, string='Calculus')
    io_stains = fields.Selection([('none', 'None'), ('extrinsic', 'Extrinsic'), ('intrinsic', 'Intrinsic')], string='Stains')
    io_halitosis = fields.Boolean(string='Halitosis')
    io_lesion_present = fields.Boolean(string='Oral Lesion Present')
    io_lesion_description = fields.Text(string='Lesion Description',
                                        help='Site, size, colour, surface, consistency, duration and whether it is painful.')
    soft_tissue_findings = fields.Text(string='Soft Tissue Findings')

    # ------------------------------------------------------------------
    # 3. Dental examination (hard tissues and occlusion)
    # ------------------------------------------------------------------
    dentition = fields.Selection([('primary', 'Primary'), ('mixed', 'Mixed'), ('permanent', 'Permanent')], string='Dentition')
    molar_relation = fields.Selection([('class_1', 'Class I'), ('class_2_div1', 'Class II Div 1'),
                                       ('class_2_div2', 'Class II Div 2'), ('class_3', 'Class III')],
                                      string='Molar Relationship (Angle)')
    overjet = fields.Float(string='Overjet (mm)', digits=(4, 1))
    overbite = fields.Float(string='Overbite (mm)', digits=(4, 1))
    crossbite = fields.Selection([('none', 'None'), ('anterior', 'Anterior'), ('posterior', 'Posterior'),
                                  ('both', 'Anterior & Posterior')], string='Crossbite')
    open_bite = fields.Boolean(string='Open Bite')
    crowding = fields.Selection([('none', 'None'), ('mild', 'Mild'), ('moderate', 'Moderate'), ('severe', 'Severe')],
                                string='Crowding')
    spacing = fields.Boolean(string='Spacing / Diastema')
    tooth_wear = fields.Selection([('none', 'None'), ('attrition', 'Attrition'), ('abrasion', 'Abrasion'),
                                   ('erosion', 'Erosion'), ('mixed', 'Mixed')], string='Tooth Wear')
    occlusion = fields.Char(string='Occlusion Notes')
    tooth_condition_summary = fields.Text(string='Tooth Condition Summary')
    tooth_finding_ids = fields.One2many('dental.tooth.finding', 'examination_id', string='Tooth Findings')
    tooth_finding_count = fields.Integer(string='Tooth Findings Recorded', compute='_compute_tooth_finding_count')
    dmft_decayed = fields.Integer(string='Decayed (D)', compute='_compute_dmft')
    dmft_missing = fields.Integer(string='Missing (M)', compute='_compute_dmft')
    dmft_filled = fields.Integer(string='Filled (F)', compute='_compute_dmft')
    dmft_index = fields.Integer(string='DMFT', compute='_compute_dmft',
                                help='Decayed + Missing + Filled teeth on the patient chart at the time of this examination.')

    # ------------------------------------------------------------------
    # 4. Periodontal examination
    # ------------------------------------------------------------------
    perio_gingival_color = fields.Selection([('coral_pink', 'Coral Pink'), ('red', 'Red / Erythematous'),
                                             ('bluish', 'Bluish-Red'), ('pale', 'Pale'), ('pigmented', 'Pigmented')],
                                            string='Gingival Colour')
    perio_gingival_consistency = fields.Selection([('firm', 'Firm & Resilient'), ('soft', 'Soft / Oedematous'),
                                                   ('fibrotic', 'Fibrotic')], string='Gingival Consistency')
    perio_gingival_contour = fields.Selection([('normal', 'Normal / Knife-edge'), ('rolled', 'Rolled Margins'),
                                               ('enlarged', 'Enlarged'), ('cratered', 'Cratered')], string='Gingival Contour')
    perio_bleeding = fields.Selection([('none', 'None'), ('localized', 'Localized'), ('generalized', 'Generalized')],
                                      string='Bleeding on Probing')
    perio_bop_percent = fields.Float(string='BOP (%)', digits=(5, 1))
    perio_plaque_percent = fields.Float(string='Plaque Score (%)', digits=(5, 1))
    perio_recession = fields.Selection([('none', 'None'), ('localized', 'Localized'), ('generalized', 'Generalized')],
                                       string='Gingival Recession')
    perio_suppuration = fields.Boolean(string='Suppuration')
    bpe_ur = fields.Selection(BPE_SCORES, string='BPE Upper Right')
    bpe_ua = fields.Selection(BPE_SCORES, string='BPE Upper Anterior')
    bpe_ul = fields.Selection(BPE_SCORES, string='BPE Upper Left')
    bpe_lr = fields.Selection(BPE_SCORES, string='BPE Lower Right')
    bpe_la = fields.Selection(BPE_SCORES, string='BPE Lower Anterior')
    bpe_ll = fields.Selection(BPE_SCORES, string='BPE Lower Left')
    bpe_max = fields.Char(string='Highest BPE Score', compute='_compute_bpe_max')
    perio_status = fields.Selection([('healthy', 'Periodontal Health'), ('gingivitis', 'Gingivitis'),
                                     ('periodontitis', 'Periodontitis'), ('stable', 'Stable (Maintenance)')],
                                    string='Periodontal Diagnosis')
    perio_stage = fields.Selection([('1', 'Stage I'), ('2', 'Stage II'), ('3', 'Stage III'), ('4', 'Stage IV')],
                                   string='Stage', help='Severity and complexity (2017 AAP/EFP classification).')
    perio_grade = fields.Selection([('a', 'Grade A'), ('b', 'Grade B'), ('c', 'Grade C')],
                                   string='Grade', help='Rate of progression (2017 AAP/EFP classification).')
    perio_extent = fields.Selection([('localized', 'Localized'), ('generalized', 'Generalized'),
                                     ('molar_incisor', 'Molar-Incisor Pattern')], string='Extent')
    gum_condition = fields.Char(string='Gingival Notes')
    perio_notes = fields.Text(string='Periodontal Notes')
    perio_chart_ids = fields.One2many('dental.examination.perio.line', 'examination_id', string='Periodontal Chart')
    perio_max_depth = fields.Integer(string='Deepest Pocket (mm)', compute='_compute_perio_chart_stats')
    perio_max_depth_tooth = fields.Char(string='Deepest Pocket Tooth', compute='_compute_perio_chart_stats')

    # ------------------------------------------------------------------
    # 5. Clinical findings and investigations
    # ------------------------------------------------------------------
    clinical_findings = fields.Text(string='Clinical Findings')
    radiographs_taken = fields.Char(string='Radiographs Taken', help='E.g. OPG, IOPA 36, bitewings, CBCT.')
    radiographic_findings = fields.Text(string='Radiographic Findings')
    investigation_notes = fields.Text(string='Other Investigations', help='Pulp vitality, biopsy, laboratory tests, photographs.')
    additional_notes = fields.Text(string='Additional Notes')

    # Vitals
    height = fields.Float(string='Height (cm)')
    weight = fields.Float(string='Weight (kg)')
    bmi = fields.Float(string='BMI', compute='_compute_bmi', store=True)
    temperature = fields.Float(string='Temperature (°C)')
    blood_pressure = fields.Char(string='Blood Pressure (mmHg)')
    pulse_rate = fields.Integer(string='Pulse Rate (bpm)')
    respiratory_rate = fields.Integer(string='Respiratory Rate (bpm)')
    oxygen_saturation = fields.Float(string='Oxygen Saturation (%)')

    # ------------------------------------------------------------------
    # 6. Diagnosis
    # ------------------------------------------------------------------
    diagnosis_ids = fields.One2many('dental.patient.diagnosis', 'examination_id', string='Diagnoses')
    provisional_diagnosis = fields.Text(string='Provisional Diagnosis')
    differential_diagnosis = fields.Text(string='Differential Diagnosis')

    # ------------------------------------------------------------------
    # 7. Assessment
    # ------------------------------------------------------------------
    clinical_impression = fields.Text(string='Clinical Impression')
    caries_risk = fields.Selection(RISK, string='Caries Risk')
    perio_risk = fields.Selection(RISK, string='Periodontal Risk')
    oral_cancer_risk = fields.Selection(RISK, string='Oral Cancer Risk')
    prognosis = fields.Selection([('good', 'Good'), ('fair', 'Fair'), ('questionable', 'Questionable'),
                                  ('poor', 'Poor'), ('hopeless', 'Hopeless')], string='Overall Prognosis')
    treatment_urgency = fields.Selection([('routine', 'Routine'), ('soon', 'Soon (within weeks)'),
                                          ('urgent', 'Urgent'), ('emergency', 'Emergency')], string='Treatment Urgency')
    recommended_treatment = fields.Text(string='Recommended Treatment')
    recall_interval = fields.Selection([('3', '3 Months'), ('6', '6 Months'), ('12', '12 Months'), ('24', '24 Months')],
                                       string='Recommended Recall')
    referral_required = fields.Boolean(string='Referral Required')
    referral_to = fields.Char(string='Refer To', help='Specialist or service, e.g. Endodontist, Oral Surgeon, Physician.')
    referral_reason = fields.Text(string='Referral Reason')
    patient_informed = fields.Boolean(string='Findings Explained to Patient')

    # ------------------------------------------------------------------
    # Progress and summary
    # ------------------------------------------------------------------
    extraoral_recorded = fields.Boolean(string='Extraoral Recorded', compute='_compute_sections')
    intraoral_recorded = fields.Boolean(string='Intraoral Recorded', compute='_compute_sections')
    dental_recorded = fields.Boolean(string='Dental Recorded', compute='_compute_sections')
    periodontal_recorded = fields.Boolean(string='Periodontal Recorded', compute='_compute_sections')
    findings_recorded = fields.Boolean(string='Findings Recorded', compute='_compute_sections')
    diagnosis_recorded = fields.Boolean(string='Diagnosis Recorded', compute='_compute_sections')
    assessment_recorded = fields.Boolean(string='Assessment Recorded', compute='_compute_sections')
    sections_progress = fields.Float(string='Examination Progress', compute='_compute_sections',
                                     help='Share of the seven examination sections with something recorded.')
    examination_summary = fields.Text(
        string='Examination Summary', compute='_compute_examination_summary', store=True,
        help='Plain-text digest of the recorded examination, shown in the Clinical Timeline.')

    @api.depends('case_id.company_id', 'appointment_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('case_id', 'appointment_id')

    @api.depends('height', 'weight')
    def _compute_bmi(self):
        for rec in self:
            if rec.height > 0 and rec.weight > 0:
                height_m = rec.height / 100.0
                rec.bmi = rec.weight / (height_m * height_m)
            else:
                rec.bmi = 0.0

    @api.depends('tooth_finding_ids')
    def _compute_tooth_finding_count(self):
        for rec in self:
            rec.tooth_finding_count = len(rec.tooth_finding_ids)

    @api.depends('patient_id', 'tooth_finding_ids.condition', 'tooth_finding_ids.finding_date', 'state', 'completed_date')
    def _compute_dmft(self):
        """DMFT of the patient's chart as it stood at this examination (latest finding per tooth)."""
        Finding = self.env['dental.tooth.finding']
        for rec in self:
            decayed = missing = filled = 0
            if rec.patient_id:
                as_of = rec.completed_date if rec.state == 'done' and rec.completed_date else fields.Datetime.now()
                findings = Finding.search([('patient_id', '=', rec.patient_id.id), ('finding_date', '<=', as_of)],
                                          order='finding_date desc, id desc')
                latest = {}
                for finding in findings:
                    latest.setdefault(finding.tooth_number, finding.condition)
                for condition in latest.values():
                    decayed += condition in DMFT_DECAYED
                    missing += condition in DMFT_MISSING
                    filled += condition in DMFT_FILLED
            rec.dmft_decayed, rec.dmft_missing, rec.dmft_filled = decayed, missing, filled
            rec.dmft_index = decayed + missing + filled

    @api.depends(*BPE_SEXTANTS)
    def _compute_bpe_max(self):
        order = [key for key, _label in BPE_SCORES]
        for rec in self:
            scores = [rec[f] for f in BPE_SEXTANTS if rec[f]]
            if not scores:
                rec.bpe_max = False
                continue
            numeric = [s for s in scores if s != 'star']
            best = max(numeric, key=order.index) if numeric else '0'
            rec.bpe_max = best + ('*' if 'star' in scores else '')

    @api.depends('perio_chart_ids.max_depth', 'perio_chart_ids.tooth_number')
    def _compute_perio_chart_stats(self):
        for rec in self:
            deepest = max(rec.perio_chart_ids, key=lambda l: l.max_depth, default=False)
            rec.perio_max_depth = deepest.max_depth if deepest else 0
            rec.perio_max_depth_tooth = deepest.tooth_number if deepest and deepest.max_depth else False

    @api.depends(*{f for names in SECTION_FIELDS.values() for f in names})
    def _compute_sections(self):
        for rec in self:
            done = 0
            for section, names in SECTION_FIELDS.items():
                recorded = any(rec[name] for name in names)
                rec[f'{section}_recorded'] = recorded
                done += recorded
            rec.sections_progress = round(100.0 * done / len(SECTION_FIELDS), 1)

    # ------------------------------------------------------------------
    # Summary for the Clinical Timeline
    # ------------------------------------------------------------------
    def _label(self, field_name):
        """Display label of a selection value of this record."""
        value = self[field_name]
        if not value:
            return ''
        return dict(self._fields[field_name]._description_selection(self.env)).get(value, value)

    def _summary_section(self, title, parts):
        parts = [p for p in parts if p]
        return f"{title}: {'; '.join(parts)}" if parts else ''

    @api.depends(
        'chief_complaint', 'presenting_complaint', 'clinical_findings', 'additional_notes',
        'eo_facial_symmetry', 'eo_facial_profile', 'eo_lip_competence', 'eo_swelling', 'eo_skin', 'eo_lymph_nodes',
        'eo_lymph_nodes_detail', 'eo_tmj_status', 'eo_tmj_clicking', 'eo_tmj_crepitus', 'eo_tmj_pain', 'eo_tmj_deviation',
        'eo_mouth_opening', 'eo_muscles', 'eo_notes',
        *INTRAORAL_SITES, 'io_saliva', 'oral_hygiene', 'io_plaque', 'io_calculus', 'io_stains', 'io_halitosis',
        'io_lesion_present', 'io_lesion_description', 'soft_tissue_findings',
        'dentition', 'molar_relation', 'overjet', 'overbite', 'crossbite', 'open_bite', 'crowding', 'spacing', 'tooth_wear',
        'occlusion', 'tooth_condition_summary',
        'tooth_finding_ids.tooth_number', 'tooth_finding_ids.condition', 'tooth_finding_ids.surfaces',
        'perio_status', 'perio_stage', 'perio_grade', 'perio_extent', 'perio_gingival_color', 'perio_gingival_consistency',
        'perio_gingival_contour', 'perio_bleeding', 'perio_bop_percent', 'perio_plaque_percent', 'perio_recession',
        'perio_suppuration', *BPE_SEXTANTS, 'gum_condition', 'perio_notes',
        'perio_chart_ids.tooth_number', 'perio_chart_ids.max_depth', 'perio_chart_ids.mobility', 'perio_chart_ids.furcation',
        'radiographs_taken', 'radiographic_findings', 'investigation_notes',
        'diagnosis_ids.diagnosis_id', 'diagnosis_ids.tooth_reference', 'diagnosis_ids.status',
        'provisional_diagnosis', 'differential_diagnosis',
        'clinical_impression', 'caries_risk', 'perio_risk', 'oral_cancer_risk', 'prognosis', 'treatment_urgency',
        'recommended_treatment', 'recall_interval', 'referral_required', 'referral_to', 'referral_reason',
    )
    def _compute_examination_summary(self):
        for rec in self:
            rec.examination_summary = '\n'.join(filter(None, rec._summary_lines())) or False

    def _summary_lines(self):
        self.ensure_one()
        lbl = self._label
        lines = []
        if self.chief_complaint:
            lines.append(_("Chief complaint: %s", self.chief_complaint.strip()))
        if self.presenting_complaint:
            lines.append(_("Presenting complaint: %s", self.presenting_complaint.strip()))

        # Extraoral
        tmj = lbl('eo_tmj_status')
        tmj_signs = [self._fields[f].string.lower() for f in ('eo_tmj_clicking', 'eo_tmj_crepitus', 'eo_tmj_pain', 'eo_tmj_deviation')
                     if self[f]]
        if tmj_signs:
            tmj = f"{tmj or _('Signs')} ({', '.join(tmj_signs)})"
        lines.append(self._summary_section(_("Extraoral"), [
            lbl('eo_facial_symmetry') and _("Face %s", lbl('eo_facial_symmetry').lower()),
            lbl('eo_facial_profile') and _("%s profile", lbl('eo_facial_profile')),
            lbl('eo_lip_competence') and _("Lips %s", lbl('eo_lip_competence').lower()),
            self.eo_swelling and _("Facial swelling"),
            self.eo_skin,
            lbl('eo_lymph_nodes') and _("Lymph nodes %s", lbl('eo_lymph_nodes').lower())
            + (f" ({self.eo_lymph_nodes_detail})" if self.eo_lymph_nodes_detail else ''),
            tmj and _("TMJ %s", tmj),
            self.eo_mouth_opening and _("Mouth opening %s mm", self.eo_mouth_opening),
            lbl('eo_muscles') and _("Muscles %s", lbl('eo_muscles').lower()),
            self.eo_notes,
        ]))

        # Intraoral
        abnormal = [label for f, label in INTRAORAL_SITES.items() if self[f] == 'abnormal']
        all_normal = not abnormal and any(self[f] == 'normal' for f in INTRAORAL_SITES)
        lines.append(self._summary_section(_("Intraoral"), [
            all_normal and _("Soft tissues normal"),
            abnormal and _("Abnormal: %s", ', '.join(abnormal)),
            lbl('oral_hygiene') and _("Oral hygiene %s", lbl('oral_hygiene').lower()),
            lbl('io_plaque') and _("Plaque %s", lbl('io_plaque').lower()),
            lbl('io_calculus') and _("Calculus %s", lbl('io_calculus').lower()),
            self.io_stains not in (False, 'none') and _("%s stains", lbl('io_stains')),
            lbl('io_saliva') and self.io_saliva != 'normal' and _("Saliva %s", lbl('io_saliva').lower()),
            self.io_halitosis and _("Halitosis"),
            self.io_lesion_present and _("Lesion: %s", (self.io_lesion_description or _('present')).strip()),
            self.soft_tissue_findings,
        ]))

        # Dental
        findings = self.tooth_finding_ids.sorted(lambda f: (f.tooth_number or '', f.id))
        teeth = ', '.join(
            f"{f.tooth_number} {lbl_cond}{f' ({f.surfaces})' if f.surfaces else ''}"
            for f in findings
            for lbl_cond in [dict(f._fields['condition']._description_selection(self.env)).get(f.condition, f.condition)]
        )
        lines.append(self._summary_section(_("Dental"), [
            lbl('dentition') and _("%s dentition", lbl('dentition')),
            lbl('molar_relation') and _("Molar %s", lbl('molar_relation')),
            self.overjet and _("Overjet %s mm", f"{self.overjet:g}"),
            self.overbite and _("Overbite %s mm", f"{self.overbite:g}"),
            self.crossbite not in (False, 'none') and _("%s crossbite", lbl('crossbite')),
            self.open_bite and _("Open bite"),
            self.crowding not in (False, 'none') and _("%s crowding", lbl('crowding')),
            self.spacing and _("Spacing"),
            self.tooth_wear not in (False, 'none') and _("Wear: %s", lbl('tooth_wear').lower()),
            self.occlusion,
            self.tooth_condition_summary,
            teeth and _("Teeth: %s", teeth),
        ]))

        # Periodontal
        status = lbl('perio_status')
        if self.perio_status == 'periodontitis':
            status = ' '.join(filter(None, [status, lbl('perio_stage'), lbl('perio_grade'), lbl('perio_extent') and f"({lbl('perio_extent').lower()})"]))
        bpe = '/'.join({'star': '*'}.get(self[f], self[f] or '-') for f in BPE_SEXTANTS) if any(self[f] for f in BPE_SEXTANTS) else ''
        charted = self.perio_chart_ids
        deepest = max(charted, key=lambda l: l.max_depth, default=False)
        tooth_notes = ', '.join(
            f"{l.tooth_number} mobility {l.mobility}" for l in charted if l.mobility and l.mobility != '0'
        )
        lines.append(self._summary_section(_("Periodontal"), [
            status,
            lbl('perio_gingival_color') and _("Gingiva %s", lbl('perio_gingival_color').lower()),
            lbl('perio_gingival_consistency') and lbl('perio_gingival_consistency').lower(),
            lbl('perio_gingival_contour') and lbl('perio_gingival_contour').lower(),
            lbl('perio_bleeding') and _("BOP %s", lbl('perio_bleeding').lower())
            + (f" ({self.perio_bop_percent:g}%)" if self.perio_bop_percent else ''),
            self.perio_plaque_percent and _("Plaque score %s%%", f"{self.perio_plaque_percent:g}"),
            self.perio_recession not in (False, 'none') and _("%s recession", lbl('perio_recession')),
            self.perio_suppuration and _("Suppuration"),
            bpe and _("BPE %s", bpe),
            deepest and deepest.max_depth and _("Deepest pocket %(depth)s mm at %(tooth)s", depth=deepest.max_depth, tooth=deepest.tooth_number),
            tooth_notes,
            self.gum_condition,
            self.perio_notes,
        ]))

        # Findings & investigations
        lines.append(self._summary_section(_("Findings"), [
            self.clinical_findings,
            self.radiographs_taken and _("Radiographs: %s", self.radiographs_taken),
            self.radiographic_findings,
            self.investigation_notes,
            self.additional_notes,
        ]))

        # Diagnosis
        coded = ', '.join(
            ' '.join(filter(None, [d.diagnosis_id.code, d.diagnosis_id.name]))
            + (f" ({d.tooth_reference})" if d.tooth_reference else '')
            + (f" [{dict(d._fields['status']._description_selection(self.env)).get(d.status)}]" if d.status and d.status != 'confirmed' else '')
            for d in self.diagnosis_ids if d.diagnosis_id
        )
        lines.append(self._summary_section(_("Diagnosis"), [
            coded,
            self.provisional_diagnosis and _("Provisional: %s", self.provisional_diagnosis.strip()),
            self.differential_diagnosis and _("Differential: %s", self.differential_diagnosis.strip()),
        ]))

        # Assessment
        lines.append(self._summary_section(_("Assessment"), [
            self.clinical_impression,
            lbl('caries_risk') and _("Caries risk %s", lbl('caries_risk').lower()),
            lbl('perio_risk') and _("Periodontal risk %s", lbl('perio_risk').lower()),
            lbl('oral_cancer_risk') and _("Oral cancer risk %s", lbl('oral_cancer_risk').lower()),
            lbl('prognosis') and _("Prognosis %s", lbl('prognosis').lower()),
            lbl('treatment_urgency') and _("Urgency: %s", lbl('treatment_urgency').lower()),
            self.recommended_treatment and _("Recommended: %s", self.recommended_treatment.strip()),
            self.referral_required and _("Refer to %s", self.referral_to or _('specialist'))
            + (f" ({self.referral_reason.strip()})" if self.referral_reason else ''),
            lbl('recall_interval') and _("Recall in %s", lbl('recall_interval').lower()),
        ]))
        return lines

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    @api.onchange('case_id')
    def _onchange_case_id(self):
        if self.case_id:
            if not self.patient_id and self.case_id.patient_id:
                self.patient_id = self.case_id.patient_id
            if not self.doctor_id and self.case_id.doctor_id:
                self.doctor_id = self.case_id.doctor_id
            if not self.chief_complaint and self.case_id.chief_complaint:
                self.chief_complaint = self.case_id.chief_complaint

    @api.onchange('referral_required')
    def _onchange_referral_required(self):
        if not self.referral_required:
            self.referral_to = False
            self.referral_reason = False

    @api.constrains('overjet', 'overbite', 'eo_mouth_opening', 'perio_bop_percent', 'perio_plaque_percent')
    def _check_measurements(self):
        for rec in self:
            if rec.eo_mouth_opening < 0 or rec.eo_mouth_opening > 90:
                raise ValidationError(_("Mouth opening must be between 0 and 90 mm."))
            if abs(rec.overjet) > 25 or abs(rec.overbite) > 25:
                raise ValidationError(_("Overjet and overbite must be within ±25 mm."))
            for value in (rec.perio_bop_percent, rec.perio_plaque_percent):
                if value < 0 or value > 100:
                    raise ValidationError(_("BOP and plaque scores are percentages between 0 and 100."))

    def _mark_done(self):
        to_close = self.filtered(lambda e: e.state != 'done')
        to_close.write({'state': 'done', 'completed_by_id': self.env.user.id, 'completed_date': fields.Datetime.now()})
        return to_close

    def action_complete_examination(self):
        for rec in self:
            if not (rec.chief_complaint or '').strip():
                raise ValidationError(_("Record the chief complaint before completing examination %s.", rec.name))
        done = self._mark_done()
        for rec in done:
            rec.message_post(body=_("Examination completed and signed off by %s.", self.env.user.name))
        return True

    def action_reopen_examination(self):
        for rec in self.filtered(lambda e: e.state == 'done'):
            if rec.case_id.state in ('completed', 'cancelled'):
                raise ValidationError(_("Case %s is closed; reopen the case before changing its examination.", rec.case_id.name))
            rec.write({'state': 'draft', 'completed_by_id': False, 'completed_date': False})
            rec.message_post(body=_("Examination reopened for changes by %s.", self.env.user.name))
        return True

    # Visit-specific values that a carried-forward examination never inherits
    _CARRY_FORWARD_SKIP = {
        'name', 'state', 'completed_by_id', 'completed_date', 'continued_from_id', 'examination_date',
        'case_id', 'appointment_id', 'patient_id', 'doctor_id', 'company_id',
        'chief_complaint', 'presenting_complaint', 'patient_informed',
        'height', 'weight', 'temperature', 'blood_pressure', 'pulse_rate', 'respiratory_rate', 'oxygen_saturation',
    }

    def _prepare_carry_forward_vals(self):
        """Clinical findings of this examination as values for a later visit's examination.

        Tooth findings and diagnoses are not copied: they belong to the patient's chart and
        stay visible there. The periodontal chart is copied so it can be re-probed.
        """
        self.ensure_one()
        vals = self.copy_data()[0]
        vals = {key: value for key, value in vals.items()
                if key not in self._CARRY_FORWARD_SKIP and self._fields[key].type not in ('one2many', 'many2many')}
        perio = []
        for line in self.perio_chart_ids:
            line_vals = line.copy_data()[0]
            line_vals.pop('examination_id', None)
            line_vals.pop('company_id', None)
            perio.append(Command.create(line_vals))
        if perio:
            vals['perio_chart_ids'] = perio
        return vals

    def action_open_examination_form(self):
        """Open this examination on its own page (from the case's list of previous examinations)."""
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.clinical.examination',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dental_core.view_dental_clinical_examination_form').id, 'form')],
            'context': {'dental_current_visit_id': self.appointment_id.id} if self.appointment_id else {},
            'target': 'current',
        }

    def action_continue_examination(self):
        """Continue this (earlier) examination in today's visit of the case the dentist is working in."""
        self.ensure_one()
        case = self.env['dental.case'].browse(self.env.context.get('dental_case_id')).exists() or self.case_id
        return case._continue_examination_from(self)

    def action_open_case(self):
        """Back to the consultation (case) this examination belongs to."""
        self.ensure_one()
        context = {'dental_current_visit_id': self.appointment_id.id} if self.appointment_id else {}
        return {
            'name': self.case_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.case',
            'res_id': self.case_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dental_core.view_dental_case_form').id, 'form')],
            'context': context,
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.clinical.examination') or _('New')
            if not vals.get('chief_complaint') and vals.get('case_id'):
                case = self.env['dental.case'].browse(vals['case_id'])
                if case.chief_complaint:
                    vals['chief_complaint'] = case.chief_complaint
        return super().create(vals_list)


class DentalExaminationPerioLine(models.Model):
    """One tooth of the periodontal chart recorded in an examination (six-point probing)."""
    _name = 'dental.examination.perio.line'
    _description = 'Periodontal Chart Entry'
    _inherit = ['dental.company.mixin']
    _order = 'examination_id, tooth_number'

    examination_id = fields.Many2one('dental.clinical.examination', string='Examination', required=True, index=True,
                                     ondelete='cascade', check_company=True)
    patient_id = fields.Many2one(related='examination_id.patient_id', store=True, index=True, string='Patient')
    tooth_number = fields.Char(string='Tooth (FDI)', required=True)
    tooth_name = fields.Char(string='Tooth Name', compute='_compute_tooth_name')
    pd_db = fields.Integer(string='DB', help='Probing depth disto-buccal (mm)')
    pd_b = fields.Integer(string='B', help='Probing depth buccal (mm)')
    pd_mb = fields.Integer(string='MB', help='Probing depth mesio-buccal (mm)')
    pd_dl = fields.Integer(string='DL', help='Probing depth disto-palatal/lingual (mm)')
    pd_l = fields.Integer(string='L', help='Probing depth palatal/lingual (mm)')
    pd_ml = fields.Integer(string='ML', help='Probing depth mesio-palatal/lingual (mm)')
    recession = fields.Integer(string='Recession (mm)')
    max_depth = fields.Integer(string='Deepest (mm)', compute='_compute_depths', store=True)
    clinical_attachment_loss = fields.Integer(string='CAL (mm)', compute='_compute_depths', store=True,
                                              help='Deepest probing depth plus recession.')
    mobility = fields.Selection([('0', '0'), ('1', 'I'), ('2', 'II'), ('3', 'III')], string='Mobility')
    furcation = fields.Selection([('0', 'None'), ('1', 'I'), ('2', 'II'), ('3', 'III')], string='Furcation')
    bleeding = fields.Boolean(string='BOP')
    plaque = fields.Boolean(string='Plaque')
    suppuration = fields.Boolean(string='Pus')
    notes = fields.Char(string='Notes')

    _tooth_uniq = models.Constraint('unique(examination_id, tooth_number)',
                                    'Each tooth can be charted only once per examination.')

    @api.depends('examination_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('examination_id')

    @api.depends('tooth_number')
    def _compute_tooth_name(self):
        for line in self:
            info = TOOTH_NAMES.get((line.tooth_number or '').strip())
            line.tooth_name = info[0] if info else False

    @api.depends('pd_db', 'pd_b', 'pd_mb', 'pd_dl', 'pd_l', 'pd_ml', 'recession')
    def _compute_depths(self):
        for line in self:
            line.max_depth = max(line.pd_db, line.pd_b, line.pd_mb, line.pd_dl, line.pd_l, line.pd_ml)
            line.clinical_attachment_loss = line.max_depth + (line.recession or 0) if line.max_depth else 0

    @api.constrains('tooth_number', 'pd_db', 'pd_b', 'pd_mb', 'pd_dl', 'pd_l', 'pd_ml', 'recession')
    def _check_values(self):
        for line in self:
            if (line.tooth_number or '').strip() not in TOOTH_NAMES:
                raise ValidationError(_("Invalid tooth number %s. Use FDI notation, e.g. 36.", line.tooth_number))
            depths = (line.pd_db, line.pd_b, line.pd_mb, line.pd_dl, line.pd_l, line.pd_ml, line.recession)
            if any(d < 0 or d > 20 for d in depths):
                raise ValidationError(_("Probing depths and recession must be between 0 and 20 mm (tooth %s).", line.tooth_number))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('tooth_number'):
                vals['tooth_number'] = str(vals['tooth_number']).strip()
        return super().create(vals_list)
