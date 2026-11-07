/** @odoo-module **/

/**
 * Folder "Edit" popup used by the folder cards, the list folder rows and the
 * search-panel folder menu.
 *
 * Opened as a FormViewDialog rather than a `target: "new"` act_window so it
 * gets a real title (an unnamed action dialog falls back to "Odoo") and the
 * standard expand button next to the close button, which opens the folder in
 * the full-page form view.
 */

import { _t } from "@web/core/l10n/translation";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

/**
 * @param {Object} env component env (needs env.services.dialog)
 * @param {number} dirId dms.directory id
 * @param {Function} [onClose] called once the popup is closed
 */
export function openDirectoryEditDialog(env, dirId, onClose) {
    env.services.dialog.add(
        FormViewDialog,
        {
            title: String(_t("Edit Folder")),
            resModel: "dms.directory",
            resId: dirId,
            canExpand: true,
        },
        { onClose: () => onClose?.() }
    );
}
