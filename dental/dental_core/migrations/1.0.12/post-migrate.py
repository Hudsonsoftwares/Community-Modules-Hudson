"""Structured clinical examination workflow.

- Examinations of finished visits or closed cases are signed off (status Completed); the ones of
  visits still in progress stay In Progress.
- The diagnosis master gets the common dental diagnoses it does not have yet.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""
        UPDATE dental_clinical_examination x
           SET state = 'done',
               completed_date = coalesce((SELECT v.date_end FROM dental_appointment v WHERE v.id = x.appointment_id),
                                         c.completion_time, x.write_date),
               completed_by_id = x.write_uid
          FROM dental_case c
         WHERE c.id = x.case_id
           AND x.state = 'draft'
           AND (c.state IN ('completed', 'cancelled')
                OR EXISTS (SELECT 1 FROM dental_appointment v
                            WHERE v.id = x.appointment_id AND v.state IN ('completed', 'cancelled', 'no_show')))
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['dental.diagnosis']._load_standard_diagnoses()
