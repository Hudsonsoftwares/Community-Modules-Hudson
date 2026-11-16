"""Move the pre-Odoo 20 check_in_photo / check_out_photo pictures to the
core ``in_image`` field and the new ``out_image`` field."""


def migrate(cr, version):
    for old, new in (('check_in_photo', 'in_image'), ('check_out_photo', 'out_image')):
        cr.execute("""
            UPDATE ir_attachment a
               SET res_field = %(new)s, name = %(new)s
             WHERE a.res_model = 'hr.attendance'
               AND a.res_field = %(old)s
               AND NOT EXISTS (
                    SELECT 1 FROM ir_attachment b
                     WHERE b.res_model = 'hr.attendance'
                       AND b.res_field = %(new)s
                       AND b.res_id = a.res_id)
        """, {'old': old, 'new': new})
