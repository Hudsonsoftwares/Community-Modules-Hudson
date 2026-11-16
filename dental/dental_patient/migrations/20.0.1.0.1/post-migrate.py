def migrate(cr, version):
    # Patients are shared by all branches: release any patient tied to a single branch
    cr.execute("UPDATE res_partner SET company_id = NULL WHERE is_dental_patient AND company_id IS NOT NULL")
