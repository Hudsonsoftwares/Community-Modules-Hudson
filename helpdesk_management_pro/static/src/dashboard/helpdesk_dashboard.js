/** @odoo-module **/

import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class HelpdeskDashboard extends Component {
    static template = "helpdesk_management_pro.HelpdeskDashboard";
    
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ metrics: null });
        
        onWillStart(async () => {
            await this.fetchMetrics();
        });
    }

    async fetchMetrics() {
        try {
            this.state.metrics = await this.orm.call("helpdesk.management.team", "get_dashboard_metrics", []);
            
            // Load user preferences from localStorage
            this.state.metrics.daily_target_value = localStorage.getItem('helpdesk_target_closed') || 1;
            this.state.metrics.daily_target_success_val = localStorage.getItem('helpdesk_target_success') || 85;
            this.state.metrics.daily_target = `${this.state.metrics.daily_target_success_val}%`;
            this.state.metrics.daily_target_rating_val = localStorage.getItem('helpdesk_target_rating') || 4.5;
            this.state.metrics.daily_rating_target = `${this.state.metrics.daily_target_rating_val} / 5`;
        } catch (e) {
            console.error("Failed to fetch dashboard metrics", e);
        }
    }

    async updateTarget(targetType, ev) {
        let value = parseFloat(ev.target.value);
        if (isNaN(value)) return;

        if (targetType === 'closed') {
            if (value < 0) value = 0;
            this.state.metrics.daily_target_value = value;
            localStorage.setItem('helpdesk_target_closed', value);
            ev.target.value = value;
        } else if (targetType === 'success') {
            if (value < 0) value = 0;
            if (value > 100) value = 100;
            this.state.metrics.daily_target_success_val = value;
            this.state.metrics.daily_target = `${value}%`;
            localStorage.setItem('helpdesk_target_success', value);
            ev.target.value = value;
        } else if (targetType === 'rating') {
            if (value < 0) value = 0;
            if (value > 5) value = 5;
            this.state.metrics.daily_target_rating_val = value;
            this.state.metrics.daily_rating_target = `${value} / 5`;
            localStorage.setItem('helpdesk_target_rating', value);
            ev.target.value = value;
        }
    }

    _openTickets(title, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "helpdesk.management.ticket",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: domain,
            context: {},
        });
    }

    openMyTickets() {
        this._openTickets("Open Tickets", ['|', ['stage_id', '=', false], ['stage_id.is_close', '=', false]]);
    }

    openHighPriority() {
        this._openTickets("High Priority", ['&', '|', ['stage_id', '=', false], ['stage_id.is_close', '=', false], ['priority', '=', '2']]);
    }

    openUrgent() {
        this._openTickets("Urgent", ['&', '|', ['stage_id', '=', false], ['stage_id.is_close', '=', false], ['priority', '=', '3']]);
    }

    openFailed() {
        this._openTickets("Failed Tickets", ['&', '|', ['stage_id', '=', false], ['stage_id.is_close', '=', false], ['sla_status', '=', 'breached']]);
    }

    openClosed() {
        this._openTickets("Closed Tickets", [['stage_id', '!=', false], ['stage_id.is_close', '=', true]]);
    }
}

export class HelpdeskDashboardKanbanRenderer extends KanbanRenderer {
    static template = "helpdesk_management_pro.DashboardKanbanRenderer";
    static components = {
        ...KanbanRenderer.components,
        HelpdeskDashboard,
    };
}

export const helpdeskDashboardKanbanView = {
    ...kanbanView,
    Renderer: HelpdeskDashboardKanbanRenderer,
};

registry.category("views").add("helpdesk_dashboard_kanban", helpdeskDashboardKanbanView);
