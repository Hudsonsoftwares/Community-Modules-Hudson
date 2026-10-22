"""
Fix the crud operation domains for DMS User and Base User rules.
Since crud rules cover both read AND write operations, we need to ensure
write/delete operations are also properly checked.

The solution: split the 'crud' domain into separate rules or use the most
permissive check (read) for the group-level rule - since the per-operation
'Apply computed write/unlink/create' rules will further restrict.

Actually in Odoo 20, the domain_force for a 'crud' rule is applied to ALL
operations covered. Since the 'Apply computed write permissions' rule also
runs for write ops, the AND logic between rules means we need BOTH to pass.

So setting the crud domain to check read permission is WRONG for write ops -
it would allow write on records the user can READ but not WRITE.

The correct approach: change the crud rules to ONLY cover read (r) and let
the separate computed permission rules handle write/create/unlink.

Or alternatively: use separate domains per operation type.
Let's check how Odoo applies these - if rules with the same operation all
need to pass (AND), then we just need the read domain on the read-only rule.
"""
import psycopg2

conn = psycopg2.connect(dbname='Testing20', user='odoo', password='odoopwd', host='localhost')
cur = conn.cursor()

# Change the 'crud' DMS user rules to 'r' only
# The write/create/unlink are already covered by the computed permission rules
# which use permission_write, permission_create, permission_unlink

# For dms_directory_user: change from crud to r (read only)
# Write/create/unlink will be handled by rule_directory_computed_*
updates = [
    # (external_id, new_operation)
    ('dms.access_dms_directory_user', 'r'),
    ('dms.access_dms_file_user', 'r'),
    ('dms.access_dms_directory_base_user', 'r'),   # was already r
    ('dms.access_dms_file_base_user', 'r'),         # was already r
]

for ext_id, new_op in updates:
    module, name = ext_id.split('.', 1)
    cur.execute(
        "SELECT res_id, operation FROM ir_model_data d "
        "JOIN ir_access a ON d.res_id = a.id "
        "WHERE d.module = %s AND d.name = %s AND d.model = 'ir.access'",
        (module, name)
    )
    row = cur.fetchone()
    if row:
        res_id, old_op = row
        if old_op != new_op:
            cur.execute("UPDATE ir_access SET operation = %s WHERE id = %s", (new_op, res_id))
            print(f"Changed [{ext_id}] operation: {old_op} -> {new_op}")
        else:
            print(f"[{ext_id}] already has operation={new_op}, no change")
    else:
        print(f"NOT FOUND: {ext_id}")

conn.commit()
print("\nDone.")
conn.close()
