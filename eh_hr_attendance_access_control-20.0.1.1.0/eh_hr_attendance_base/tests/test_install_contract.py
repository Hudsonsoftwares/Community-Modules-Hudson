# -*- encoding: utf-8 -*-
"""What the install leaves behind, checked rather than assumed.

Install validates a view arch but never renders it, and it reports nothing
about the records a post_init_hook wrote. The three things this module leans
on at install time are checked here: the access level dropdown the hook
builds, the icon names the views carry (Font Awesome is gone on Odoo 20, so a
stale name renders a blank glyph without any error), and the timezone
selection, which now comes from the standard Odoo list rather than from a
third party timezone package.
"""
import re
from pathlib import Path

from lxml import etree

from odoo.addons.web.icons import ICONS

from .common import EhHrTestCommon


ACCESS_GROUPS = (
    'eh_hr_attendance_base.group_eh_hr_user',
    'eh_hr_attendance_base.group_eh_hr_manager',
    'eh_hr_attendance_base.group_eh_hr_admin',
    'eh_hr_attendance_base.group_eh_hr_auditor',
)


class TestInstallContract(EhHrTestCommon):

    def test_access_dropdown_privilege_is_assigned(self):
        """post_init_hook groups the four roles under one privilege, which is
        what renders them as a single access level dropdown.
        """
        privileges = {self.env.ref(xmlid).privilege_id for xmlid in ACCESS_GROUPS}
        self.assertEqual(len(privileges), 1, 'the four roles must share one privilege')
        privilege = privileges.pop()
        self.assertEqual(privilege.name, 'ERP Heritage Attendance Suite')
        # The category is owned by the compat layer, so only its presence is
        # asserted here: without one the roles would not group on the user form.
        self.assertTrue(privilege.category_id)

    def test_view_icons_are_material_symbols(self):
        """Every icon the module ships resolves in the Odoo 20 icon set."""
        view_data = self.env['ir.model.data'].search([
            ('module', '=', 'eh_hr_attendance_base'),
            ('model', '=', 'ir.ui.view'),
        ])
        self.assertTrue(view_data, 'the module must ship views')
        checked = 0
        for view in self.env['ir.ui.view'].browse(view_data.mapped('res_id')):
            root = etree.fromstring(view.arch)
            for node in root.iter():
                for attribute in ('icon', 'data-icon'):
                    name = node.get(attribute)
                    if not name:
                        continue
                    checked += 1
                    self.assertIn(
                        name, ICONS,
                        '%s: icon %r is not an Odoo 20 icon name' % (view.name, name),
                    )
                classes = node.get('class') or ''
                self.assertNotIn('fa-', classes, '%s: Font Awesome class left behind' % view.name)
        self.assertGreaterEqual(checked, 1, 'no icon was checked')

    def test_timezone_selection_is_populated(self):
        """The site timezone selection is built from the standard Odoo 20
        timezone list, so stored values keep resolving.
        """
        selection = dict(self.Site.fields_get(['timezone'])['timezone']['selection'])
        self.assertGreater(len(selection), 100)
        self.assertIn('UTC', selection)
        self.assertIn('Australia/Melbourne', selection)

        site = self.Site.create({
            'name': 'Timezone site',
            'code': 'tz-site',
            'company_id': self.company.id,
            'timezone': 'Australia/Melbourne',
        })
        self.assertEqual(site.timezone, 'Australia/Melbourne')

    def test_listing_matches_the_manifest_version(self):
        root = Path(__file__).parents[1]
        listing = (root / 'static/description/index.html').read_text()
        manifest = (root / '__manifest__.py').read_text()
        version = re.search(r"'version': '([^']+)'", manifest)
        self.assertIsNotNone(version, 'no version in the manifest')
        self.assertIn('v%s' % version.group(1), listing)
        self.assertNotIn('Odoo 19', listing)
