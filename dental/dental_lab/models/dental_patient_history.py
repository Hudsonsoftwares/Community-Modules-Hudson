from odoo import fields, models


class DentalPatientHistory(models.Model):
    _inherit = 'dental.patient.history'

    # The timeline is an SQL view: nothing to clean up when the type disappears
    record_type = fields.Selection(selection_add=[('lab', 'Lab Order')],
                                   ondelete={'lab': lambda records: None})

    def _history_queries(self):
        return super()._history_queries() + [
            """SELECT o.id * {f} + 10, o.patient_id, o.order_date,
                      CASE WHEN o.create_date::date = o.order_date THEN o.create_date ELSE o.order_date::timestamp END,
                      'lab', o.name, c.name, o.tooth_summary,
                      o.lab_type, o.state, e.name, co.name, o.company_id
                 FROM dental_lab_order o
                 LEFT JOIN dental_case c ON c.id = o.case_id
                 LEFT JOIN hr_employee e ON e.id = o.dentist_id
                 LEFT JOIN res_company co ON co.id = o.company_id""",
        ]
