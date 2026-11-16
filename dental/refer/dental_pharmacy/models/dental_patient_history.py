from odoo import fields, models


class DentalPatientHistory(models.Model):
    _inherit = 'dental.patient.history'

    # The timeline is an SQL view: nothing to clean up when the type disappears
    record_type = fields.Selection(selection_add=[('prescription', 'Prescription')],
                                   ondelete={'prescription': lambda records: None})

    def _history_queries(self):
        return super()._history_queries() + [
            """SELECT r.id * {f} + 9, r.patient_id, r.prescription_date,
                      CASE WHEN r.create_date::date = r.prescription_date THEN r.create_date ELSE r.prescription_date::timestamp END,
                      'prescription', r.name, c.name, NULL,
                      concat_ws(E'\n', r.diagnosis,
                                (SELECT string_agg(t.name->>'en_US', ', ' ORDER BY l.id)
                                   FROM dental_prescription_line l
                                   JOIN product_product pp ON pp.id = l.medicine_id
                                   JOIN product_template t ON t.id = pp.product_tmpl_id
                                  WHERE l.prescription_id = r.id)),
                      r.state, e.name, co.name, r.company_id
                 FROM dental_prescription r
                 LEFT JOIN dental_case c ON c.id = r.case_id
                 LEFT JOIN hr_employee e ON e.id = r.dentist_id
                 LEFT JOIN res_company co ON co.id = r.company_id""",
        ]
