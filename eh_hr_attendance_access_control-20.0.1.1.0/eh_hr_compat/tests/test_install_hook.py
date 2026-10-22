# -*- coding: utf-8 -*-
"""The install hook seeds the publisher contact. It runs on every install of
every platform module, so it has to stay idempotent and it must never write a
field the running Odoo computes for itself."""
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.eh_hr_compat import post_init_hook

CONTACT_EMAIL = 'info@erpheritage.com.au'


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_compat')
class TestInstallHook(TransactionCase):

    def _contacts(self):
        return self.env['res.partner'].with_context(active_test=False).search(
            [('email', '=', CONTACT_EMAIL)])

    def test_install_seeded_exactly_one_contact(self):
        contacts = self._contacts()
        self.assertEqual(len(contacts), 1,
                         'The module install must leave one publisher contact.')
        self.assertTrue(contacts.name)
        self.assertEqual(contacts.website, 'https://www.erpheritage.com.au')

    def test_hook_is_idempotent(self):
        post_init_hook(self.env)
        post_init_hook(self.env)
        self.assertEqual(len(self._contacts()), 1,
                         'Re-running the hook must not duplicate the contact.')

    def test_hook_writes_no_computed_or_missing_field(self):
        # The seed dict is filtered against res.partner._fields, so a field
        # the running Odoo dropped (res.partner.mobile on 19) is skipped
        # rather than raising. Archiving the contact and re-running proves the
        # lookup also sees inactive rows.
        contact = self._contacts()
        contact.active = False
        post_init_hook(self.env)
        self.assertEqual(len(self._contacts()), 1,
                         'An archived contact must not be seeded again.')
