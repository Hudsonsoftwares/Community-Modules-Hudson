# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTaxProofDms(TransactionCase):
    """Proof files of a submitted tax declaration are copied into
    Employees / <employee> / Payroll / <tax year> / Tax Proofs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.hds_dms_store_tax_proofs = True
        cls.fy = cls.env['tds.financial.year'].search([('start_date', '=', '2026-04-01')], limit=1) or \
            cls.env['tds.financial.year'].create({
                'name': 'FY 2026-27 Proof Test', 'code': '2026-2027-PROOF-TEST', 'assessment_year': '2027-2028',
                'start_date': '2026-04-01', 'end_date': '2027-03-31'})
        cls.employee = cls._employee('Tax Proof Employee One', 'tax.proof.one@example.com')
        cls.other = cls._employee('Tax Proof Employee Two', 'tax.proof.two@example.com')

    @classmethod
    def _employee(cls, name, login):
        user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])]})
        return cls.env['hr.employee'].create({'name': name, 'user_id': user.id, 'company_id': cls.company.id})

    def _declaration(self, employee=None):
        employee = employee or self.employee
        return self.env['tds.employee.declaration'].create({
            'employee_id': employee.id, 'financial_year_id': self.fy.id, 'company_id': self.company.id})

    def _proof(self, decl, field, name, content=b'%PDF-1.4 proof'):
        attachment = self.env['ir.attachment'].create({
            'name': name, 'raw': content, 'res_model': decl._name, 'res_id': decl.id})
        decl.write({field: [(6, 0, attachment.ids)]})
        return attachment

    def _copies(self, decl, trashed=False):
        links = self.env['hds.in.tax.proof.document'].search([('declaration_id', '=', decl.id)])
        return links.mapped('dms_file_id').with_context(active_test=False).filtered(
            lambda dms_file: dms_file.is_trashed == trashed)

    def test_copied_on_proof_submission_in_the_tax_year_folder(self):
        decl = self._declaration()
        attachment = self._proof(decl, 'decl_80c_attachment_ids', 'LIC receipt.pdf')
        self.assertFalse(self._copies(decl), "Draft proofs are not copied")
        decl.write({'state': 'proof_submitted'})
        copy = self._copies(decl)
        self.assertEqual(len(copy), 1)
        self.assertEqual(copy.name, '80C - LIC receipt.pdf')
        self.assertEqual(copy.directory_id.name, 'Tax Proofs')
        self.assertEqual(copy.directory_id.parent_id.name, '2026-27')
        self.assertEqual(copy.directory_id.parent_id.parent_id.name, 'Payroll')
        self.assertEqual(copy.directory_id.parent_id.parent_id.parent_id, self.employee.dms_directory_id)
        self.assertEqual(bytes(copy.content), bytes(attachment.raw))
        self.assertNotEqual(copy.attachment_id, attachment, "A copy, not the declaration's own file")
        self.assertEqual(copy.create_uid.id, SUPERUSER_ID)
        # Saving again creates no duplicate
        decl.write({'state': 'proof_under_review'})
        decl.write({'decl_80c_attachment_ids': [(6, 0, attachment.ids)]})
        self.assertEqual(self._copies(decl), copy)

    def test_added_and_removed_proofs(self):
        decl = self._declaration()
        lic = self._proof(decl, 'decl_80c_attachment_ids', 'LIC receipt.pdf')
        decl.write({'state': 'proof_submitted'})
        # A proof added while under review is copied
        self._proof(decl, 'decl_hra_attachment_ids', 'Rent agreement.pdf')
        self._proof(decl, 'prev_employer_attachment_ids', 'Form 16.pdf')
        self.assertEqual(sorted(self._copies(decl).mapped('name')),
                         ['80C - LIC receipt.pdf', 'HRA - Rent agreement.pdf', 'Previous Employer - Form 16.pdf'])
        # A removed proof goes to the Trash (declaration keeps working)
        decl.write({'decl_80c_attachment_ids': [(5, 0, 0)]})
        self.assertEqual(self._copies(decl, trashed=True).mapped('name'), ['80C - LIC receipt.pdf'])
        self.assertEqual(len(self._copies(decl)), 2)

    def test_locked_when_verified_and_trashed_on_reset_to_draft(self):
        decl = self._declaration()
        self._proof(decl, 'decl_57iia_attachment_ids', 'Pension slip.pdf')
        decl.write({'state': 'proof_submitted'})
        decl.write({'state': 'proof_verified'})
        copy = self._copies(decl)
        self.assertEqual(copy.name, '57(iia) - Pension slip.pdf')
        self.assertTrue(copy.is_locked)
        with self.assertRaises(UserError):
            copy.with_user(self.employee.user_id).sudo(False).write({'name': 'changed.pdf'})
        # Back to draft: the copy is unlocked and moved to the Trash
        decl.write({'state': 'draft'})
        trashed = self._copies(decl, trashed=True)
        self.assertEqual(trashed, copy)
        self.assertFalse(trashed.locked_by)
        # Submitted again: the same document is restored
        decl.write({'state': 'proof_submitted'})
        self.assertEqual(self._copies(decl), copy)

    def test_rejected_declaration_keeps_its_copies(self):
        decl = self._declaration()
        self._proof(decl, 'decl_80d_attachment_ids', 'Insurance.pdf')
        decl.write({'state': 'proof_submitted'})
        decl.write({'state': 'rejected'})
        self.assertEqual(self._copies(decl).mapped('name'), ['80D - Insurance.pdf'])
        self.assertFalse(self._copies(decl).is_locked)

    def test_deleting_the_copy_never_touches_the_declaration(self):
        decl = self._declaration()
        attachment = self._proof(decl, 'decl_80c_attachment_ids', 'PPF passbook.pdf')
        decl.write({'state': 'proof_submitted'})
        copy = self._copies(decl)
        copy.unlink()  # to the Trash
        copy.unlink()  # deleted for good
        self.assertFalse(copy.exists())
        self.assertTrue(attachment.exists())
        self.assertEqual(decl.decl_80c_attachment_ids, attachment)

    def test_same_file_name_gets_a_number(self):
        decl = self._declaration()
        self._proof(decl, 'decl_80c_attachment_ids', 'receipt.pdf')
        decl.write({'state': 'proof_submitted'})
        self._proof(decl, 'decl_80c_attachment_ids', 'receipt.pdf')  # replaced by a new file of the same name
        self.assertEqual(self._copies(decl).mapped('name'), ['80C - receipt (2).pdf'])
        self.assertEqual(self._copies(decl, trashed=True).mapped('name'), ['80C - receipt.pdf'])

    def test_employee_sees_own_proofs_only(self):
        own_decl = self._declaration()
        self._proof(own_decl, 'decl_80c_attachment_ids', 'Own.pdf')
        own_decl.write({'state': 'proof_submitted'})
        other_decl = self._declaration(self.other)
        self._proof(other_decl, 'decl_80c_attachment_ids', 'Other.pdf')
        other_decl.write({'state': 'proof_submitted'})
        own, others = self._copies(own_decl), self._copies(other_decl)
        File = self.env['dms.file'].with_user(self.employee.user_id)
        self.assertIn(own, File.search([]), "The employee sees their own proof")
        self.assertNotIn(others, File.search([]), "...but not a colleague's")

    def test_switch_off_and_store_existing(self):
        self.company.hds_dms_store_tax_proofs = False
        decl = self._declaration()
        self._proof(decl, 'decl_80c_attachment_ids', 'Later.pdf')
        decl.write({'state': 'proof_submitted'})
        self.assertFalse(self._copies(decl))
        # Switched on again: "Store existing tax proofs" copies them
        self.company.hds_dms_store_tax_proofs = True
        settings = self.env['res.config.settings'].create({})
        settings.action_hds_dms_store_existing_tax_proofs()
        self.assertEqual(self._copies(decl).mapped('name'), ['80C - Later.pdf'])

    def test_failure_does_not_block_the_declaration(self):
        decl = self._declaration()
        self._proof(decl, 'decl_80c_attachment_ids', 'Broken.pdf')
        from unittest.mock import patch
        with patch.object(type(decl), '_hds_dms_proof_folder', side_effect=ValueError('Documents down')):
            decl.write({'state': 'proof_submitted'})
        self.assertEqual(decl.state, 'proof_submitted')
        self.assertFalse(self._copies(decl))
        # Retried on the next save
        decl.write({'state': 'proof_under_review'})
        self.assertEqual(self._copies(decl).mapped('name'), ['80C - Broken.pdf'])

    def test_unreadable_file_is_not_copied_empty(self):
        decl = self._declaration()
        attachment = self._proof(decl, 'decl_80c_attachment_ids', 'Empty.pdf', content=b'')
        decl.write({'state': 'proof_submitted'})
        self.assertFalse(self._copies(decl), "No empty document in Documents")
        attachment.raw = b'%PDF-1.4 now readable'
        decl.write({'state': 'proof_under_review'})
        self.assertEqual(self._copies(decl).mapped('name'), ['80C - Empty.pdf'])
