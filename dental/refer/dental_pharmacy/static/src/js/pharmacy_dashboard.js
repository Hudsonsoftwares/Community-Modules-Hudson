/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy } from "@odoo/owl";
import { user } from "@web/core/user";

export class PharmacyDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.userName = user.name;

        const now = new Date();
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        this.currentFormattedDate = `${days[now.getDay()]}, ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()}`;

        this.state = proxy({
            loading: true,
            data: {
                total_medicines: 0,
                in_stock: 0,
                low_stock: 0,
                out_of_stock: 0,
                total_batches: 0,
                valid_batches: 0,
                near_expiry_batches: 0,
                expired_batches: 0,
                total_prescriptions: 0,
                pending_prescriptions: 0,
                partially_dispensed: 0,
                fully_dispensed: 0,
                draft_prescriptions: 0,
                prescriptions_today: 0,
                prescriptions_growth: '0%',
                prescriptions_trend_is_up: false,
                prescriptions_trend_is_down: false,
                medicines_dispensed_today: 0,
                medicines_dispensed_growth: '0%',
                dispensed_trend_is_up: false,
                dispensed_trend_is_down: false,
                today_dispensed_count: 0,
                today_dispensed_amount: 0,
                total_dispensed_amount: 0,
                currency_symbol: '',
                stock_breakdown: {
                    total_items: 0,
                    in_stock: 0,
                    in_stock_pct: 0,
                    low_stock: 0,
                    low_stock_pct: 0,
                    expiring_soon: 0,
                    expiring_soon_pct: 0,
                    out_of_stock: 0,
                    out_of_stock_pct: 0,
                    inactive: 0,
                    inactive_pct: 0,
                },
                chart_activity: {
                    labels: [],
                    prescriptions: [],
                    dispensed: [],
                },
                recent_prescriptions: [],
                low_stock_medicines: [],
                expiry_alerts: [],
            }
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const result = await this.orm.call("dental.pharmacy.dashboard", "get_dashboard_data", []);
            if (result && typeof result === 'object') {
                Object.assign(this.state.data, result);
            }
        } catch (error) {
            console.error("Failed to load pharmacy dashboard analytics:", error);
            if (this.notification) {
                this.notification.add("Could not refresh pharmacy metrics.", { type: "warning" });
            }
        } finally {
            this.state.loading = false;
        }
    }

    get chartInfo() {
        const labels = this.state.data.chart_activity?.labels || [];
        const rx = this.state.data.chart_activity?.prescriptions || [];
        const disp = this.state.data.chart_activity?.dispensed || [];

        const n = Math.max(labels.length, 1);
        const maxVal = Math.max(10, ...rx, ...disp);

        const yLabels = [
            Math.round(maxVal),
            Math.round(maxVal * 0.75),
            Math.round(maxVal * 0.5),
            Math.round(maxVal * 0.25),
            0,
        ];

        const rxPoints = [];
        const dispPoints = [];

        for (let i = 0; i < n; i++) {
            const x = labels.length > 1 ? 40 + (i / (labels.length - 1)) * 400 : 240;
            const rxVal = rx[i] || 0;
            const rxY = 150 - (rxVal / maxVal) * 130;
            rxPoints.push({ x, y: rxY, val: rxVal });

            const dispVal = disp[i] || 0;
            const dispY = 150 - (dispVal / maxVal) * 130;
            dispPoints.push({ x, y: dispY, val: dispVal });
        }

        const buildPath = (points) => {
            if (points.length === 0) return "";
            if (points.length === 1) return `M 40 ${points[0].y} L 440 ${points[0].y}`;
            let path = `M ${points[0].x} ${points[0].y}`;
            for (let i = 1; i < points.length; i++) {
                const prev = points[i - 1];
                const curr = points[i];
                const cpX1 = prev.x + (curr.x - prev.x) / 2;
                const cpY1 = prev.y;
                const cpX2 = cpX1;
                const cpY2 = curr.y;
                path += ` C ${cpX1} ${cpY1}, ${cpX2} ${cpY2}, ${curr.x} ${curr.y}`;
            }
            return path;
        };

        const rxLinePath = buildPath(rxPoints);
        const dispLinePath = buildPath(dispPoints);

        const rxAreaPath = rxPoints.length > 0
            ? `${rxLinePath} L ${rxPoints[rxPoints.length - 1].x} 150 L ${rxPoints[0].x} 150 Z`
            : "";
        const dispAreaPath = dispPoints.length > 0
            ? `${dispLinePath} L ${dispPoints[dispPoints.length - 1].x} 150 L ${dispPoints[0].x} 150 Z`
            : "";

        return {
            labels,
            yLabels,
            rxPoints,
            dispPoints,
            rxLinePath,
            dispLinePath,
            rxAreaPath,
            dispAreaPath,
        };
    }

    get donutInfo() {
        const sb = this.state.data.stock_breakdown || {};
        const total = sb.total_items || 0;
        const C = 2 * Math.PI * 54; // ~339.292

        if (total === 0) {
            return {
                isEmpty: true,
                total: 0,
                segments: [],
            };
        }

        const slices = [
            { key: 'in_stock', color: '#00b4d8', pct: sb.in_stock_pct || 0 },
            { key: 'low_stock', color: '#f97316', pct: sb.low_stock_pct || 0 },
            { key: 'expiring_soon', color: '#eab308', pct: sb.expiring_soon_pct || 0 },
            { key: 'out_of_stock', color: '#ef4444', pct: sb.out_of_stock_pct || 0 },
            { key: 'inactive', color: '#cbd5e1', pct: sb.inactive_pct || 0 },
        ];

        let currentOffset = 0;
        const segments = [];

        for (const slice of slices) {
            if (slice.pct > 0) {
                const dash = (slice.pct / 100) * C;
                segments.push({
                    key: slice.key,
                    color: slice.color,
                    dasharray: `${dash.toFixed(1)} ${(C - dash).toFixed(1)}`,
                    dashoffset: (-currentOffset).toFixed(1),
                });
                currentOffset += dash;
            }
        }

        return {
            isEmpty: false,
            total,
            segments,
        };
    }

    openFilteredMedicines(filterType) {
        let domain = [["is_medicine", "=", true]];
        let title = "Dental Medicines";

        if (filterType === 'in_stock') {
            domain.push(["stock_status", "=", "in_stock"]);
            title = "In-Stock Medicines";
        } else if (filterType === 'low_stock') {
            domain.push(["stock_status", "=", "low_stock"]);
            title = "Low Stock Alerts";
        } else if (filterType === 'out_of_stock') {
            domain.push(["stock_status", "=", "out_of_stock"]);
            title = "Out-of-Stock Medicines";
        }

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: 'product.template',
            domain: domain,
            views: [[false, 'list'], [false, 'kanban'], [false, 'form']],
            target: 'current'
        });
    }

    openFilteredBatches(filterType) {
        let domain = [["is_medicine", "=", true]];
        let title = "Medicine Batches";

        if (filterType === 'expired') {
            domain.push(["expiry_status", "=", "expired"]);
            title = "Expired Batches (Do Not Dispense)";
        } else if (filterType === 'near_expiry') {
            domain.push(["expiry_status", "=", "near_expiry"]);
            title = "Near Expiry Batches (≤ 60 Days)";
        } else if (filterType === 'valid') {
            domain.push(["expiry_status", "=", "valid"]);
            title = "Valid & Safe Batches";
        }

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: 'stock.lot',
            domain: domain,
            views: [[false, 'list'], [false, 'form']],
            target: 'current'
        });
    }

    openFilteredPrescriptions(filterType) {
        let domain = [];
        let title = "Clinical Prescriptions";

        if (filterType === 'pending') {
            domain = [["state", "=", "confirmed"]];
            title = "Prescriptions Ready for Dispensing";
        } else if (filterType === 'partially_dispensed') {
            domain = [["state", "=", "partially_dispensed"]];
            title = "Partially Dispensed Prescriptions";
        } else if (filterType === 'fully_dispensed') {
            domain = [["state", "=", "fully_dispensed"]];
            title = "Fully Dispensed Prescriptions";
        } else if (filterType === 'today') {
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');
            const todayStr = `${year}-${month}-${day}`;
            domain = [["prescription_date", "=", todayStr]];
            title = "Today's Clinical Prescriptions";
        }

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: 'dental.prescription',
            domain: domain,
            views: [[false, 'list'], [false, 'kanban'], [false, 'form']],
            target: 'current'
        });
    }

    openDispenseOrders(filterType) {
        let domain = [];
        let title = "Pharmacy Dispense Orders";

        if (filterType === 'today') {
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');
            const todayStr = `${year}-${month}-${day}`;
            domain = [
                ["dispense_date", ">=", todayStr + " 00:00:00"],
                ["dispense_date", "<=", todayStr + " 23:59:59"],
                ["state", "=", "dispensed"]
            ];
            title = "Today's Completed Dispenses";
        }

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: 'dental.pharmacy.dispense',
            domain: domain,
            views: [[false, 'list'], [false, 'form']],
            target: 'current'
        });
    }

    openInventory() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Pharmacy Stock & Pickings',
            res_model: 'stock.picking',
            views: [[false, 'list'], [false, 'kanban'], [false, 'form']],
            target: 'current'
        });
    }

    openPurchaseOrders() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Requests for Quotation',
            res_model: 'purchase.order',
            views: [[false, 'list'], [false, 'form']],
            target: 'current'
        });
    }

    openRecord(model, id) {
        if (!id) {
            if (model === 'dental.prescription') return this.openFilteredPrescriptions('all');
            if (model === 'product.template') return this.openFilteredMedicines('all');
            if (model === 'stock.lot') return this.openFilteredBatches('all');
            return;
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: model,
            res_id: id,
            views: [[false, 'form']],
            target: 'current'
        });
    }

    newPrescription() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'New Prescription',
            res_model: 'dental.prescription',
            views: [[false, 'form']],
            target: 'current'
        });
    }

    newDispense() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'New Dispense Order',
            res_model: 'dental.pharmacy.dispense',
            views: [[false, 'form']],
            target: 'current'
        });
    }

    newMedicine() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Add Medicine',
            res_model: 'product.template',
            views: [[false, 'form']],
            context: { default_is_medicine: true, default_tracking: 'lot' },
            target: 'current'
        });
    }

    async generateReorderRfqs() {
        try {
            const action = await this.orm.call(
                "dental.pharmacy.dashboard",
                "action_generate_reorder_rfq",
                []
            );
            if (action) {
                this.action.doAction(action);
            }
        } catch (e) {
            console.error("Error generating reorder RFQs:", e);
        }
    }
}

PharmacyDashboard.template = "dental_pharmacy.PharmacyDashboard";
registry.category("actions").add("dental_pharmacy.pharmacy_dashboard", PharmacyDashboard);
