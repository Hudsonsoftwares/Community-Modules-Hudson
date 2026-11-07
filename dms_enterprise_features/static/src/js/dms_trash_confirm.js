/** @odoo-module **/

/**
 * Confirmation before anything is sent to the DMS Trash.
 *
 * - confirmSendToTrash(): small dialog used by the folder buttons in the
 *   unified kanban/list renderers and the search-panel folder menu.
 * - ActionMenus patch: the gear-menu "Send to Trash" server actions on
 *   dms.file / dms.directory ask the same question before running.
 *   (Card dropdown buttons use the view-level `confirm` attribute instead.)
 */

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ActionMenus } from "@web/search/action_menus/action_menus";

const TRASH_MODELS = {
    "dms.file": { one: _t("file"), many: _t("files") },
    "dms.directory": { one: _t("folder"), many: _t("folders") },
};

/**
 * @param {Object} dialogService
 * @param {Object} [options]
 * @param {string} [options.resModel] "dms.file" or "dms.directory"
 * @param {number} [options.count]
 * @returns {Promise<boolean>} true when the user confirmed
 */
export function confirmSendToTrash(dialogService, { resModel = "dms.directory", count = 1 } = {}) {
    const labels = TRASH_MODELS[resModel] || { one: _t("item"), many: _t("items") };
    const what =
        count > 1 ? `${count} ${String(labels.many)}` : String(_t("this %s", String(labels.one)));
    let body = String(_t("Are you sure you want to send %s to the Trash?", what));
    if (resModel === "dms.directory") {
        body += " " + String(_t("Everything inside will be moved to the Trash as well."));
    }
    body += " " + String(_t("You can restore it later from the Trash."));
    return new Promise((resolve) => {
        let confirmed = false;
        dialogService.add(
            ConfirmationDialog,
            {
                title: String(_t("Send to Trash")),
                body,
                confirmLabel: String(_t("Send to Trash")),
                confirmClass: "btn-danger",
                cancelLabel: String(_t("Cancel")),
                confirm: () => {
                    confirmed = true;
                },
                cancel: () => {},
            },
            { onClose: () => resolve(confirmed) }
        );
    });
}

patch(ActionMenus.prototype, {
    async executeAction(action) {
        const resModel = this.props.resModel;
        const isTrashAction =
            action?.name === "Send to Trash" || action?.name === String(_t("Send to Trash"));
        if (TRASH_MODELS[resModel] && isTrashAction) {
            let count = this.props.getActiveIds().length;
            if (this.props.isDomainSelected) {
                count = await this.orm.searchCount(resModel, this.props.domain, {
                    context: this.props.context,
                });
            }
            const ok = await confirmSendToTrash(this.env.services.dialog, { resModel, count });
            if (!ok) {
                return;
            }
        }
        return super.executeAction(...arguments);
    },
});
