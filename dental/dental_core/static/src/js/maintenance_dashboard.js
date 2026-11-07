/** @odoo-module **/
import { Component, proxy, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class MaintenanceDashboard extends Component {
    static template = "dental_core.MaintenanceDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = proxy({
            selectedBranchId: null,
            branches: [],
            kpis: {},
            recent_requests: [],
            upcoming_preventive: [],
            category_counts: {},
            condition_counts: {},
            costly_equipments: [],
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData(branchId = null) {
        try {
            const data = await this.orm.call(
                "maintenance.equipment",
                "get_maintenance_dashboard_data",
                [],
                { branch_id: branchId || this.state.selectedBranchId }
            );
            if (data) {
                this.state.selectedBranchId = data.current_branch_id;
                this.state.branches = data.branches || [];
                this.state.kpis = data.kpis || {};
                this.state.recent_requests = data.recent_requests || [];
                this.state.upcoming_preventive = data.upcoming_preventive || [];
                this.state.category_counts = data.category_counts || {};
                this.state.condition_counts = data.condition_counts || {};
                this.state.costly_equipments = data.costly_equipments || [];
            }
        } catch (e) {
            console.error("Failed to load maintenance dashboard data:", e);
        }
    }

    async onBranchChange(ev) {
        const val = parseInt(ev.target.value);
        this.state.selectedBranchId = val;
        await this.loadData(val);
    }

    openEquipmentRegistry() {
        this.action.doAction("dental_core.action_dental_equipment_registry");
    }

    openUnderMaintenance() {
        this.action.doAction({
            name: "Equipment Under Maintenance / Unavailable",
            type: "ir.actions.act_window",
            res_model: "maintenance.equipment",
            view_mode: "list,form",
            domain: [["is_available", "=", false]],
        });
    }

    openRepairRequests() {
        this.action.doAction("dental_core.action_dental_maintenance_requests");
    }

    openOverduePreventive() {
        this.action.doAction({
            name: "Overdue Preventive Maintenance",
            type: "ir.actions.act_window",
            res_model: "maintenance.equipment",
            view_mode: "list,form",
            domain: [["is_overdue", "=", true]],
        });
    }

    openPreventiveDueSoon() {
        this.action.doAction({
            name: "Preventive Maintenance Schedules",
            type: "ir.actions.act_window",
            res_model: "maintenance.equipment",
            view_mode: "list,form",
            domain: [["next_maintenance_date", "!=", false]],
            context: { search_default_group_by_category: 1 },
        });
    }

    openWarrantyExpiring() {
        this.action.doAction({
            name: "Upcoming Warranty Expirations",
            type: "ir.actions.act_window",
            res_model: "maintenance.equipment",
            view_mode: "list,form",
            domain: [["warranty_status", "in", ["valid", "expiring_soon"]]],
        });
    }

    openRequestRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "maintenance.request",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
        });
    }

    openEquipmentRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "maintenance.equipment",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
        });
    }

    openNewIssueModal() {
        this.action.doAction("dental_core.action_reception_report_equipment_issue", {
            onClose: () => this.loadData(),
        });
    }

    openNewEquipmentModal() {
        this.action.doAction({
            name: "Register New Equipment",
            type: "ir.actions.act_window",
            res_model: "maintenance.equipment",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    async schedulePreventiveForEquipment(equipmentId) {
        try {
            const action = await this.orm.call(
                "maintenance.equipment",
                "action_schedule_preventive_maintenance",
                [[equipmentId]]
            );
            if (action) {
                this.action.doAction(action, {
                    onClose: () => this.loadData(),
                });
            }
        } catch (e) {
            console.error("Failed to schedule preventive maintenance:", e);
        }
    }
}

registry.category("actions").add("dental_core.maintenance_dashboard", MaintenanceDashboard);
