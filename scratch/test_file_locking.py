import sys
sys.path.append(r"C:\Program Files\Odoo 19.0.20260518\server")
import odoo
from odoo import api, SUPERUSER_ID
from odoo.exceptions import UserError, AccessError

def run_test():
    config_file = r"C:\Program Files\Odoo 19.0.20260518\server\odoo.conf"
    odoo.tools.config.parse_config(['-c', config_file, '-d', 'Testing'])
    registry = odoo.modules.registry.Registry('Testing')

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        # Find or create a test user
        user_admin = env.ref('base.user_admin')
        user_demo = env.ref('base.user_demo', raise_if_not_found=False) or user_admin
        
        storage = env['dms.storage'].search([], limit=1)
        directory = env['dms.directory'].create({
            'name': 'Lock Test Folder',
            'is_root_directory': True,
            'storage_id': storage.id,
        })
        dest_directory = env['dms.directory'].create({
            'name': 'Lock Dest Folder',
            'is_root_directory': True,
            'storage_id': storage.id,
        })

        # 1. Create a test file as user_admin
        env_admin = api.Environment(cr, user_admin.id, {})
        test_file = env_admin['dms.file'].create({
            'name': 'Lock_Test_Doc.txt',
            'directory_id': directory.id,
            'content': b'SGVsbG8gV29ybGQ=', # "Hello World"
        })
        print(f"Created file: {test_file.name} (ID: {test_file.id})")
        
        # 2. Lock the file as user_admin
        test_file.lock()
        print(f"File locked by: {test_file.locked_by.name}, is_locked={test_file.is_locked}, is_lock_editor={test_file.is_lock_editor}")
        assert test_file.is_locked == True
        
        # 3. Try to send to trash while locked -> should fail
        try:
            test_file.action_send_to_trash()
            print("ERROR: action_send_to_trash succeeded on locked file!")
        except UserError as e:
            print(f"SUCCESS: action_send_to_trash blocked: {e}")

        # 4. Try to move while locked -> should fail
        try:
            test_file.action_open_move_wizard()
            print("ERROR: action_open_move_wizard succeeded on locked file!")
        except UserError as e:
            print(f"SUCCESS: action_open_move_wizard blocked: {e}")

        try:
            test_file.write({'directory_id': dest_directory.id})
            print("ERROR: moving directory_id via write succeeded on locked file!")
        except UserError as e:
            print(f"SUCCESS: moving directory_id via write blocked: {e}")

        # 5. Try to delete while locked -> should fail
        try:
            test_file.unlink()
            print("ERROR: unlink succeeded on locked file!")
        except UserError as e:
            print(f"SUCCESS: unlink blocked: {e}")

        # 6. Try to delete revision while locked -> should fail
        if test_file.revision_ids:
            rev = test_file.revision_ids[0]
            try:
                rev.unlink()
                print("ERROR: rev.unlink succeeded on locked file!")
            except UserError as e:
                print(f"SUCCESS: rev.unlink blocked: {e}")

        # 7. Try to edit by another user -> should fail
        if user_admin.id != user_demo.id:
            # Let's create another regular user to test non-manager write
            user_other = env['res.users'].search([('id', 'not in', [user_demo.id, user_admin.id])], limit=1)
            if not user_other:
                user_other = env['res.users'].create({
                    'name': 'Test User Other',
                    'login': 'test_other_user',
                    'groups_id': [(6, 0, [env.ref('base.group_user').id, env.ref('dms.group_dms_user').id])]
                })
            env_other = api.Environment(cr, user_other.id, {})
            try:
                env_other['dms.file'].browse(test_file.id).write({'name': 'Hacked_Name.txt'})
                print("ERROR: non-locker write succeeded on locked file!")
            except (UserError, AccessError) as e:
                print(f"SUCCESS: non-locker write blocked: {e}")

        # 8. Unlock the file as user_demo
        test_file.unlock()
        print(f"File unlocked, is_locked={test_file.is_locked}")
        assert test_file.is_locked == False

        # 9. Clean up test file
        test_file.action_send_to_trash()
        print("Cleaned up test file.")
        
        cr.rollback()
        print("TEST PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_test()
