/* eslint-disable no-undef */
/** @odoo-module **/

import { SearchPanel } from "@web/search/search_panel/search_panel";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onMounted, useState } from "@odoo/owl";

patch(SearchPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.action = useService("action");
        this.dmsTrashState = useState({ isDmsView: false });
    },

    isDmsView() {
        try {
            const resModel = this.env.searchModel?.resModel;
            return resModel === "dms.file" || resModel === "dms.directory";
        } catch {
            return false;
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
                        search_default_group_directory: 1
                    }
                });
                return;
            }
        }
        return super.toggleCategory(category, value);
    },
});
