def migrate(cr, version):
    """Braces are adjusted monthly: give the seeded Braces treatment its visit interval
    (the seed data is noupdate, so existing databases do not get it otherwise)."""
    if not version:
        return
    cr.execute("""
        UPDATE product_template pt
           SET visit_interval = '1 Month'
          FROM ir_model_data imd
         WHERE imd.module = 'dental_catalog' AND imd.name = 'treatment_braces'
           AND imd.model = 'product.template' AND imd.res_id = pt.id
           AND (pt.visit_interval IS NULL OR pt.visit_interval = '')
    """)
