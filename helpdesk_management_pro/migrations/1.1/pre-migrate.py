def migrate(cr, version):
    cr.execute("UPDATE helpdesk_management_team SET article_id = NULL")
    
    # Try to find and drop the constraint
    cr.execute("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'helpdesk_management_team'::regclass
        AND contype = 'f'
    """)
    constraints = cr.fetchall()
    for (conname,) in constraints:
        if 'article_id' in conname:
            cr.execute(f"ALTER TABLE helpdesk_management_team DROP CONSTRAINT {conname}")
