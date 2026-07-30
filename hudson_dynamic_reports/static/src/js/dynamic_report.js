/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class DynamicReport extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            title: "Loading...",
            columns: [],
            lines: [],
            expandedLines: {},
            currencyId: null,
        });

        onWillStart(async () => {
            await this.fetchData();
        });
    }

    async fetchData() {
        const params = this.props.action.params || {};
        const model_name = params.model_name || null;
        const wizard_id = params.wizard_id || null;
        const data = params.data || {};

        const result = await this.orm.call("hudson.dynamic.report", "get_report_data", [
            model_name,
            wizard_id,
            data
        ]);

        this.state.title = result.title;
        this.state.columns = result.columns;
        this.state.lines = result.lines;
        this.state.currencyId = result.currency_id;
        
        // Expand top level lines by default if it's hierarchical
        for (const line of result.lines) {
            if (line.level === 1) {
                this.state.expandedLines[line.id] = true;
            }
        }
    }

    toggleExpand(lineId) {
        this.state.expandedLines[lineId] = !this.state.expandedLines[lineId];
    }

    isVisible(line) {
        if (line.level === 1) return true;
        
        const lines = this.state.lines;
        const index = lines.indexOf(line);
        for (let i = index - 1; i >= 0; i--) {
            if (lines[i].level < line.level) {
                if (!this.state.expandedLines[lines[i].id]) {
                    return false;
                }
                if (!this.isVisible(lines[i])) {
                    return false;
                }
                break;
            }
        }
        return true;
    }

    formatMonetary(value) {
        if (value === undefined || value === null) return "";
        return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    hasChildren(line) {
        const lines = this.state.lines;
        const index = lines.indexOf(line);
        if (index < lines.length - 1) {
            return lines[index + 1].level > line.level;
        }
        return false;
    }
    
    async onLineClicked(line) {
        const params = this.props.action.params || {};
        const model_name = params.model_name;
        const data = params.data || {};
        const form_data = data.form || data;
        
        if (line.type === 'account' && model_name === 'accounting.report') {
            const date_from = form_data.date_from || form_data.date_from_cmp;
            const date_to = form_data.date_to || form_data.date_to_cmp;
            
            // Extract account code
            const nameParts = line.name.split(' ');
            const code = nameParts[0];
            
            const action = {
                type: 'ir.actions.act_window',
                name: 'Journal Items',
                res_model: 'account.move.line',
                view_mode: 'list,form',
                views: [[false, 'list'], [false, 'form']],
                domain: [['account_id.code', '=', code]],
            };
            
            if (date_from) action.domain.push(['date', '>=', date_from]);
            if (date_to) action.domain.push(['date', '<=', date_to]);
            
            await this.action.doAction(action);
        }
    }

    printView() {
        window.print();
    }

    async exportPDF() {
        const params = this.props.action.params || {};
        const model_name = params.model_name;
        const wizard_id = params.wizard_id;
        const data = params.data || {};
        
        if (model_name && wizard_id) {
            const context = {
                active_model: data.model || this.props.action.context?.active_model || model_name,
                active_ids: data.ids || this.props.action.context?.active_ids || [wizard_id],
                active_id: (data.ids && data.ids[0]) || this.props.action.context?.active_id || wizard_id,
            };
            const action = await this.orm.call(model_name, "check_report", [[wizard_id]], { context });
            if (action) {
                if (!action.context) {
                    action.context = {};
                }
                Object.assign(action.context, context);
                await this.action.doAction(action);
            }
        }
    }

    exportCSV() {
        const headers = this.state.columns.map(col => `"${col.label.replace(/"/g, '""')}"`);
        let csvContent = headers.join(",") + "\r\n";
        
        for (const line of this.state.lines) {
            if (!this.isVisible(line)) continue;
            const row = this.state.columns.map(col => {
                let val = line[col.field];
                if (val === undefined || val === null) val = '';
                if (col.type === 'monetary') {
                    val = Number(val).toFixed(2);
                }
                return `"${String(val).replace(/"/g, '""')}"`;
            });
            csvContent += row.join(",") + "\r\n";
        }
        
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `${this.state.title.replace(/\s+/g, '_')}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    exportJSON() {
        const data = {
            title: this.state.title,
            columns: this.state.columns,
            lines: this.state.lines.filter(line => this.isVisible(line))
        };
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `${this.state.title.replace(/\s+/g, '_')}.json`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }
}

DynamicReport.template = "hudson_dynamic_reports.DynamicReport";

registry.category("actions").add("hudson_dynamic_reports.dynamic_report", DynamicReport);
