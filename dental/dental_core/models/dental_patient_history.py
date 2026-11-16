from odoo import fields, models, tools

HISTORY_TYPES = [
    ('visit', 'Visit'),
    ('case', 'Case / Clinical Notes'),
    ('consultation', 'Examination'),
    ('diagnosis', 'Diagnosis'),
    ('finding', 'Odontogram Finding'),
    ('plan', 'Planned Treatment'),
    ('session', 'Treatment Session'),
    ('document', 'Record / X-Ray'),
]

# Row ids are "source id * HISTORY_ID_FACTOR + type number" so they stay stable between reads.
# Type numbers 1-7 are used here, 8 for visits; add-ons (pharmacy, lab) use 9 and up.
HISTORY_ID_FACTOR = 16


class DentalPatientHistory(models.Model):
    """Read-only clinical timeline of a patient across all branches.

    Patients are shared by all branches, their clinical records are not (dental_base/SECURITY.md): a doctor
    of branch B cannot open a case of branch A. This view gives branch B what it needs to treat a returning
    patient (what was diagnosed and done, where, when and by whom) without granting access to the
    branch-owned records themselves, so the isolation of cases, sessions and work lists stays intact.
    Doctor and branch are plain names so no access to other branches' employees or companies is needed.

    Add-ons add their own records to the timeline by extending ``_history_queries`` (and ``record_type``).
    """
    _name = 'dental.patient.history'
    _description = 'Patient Clinical Timeline (All Branches)'
    _auto = False
    _order = 'event_time desc, id desc'
    _rec_name = 'reference'

    patient_id = fields.Many2one('res.partner', string='Patient', readonly=True, index=True)
    date = fields.Date(string='Date', readonly=True)
    event_time = fields.Datetime(string='Recorded On', readonly=True,
                                 help='Exact time of the event, used to order the timeline chronologically.')
    record_type = fields.Selection(HISTORY_TYPES, string='Type', readonly=True)
    reference = fields.Char(string='Reference', readonly=True)
    case_reference = fields.Char(string='Case', readonly=True)
    tooth = fields.Char(string='Tooth', readonly=True)
    description = fields.Text(string='Details', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    doctor_name = fields.Char(string='Doctor', readonly=True)
    branch_name = fields.Char(string='Branch', readonly=True)
    other_branch = fields.Boolean(string='Other Branch', compute='_compute_other_branch')
    branch_id = fields.Many2one('res.company', string='Branch Record', readonly=True)

    def _compute_other_branch(self):
        current = self.env.companies
        for line in self:
            line.other_branch = line.branch_id not in current

    def _history_queries(self):
        """SELECT statements feeding the timeline, one per source.

        Each returns, in this order: id, patient_id, date, event_time, record_type, reference,
        case_reference, tooth, description, status, doctor_name, branch_name, branch_id.
        ``{f}`` is replaced by HISTORY_ID_FACTOR.
        """
        return [
            # Visits (appointments that were not cancelled)
            """SELECT a.id * {f} + 8, a.patient_id, a.date_start::date, a.date_start, 'visit',
                      a.name, c.name, NULL,
                      a.reason, a.state,
                      e.name, co.name, a.company_id
                 FROM dental_appointment a
                 LEFT JOIN dental_case c ON c.id = a.case_id
                 LEFT JOIN hr_employee e ON e.id = a.doctor_id
                 LEFT JOIN res_company co ON co.id = a.company_id
                WHERE a.state != 'cancelled'""",
            # Cases with their chief complaint and clinical notes
            """SELECT c.id * {f} + 1, c.patient_id, c.case_date, c.create_date, 'case',
                      c.name, c.name, NULL,
                      concat_ws(E'\\n', c.chief_complaint, c.clinical_notes), c.state,
                      e.name, co.name, c.company_id
                 FROM dental_case c
                 LEFT JOIN hr_employee e ON e.id = c.doctor_id
                 LEFT JOIN res_company co ON co.id = c.company_id""",
            """SELECT x.id * {f} + 2, x.patient_id, x.examination_date::date, x.examination_date, 'consultation',
                      x.name, c.name,
                      (SELECT string_agg(DISTINCT t.tooth, ', ')
                         FROM (SELECT tf.tooth_number AS tooth FROM dental_tooth_finding tf
                                WHERE tf.examination_id = x.id AND tf.active
                               UNION
                               SELECT pl.tooth_number FROM dental_examination_perio_line pl
                                WHERE pl.examination_id = x.id) t),
                      coalesce(x.examination_summary,
                               concat_ws(E'\\n', x.chief_complaint, x.presenting_complaint, x.clinical_findings, x.additional_notes)),
                      CASE x.state WHEN 'done' THEN 'completed' ELSE 'in_progress' END,
                      e.name, co.name, x.company_id
                 FROM dental_clinical_examination x
                 LEFT JOIN dental_case c ON c.id = x.case_id
                 LEFT JOIN hr_employee e ON e.id = x.doctor_id
                 LEFT JOIN res_company co ON co.id = x.company_id""",
            """SELECT d.id * {f} + 3, d.patient_id, d.date, d.create_date, 'diagnosis',
                      concat_ws(' ', m.code, m.name), c.name, d.tooth_reference,
                      d.notes, d.status,
                      e.name, co.name, d.company_id
                 FROM dental_patient_diagnosis d
                 JOIN dental_diagnosis m ON m.id = d.diagnosis_id
                 LEFT JOIN dental_case c ON c.id = d.case_id
                 LEFT JOIN hr_employee e ON e.id = d.doctor_id
                 LEFT JOIN res_company co ON co.id = d.company_id""",
            """SELECT f.id * {f} + 4, f.patient_id, f.finding_date::date, f.finding_date, 'finding',
                      f.name, c.name, f.tooth_number,
                      concat_ws(E'\\n', concat_ws(' ', f.condition, f.surfaces), f.treatment_indicated, f.notes), f.state,
                      e.name, co.name, f.company_id
                 FROM dental_tooth_finding f
                 LEFT JOIN dental_case c ON c.id = f.case_id
                 LEFT JOIN hr_employee e ON e.id = f.doctor_id
                 LEFT JOIN res_company co ON co.id = f.company_id""",
            """SELECT l.id * {f} + 5, p.patient_id, p.plan_date, l.create_date, 'plan',
                      p.name, c.name, l.tooth_reference,
                      concat_ws(E'\\n', t.name->>'en_US', l.description), l.state,
                      e.name, co.name, l.company_id
                 FROM dental_treatment_plan_line l
                 JOIN dental_treatment_plan p ON p.id = l.plan_id
                 LEFT JOIN product_template t ON t.id = l.treatment_id
                 LEFT JOIN dental_case c ON c.id = p.case_id
                 LEFT JOIN hr_employee e ON e.id = p.doctor_id
                 LEFT JOIN res_company co ON co.id = l.company_id""",
            """SELECT s.id * {f} + 6, s.patient_id, s.session_date::date, s.session_date, 'session',
                      s.name, c.name, s.tooth_reference,
                      concat_ws(E'\\n', t.name->>'en_US', s.procedure_notes, s.clinical_notes), s.state,
                      e.name, co.name, s.company_id
                 FROM dental_treatment_session s
                 LEFT JOIN dental_treatment_plan_line l ON l.id = s.plan_line_id
                 LEFT JOIN product_template t ON t.id = l.treatment_id
                 LEFT JOIN dental_case c ON c.id = s.case_id
                 LEFT JOIN hr_employee e ON e.id = s.doctor_id
                 LEFT JOIN res_company co ON co.id = s.company_id""",
            """SELECT dd.id * {f} + 7, dd.patient_id, dd.document_date, coalesce(dd.document_date::timestamp, dd.create_date), 'document',
                      dd.name, NULL, NULL,
                      concat_ws(E'\\n', dd.document_type, dd.notes), NULL,
                      NULL, co.name, dd.company_id
                 FROM dental_patient_document dd
                 LEFT JOIN res_company co ON co.id = dd.company_id""",
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        columns = ('id, patient_id, date, event_time, record_type, reference, case_reference, tooth, '
                   'description, status, doctor_name, branch_name, branch_id')
        union = '\nUNION ALL\n'.join(q.format(f=HISTORY_ID_FACTOR) for q in self._history_queries())
        self.env.cr.execute(f"CREATE OR REPLACE VIEW {self._table} AS (SELECT {columns} FROM ({union}) AS h({columns}))")

