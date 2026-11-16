/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Component, onWillStart, proxy } from "@odoo/owl";

const TYPE_ORDER = ["membership", "family", "preventive", "maintenance", "installment"];

export class DentalSubscriptionDashboard extends Component {
    static template = "dental_subscription.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.companyId = user.activeCompany ? user.activeCompany.id : false;
        this.state = proxy({ loading: true, error: false, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "sale.order", "get_dental_subscription_dashboard", [],
                { branch_id: this.companyId || undefined },
            );
        } catch (e) {
            this.state.error = (e && e.data && e.data.message) || (e && e.message) || "Could not load the dashboard.";
        } finally {
            this.state.loading = false;
        }
    }

    // ---------- formatting ----------
    money(value) {
        const cur = (this.state.data && this.state.data.currency) || { symbol: "", position: "before", digits: 2 };
        const abs = Math.abs(value || 0);
        let num;
        if (abs >= 1e6) {
            num = (value / 1e6).toFixed(1) + "M";
        } else if (abs >= 1e4) {
            num = (value / 1e3).toFixed(1) + "k";
        } else {
            num = (value || 0).toLocaleString(undefined, {
                minimumFractionDigits: cur.digits, maximumFractionDigits: cur.digits,
            });
        }
        return cur.position === "after" ? `${num} ${cur.symbol}` : `${cur.symbol} ${num}`;
    }

    count(value) {
        return (value || 0).toLocaleString();
    }

    // ---------- chart geometry (plain SVG, one axis per chart) ----------
    get byType() {
        const rows = (this.state.data && this.state.data.by_type) || [];
        const sorted = [...rows].sort((a, b) => TYPE_ORDER.indexOf(a.key) - TYPE_ORDER.indexOf(b.key));
        const max = Math.max(1, ...sorted.map((r) => r.count));
        return sorted.map((r) => ({ ...r, pct: (r.count / max) * 100 }));
    }

    get trend() {
        const rows = (this.state.data && this.state.data.trend) || [];
        const max = Math.max(1, ...rows.flatMap((r) => [r.new, r.churn]));
        const maxInv = Math.max(1, ...rows.map((r) => r.invoiced));
        const plotH = 120;
        const slot = 300 / Math.max(rows.length, 1);
        const barW = Math.min(16, slot / 3);
        return {
            rows: rows.map((r, i) => {
                const x0 = 30 + i * slot + slot / 2;
                const hNew = (r.new / max) * plotH;
                const hChurn = (r.churn / max) * plotH;
                const hInv = (r.invoiced / maxInv) * plotH;
                return {
                    ...r,
                    xLabel: x0,
                    newX: x0 - barW - 1, newY: 10 + plotH - hNew, newH: Math.max(hNew, r.new ? 2 : 0),
                    churnX: x0 + 1, churnY: 10 + plotH - hChurn, churnH: Math.max(hChurn, r.churn ? 2 : 0),
                    invX: x0 - barW, invY: 10 + plotH - hInv, invH: Math.max(hInv, r.invoiced ? 2 : 0),
                };
            }),
            barW,
            invBarW: barW * 2,
            max,
            maxInv,
            baseline: 10 + plotH,
        };
    }

    // ---------- navigation ----------
    openOrders(domain, name) {
        if (!domain) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "sale.order",
            domain,
            views: [[false, "list"], [false, "form"]],
            context: { create: false },
        });
    }

    openInvoices(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "account.move",
            domain,
            views: [[false, "list"], [false, "form"]],
            context: { create: false },
        });
    }

    openUsage() {
        this.action.doAction("dental_subscription.action_dental_benefit_usage");
    }

    openOrder(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("dental_subscription.dashboard", DentalSubscriptionDashboard);
