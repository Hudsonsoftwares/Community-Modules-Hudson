/** @odoo-module **/

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { listView } from "@web/views/list/list_view";
import { Component } from "@odoo/owl";

function triggerDirectUpload(orm, action) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/pdf";
    input.style.display = "none";
    document.body.appendChild(input);
    
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) {
            document.body.removeChild(input);
            return;
        }
        
        const reader = new FileReader();
        reader.onload = async (event) => {
            let base64 = event.target.result;
            // Remove data url prefix
            if (base64.indexOf("base64,") !== -1) {
                base64 = base64.split("base64,")[1];
            }
            try {
                const res = await orm.call("hudson.sign.template", "create_template_from_file", [file.name, base64]);
                if (res) {
                    action.doAction(res);
                }
            } catch (err) {
                console.error("Upload failed", err);
            }
            document.body.removeChild(input);
        };
        reader.readAsDataURL(file);
    };
    
    input.click();
}

// Extension for Kanban
export class HudsonSignTemplateKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async uploadPdf() {
        triggerDirectUpload(this.orm, this.action);
    }
}

export const hudsonSignTemplateKanbanView = {
    ...kanbanView,
    Controller: HudsonSignTemplateKanbanController,
    buttonTemplate: "hudson_sign.KanbanButtons",
};

registry.category("views").add("hudson_sign_template_kanban", hudsonSignTemplateKanbanView);

// Extension for List
export class HudsonSignTemplateListController extends ListController {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async uploadPdf() {
        triggerDirectUpload(this.orm, this.action);
    }
}

export const hudsonSignTemplateListView = {
    ...listView,
    Controller: HudsonSignTemplateListController,
    buttonTemplate: "hudson_sign.ListButtons",
};

registry.category("views").add("hudson_sign_template_list", hudsonSignTemplateListView);
