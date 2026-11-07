"""Neutralise the stale folder-cards kanban view before the XML reloads.

20.0.1.0.3 rebuilt the folder card menu as a flat list and removed its
"Files" item. The stored arch of view_dms_directory_kanban_folder_cards
still targets that item, so validating the updated parent view
(view_dms_directory_kanban_inherit_trash) failed with "cannot be located in
parent view". Emptying the child's arch lets the parent load; the XML file
then rewrites the child with its new arch.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_view v
           SET arch_db = jsonb_build_object('en_US', '<data/>')
          FROM ir_model_data d
         WHERE d.model = 'ir.ui.view'
           AND d.res_id = v.id
           AND d.module = 'dms_enterprise_features'
           AND d.name = 'view_dms_directory_kanban_folder_cards'
        """
    )
