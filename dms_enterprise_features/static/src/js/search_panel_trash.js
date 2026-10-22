/* eslint-disable no-undef */
/** @odoo-module **/

import { SearchPanel } from "@web/search/search_panel/search_panel";
import { patch } from "@web/core/utils/patch";
import { useService, useBus } from "@web/core/utils/hooks";
import { onMounted, onWillStart, onWillUpdateProps, proxy } from "@odoo/owl";

patch(SearchPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.action = useService("action");
        this.dmsTrashState = proxy({ 
            isDmsView: false,
            trashCount: 0,
        });

        const updateData = async () => {
            if (this.isDmsView()) {
                await this.fetchTrashCount();
            }
        };

        onWillStart(updateData);
        onWillUpdateProps(updateData);

        if (this.env.searchModel) {
            useBus(this.env.searchModel, "update", async () => {
                if (this.isDmsView()) {
                    await this.fetchTrashCount();
                }
            });
        }
    },

    isDmsView() {
        try {
            const resModel = this.env.searchModel?.resModel;
            return resModel === "dms.file" || resModel === "dms.directory";
        } catch {
            return false;
        }
    },

    async fetchTrashCount() {
        try {
            const fileCount = await this.orm.searchCount(
                "dms.file",
                [["is_trashed", "=", true]],
                { context: { active_test: false } }
            );
            const dirCount = await this.orm.searchCount(
                "dms.directory",
                [["is_trashed", "=", true], "|", ["parent_id", "=", false], ["parent_is_trashed", "=", false]]
            );
            this.dmsTrashState.trashCount = fileCount + dirCount;
        } catch {
            this.dmsTrashState.trashCount = 0;
        }
    },

    openTrash() {
        this.action.doAction("dms_enterprise_features.action_dms_file_trash", { clearBreadcrumbs: true });
    },

    async toggleCategory(category, value) {
        // If we are in the Trash action and the user clicks on a directory in the sidebar
        if (this.env.config.actionId && this.env.searchModel?.resModel === "dms.file") {
            const currentActionId = this.action.currentController?.action?.id;
            const currentActionXmlId = this.action.currentController?.action?.xml_id;
            
            const actionName = this.action.currentController?.action?.name;
            
            if (this.env.config.actionId === currentActionId && (currentActionXmlId === "dms_enterprise_features.action_dms_file_trash" || actionName === "Trash")) {
                // Navigate back to normal 'My Documents' view and pre-select the folder
                this.action.doAction("dms.action_dms_file", {
                    clearBreadcrumbs: true,
                    additionalContext: {
                        searchpanel_default_directory_id: value.id,
                    }
                });
                return;
            }
        }
        return super.toggleCategory(category, value);
    },
});
