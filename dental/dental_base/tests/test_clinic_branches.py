from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dental_clinic_branches')
class TestDentalClinicBranches(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.main_clinic = cls.env.company
        cls.main_clinic.is_dental_clinic = True

    def test_menu_action_points_to_clinic_branches_not_multi_company(self):
        """Configuration menu 'Clinic Branches' must point to dedicated branch action, not multi-company action."""
        menu = self.env.ref('dental_base.menu_dental_branches')
        action = self.env.ref('dental_base.action_dental_clinic_branches')
        multi_company_action = self.env.ref('base.action_res_company_form')

        self.assertEqual(menu.action, action, "Menu must open dedicated clinic branches action")
        self.assertNotEqual(menu.action, multi_company_action, "Menu must NOT open root multi-company action")

    def test_branch_action_restricts_to_branches(self):
        """The action must filter by parent_id != False to exclude root companies."""
        action = self.env.ref('dental_base.action_dental_clinic_branches')
        self.assertEqual(action.res_model, 'res.company')
        self.assertIn("('parent_id', '!=', False)", action.domain)
        self.assertTrue(eval(action.context).get('dental_branch_creation'))

    def test_branch_creation_assigns_parent_clinic(self):
        """Creating a branch via the clinic branch action sets parent_id and is_dental_clinic."""
        BranchModel = self.env['res.company'].with_context(
            dental_branch_creation=True,
            default_is_dental_clinic=True,
        )
        # Verify default_get
        defaults = BranchModel.default_get(['name', 'parent_id', 'is_dental_clinic'])
        expected_parent = self.main_clinic.root_id or self.main_clinic
        self.assertEqual(defaults.get('parent_id'), expected_parent.id)
        self.assertTrue(defaults.get('is_dental_clinic'))

        # Create branch without explicit parent_id: model enforces branch of main clinic
        branch = BranchModel.create({'name': 'Downtown Branch'})
        self.assertEqual(branch.parent_id, expected_parent, "Branch must belong to the parent clinic")
        self.assertTrue(branch.is_dental_clinic)
        self.assertIn(branch, self.main_clinic.child_ids)

    def test_dental_branch_count_and_action(self):
        """Clinic configuration shows branch count and opens child branches."""
        initial_count = self.main_clinic.dental_branch_count
        branch = self.env['res.company'].with_context(dental_branch_creation=True).create({
            'name': 'Uptown Branch',
            'parent_id': self.main_clinic.id,
        })
        self.assertEqual(self.main_clinic.dental_branch_count, initial_count + 1)

        action = self.main_clinic.action_view_dental_branches()
        self.assertEqual(action['res_model'], 'res.company')
        self.assertEqual(action['domain'], [('parent_id', '=', self.main_clinic.id)])
        self.assertEqual(action['context']['default_parent_id'], self.main_clinic.id)
        self.assertTrue(action['context']['dental_branch_creation'])

