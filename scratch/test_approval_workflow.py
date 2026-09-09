import sys
sys.path.insert(0, r"C:\Program Files\Odoo 19.0.20260518\server")
import odoo
from odoo import api, SUPERUSER_ID
from odoo.tools import config
from odoo.modules.registry import Registry
from odoo.exceptions import UserError

def run_test():
    config.parse_config(['-c', r"C:\Program Files\Odoo 19.0.20260518\server\odoo.conf", '-d', 'Testing'])
    registry = Registry('Testing')
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        print("=== RUNNING APPROVAL WORKFLOW PERMISSION & VISIBILITY TESTS ===")

        # Get or create test users
        admin = env.ref('base.user_admin')
        users = env['res.users'].search([('id', '!=', admin.id), ('share', '=', False)], limit=2)
        if len(users) >= 2:
            demo_user = users[0]
            user_b = users[1]
        elif len(users) == 1:
            demo_user = users[0]
            user_b = env['res.users'].create({
                'name': 'Approver Bob',
                'login': 'test_approver_b',
                'email': 'bob@example.com',
            })
        else:
            demo_user = env['res.users'].create({
                'name': 'Demo Approver',
                'login': 'demo_approver',
                'email': 'demo@example.com',
            })
            user_b = env['res.users'].create({
                'name': 'Approver Bob',
                'login': 'test_approver_b',
                'email': 'bob@example.com',
            })

        storage = env['dms.storage'].search([], limit=1)
        root_dir = env['dms.directory'].search([('is_root_directory', '=', True)], limit=1)

        # TEST 1: Visibility for assigned approver
        print("\n--- TEST 1: Approver Visibility in Document Module ---")
        # Create private directory without general permissions
        private_dir = env['dms.directory'].create({
            'name': 'Private_Executive_Folder',
            'is_root_directory': True,
            'storage_id': storage.id,
        })
        private_file = env['dms.file'].create({
            'name': 'Executive_Proposal.pdf',
            'directory_id': private_dir.id,
            'document_owner_id': admin.id,
            'approval_ids': [
                (0, 0, {'sequence': 10, 'approver_id': demo_user.id}),
            ]
        })
        private_file.action_request_approval()

        # Check visibility as demo_user
        demo_files = env['dms.file'].with_user(demo_user).search([('id', '=', private_file.id)])
        assert len(demo_files) == 1, f"Expected demo_user to see assigned file, but found {len(demo_files)}"
        
        demo_dirs = env['dms.directory'].with_user(demo_user).search([('id', '=', private_dir.id)])
        assert len(demo_dirs) == 1, f"Expected demo_user to see parent directory of assigned file, but found {len(demo_dirs)}"
        
        # Check permissions on file
        assert demo_files.permission_view == True, "Approver should have view permission on assigned file"
        assert demo_files.permission_download == True, "Approver should have download permission on assigned file"
        print("[OK] Approver can see both the document and parent directory, with view & download permissions.")

        # TEST 2: Only assigned approver can approve
        print("\n--- TEST 2: Only Assigned Approver Can Approve / Reject ---")
        # Admin tries to approve demo_user's step
        admin_blocked = False
        try:
            private_file.with_user(admin).action_approve_step()
        except UserError as e:
            admin_blocked = True
            print(f"[OK] Admin correctly blocked from approving demo_user's step: {e}")
        assert admin_blocked, "Admin must be blocked from approving non-assigned step"

        # User B tries to approve demo_user's step
        user_b_blocked = False
        try:
            private_file.with_user(user_b).action_approve_step()
        except UserError as e:
            user_b_blocked = True
            print(f"[OK] User B correctly blocked from approving demo_user's step: {e}")
        assert user_b_blocked, "User B must be blocked from approving demo_user's step"

        # Assigned demo_user approves
        private_file.with_user(demo_user).action_approve_step()
        assert private_file.approval_state == 'approved', f"Expected approved, got {private_file.approval_state}"
        assert private_file.directory_id == private_dir, "Document retained in original directory"
        print("[OK] Assigned approver approved successfully!")

        print("\n=========================================")
        print("ALL APPROVER VISIBILITY & SECURITY TESTS PASSED 100%!")
        print("=========================================")
        
        cr.rollback()

if __name__ == '__main__':
    run_test()
