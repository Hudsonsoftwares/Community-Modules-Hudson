/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, xml, onWillStart, useState } from "@odoo/owl";
import { SpreadsheetComponent } from "@spreadsheet/actions/spreadsheet_component";
import { Model } from "@odoo/o-spreadsheet";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

class QualitySpreadsheetAction extends Component {
    static template = xml`
        <div class="o_spreadsheet_action h-100 d-flex flex-column">
            <ControlPanel display="controlPanelDisplay" />
            <div class="flex-grow-1 position-relative">
                <t t-if="state.model">
                    <SpreadsheetComponent model="state.model" />
                </t>
            </div>
        </div>
    `;
    static components = { SpreadsheetComponent, ControlPanel };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.state = useState({ model: null });
        
        this.controlPanelDisplay = {};

        onWillStart(async () => {
            const resModel = this.props.action.params.res_model || "quality.spreadsheet.template";
            this.resModel = resModel;
            const spreadsheetId = this.props.action.params.spreadsheet_id || this.props.action.context.active_id;
            this.spreadsheetId = spreadsheetId;
            const dataField = resModel === "quality.spreadsheet.template" ? "spreadsheet_data" : "spreadsheet_content";
            const data = await this.orm.read(resModel, [spreadsheetId], [dataField, "name"]);
            
            this.env.config.setDisplayName(data[0].name || "Spreadsheet");

            let spreadsheetData = {};
            if (data[0][dataField]) {
                try {
                    let rawData = data[0][dataField];
                    // If it's base64 encoded (which doesn't start with { or [), we decode it
                    if (typeof rawData === 'string' && !rawData.trim().startsWith('{') && !rawData.trim().startsWith('[')) {
                        rawData = decodeURIComponent(escape(atob(rawData)));
                    }
                    spreadsheetData = JSON.parse(rawData);
                } catch (e) {
                    console.error("Invalid spreadsheet data", e);
                }
            }
            
            this.state.model = new Model(spreadsheetData, {
                evalContext: { env: this.env },
            });
            
            this.state.model.on("update", this, this._onModelUpdate.bind(this));
        });
    }

    _onModelUpdate() {
        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }
        this.saveTimeout = setTimeout(() => {
            this.save();
        }, 2000); // 2 second debounce for auto-save
    }

    async save() {
        if (!this.state.model) return;
        const data = this.state.model.exportData();
        const jsonStr = JSON.stringify(data);
        
        if (this.resModel === "quality.spreadsheet.template") {
            const base64Data = btoa(unescape(encodeURIComponent(jsonStr)));
            await this.orm.write(this.resModel, [this.spreadsheetId], {
                spreadsheet_binary_data: base64Data
            });
        } else {
            await this.orm.write(this.resModel, [this.spreadsheetId], {
                spreadsheet_content: jsonStr
            });
        }
    }
}

registry.category("actions").add("action_quality_spreadsheet", QualitySpreadsheetAction, { force: true });
