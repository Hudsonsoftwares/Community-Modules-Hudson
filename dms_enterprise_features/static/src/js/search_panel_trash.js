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
});
