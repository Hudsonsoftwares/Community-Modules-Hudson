/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

export class SecondOpinionDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const reactive = proxy || useState;
        this.state = reactive({ loading: true, data: null });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("dental.second.opinion.dashboard", "get_dashboard_data", []);
        } catch (error) {
            console.error("Failed to load second opinion dashboard:", error);
            this.notification.add(_t("Could not load the second opinion dashboard."), { type: "warning" });
        } finally {
            this.state.loading = false;
        }
    }

    priorityLabel(priority) {
        return { 1: _t("Urgent"), 2: _t("Emergency") }[priority] || "";
    }

    openList(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "dental.second.opinion",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    openRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dental.second.opinion",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTile(key) {
        const tiles = {
            sp_new: [_t("New Requests"), [["specialist_user_id", "=", user.userId], ["state", "=", "submitted"]]],
            sp_review: [_t("Under Review"), [["specialist_user_id", "=", user.userId], ["state", "=", "in_review"]]],
            sp_clarification: [_t("Clarification Requested"), [["specialist_user_id", "=", user.userId], ["state", "=", "clarification"]]],
            sp_waiting: [_t("Waiting on Dentist"), [["specialist_user_id", "=", user.userId], ["state", "in", ["info_requested", "opinion_submitted"]]]],
            sp_overdue: [_t("Overdue Reviews"), [["specialist_user_id", "=", user.userId], ["is_overdue", "=", true]]],
            rq_decide: [_t("Awaiting My Decision"), [["requesting_user_id", "=", user.userId], ["state", "=", "opinion_submitted"]]],
            rq_info: [_t("Information Requested"), [["requesting_user_id", "=", user.userId], ["state", "=", "info_requested"]]],
            rq_declined: [_t("Declined"), [["requesting_user_id", "=", user.userId], ["state", "=", "declined"]]],
            rq_open: [_t("My Open Requests"), [["requesting_user_id", "=", user.userId], ["state", "in", ["submitted", "in_review", "info_requested", "opinion_submitted", "clarification"]]]],
            cl_open: [_t("Open Requests"), [["state", "in", ["submitted", "in_review", "info_requested", "opinion_submitted", "clarification"]]]],
            cl_overdue: [_t("Overdue Requests"), [["is_overdue", "=", true]]],
            cl_emergency: [_t("Emergency Requests"), [["priority", "=", "2"], ["state", "in", ["submitted", "in_review", "info_requested", "opinion_submitted", "clarification"]]]],
        };
        const [name, domain] = tiles[key];
        this.openList(name, domain);
    }
}

SecondOpinionDashboard.template = "dental_second_opinion.SecondOpinionDashboard";
registry.category("actions").add("dental_second_opinion.dashboard", SecondOpinionDashboard);
