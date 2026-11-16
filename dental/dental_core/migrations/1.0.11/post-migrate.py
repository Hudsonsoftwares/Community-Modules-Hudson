"""Treatment already approved, started or performed was accepted by the patient: record it.

Everything else stays 'Awaiting Decision'; nothing is declined automatically.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE dental_treatment_plan_line l
           SET acceptance = 'accepted'
          FROM dental_treatment_plan p
         WHERE p.id = l.plan_id
           AND l.acceptance = 'pending'
           AND (p.state IN ('approved', 'in_progress', 'completed') OR l.state IN ('in_progress', 'completed'))
    """)
