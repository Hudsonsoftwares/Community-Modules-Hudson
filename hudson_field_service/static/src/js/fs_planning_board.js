/** @odoo-module **/

/**
 * Field Service Planning Board — OWL Client Action
 *
 * Renders a Gantt-style scheduling grid:
 *   - Left column  : all technicians (employees) as rows
 *   - Top axis     : hourly time slots (Day mode) or daily slots (Week mode)
 *   - Cards        : field service orders positioned by date_planned + duration_planned
 *
 * Access:
 *   - Managers (group_field_service_manager) → see ALL employees + ALL orders
 *   - Normal users  → redirected to standard calendar filtered to their own orders
 *     (handled server-side: the menu item for this board is manager-only)
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";

// ─── Palette for avatar initials background ──────────────────────────────────
const AVATAR_COLORS = [
    "#714b67", "#0d6efd", "#198754", "#dc3545", "#fd7e14",
    "#6610f2", "#0dcaf0", "#d63384", "#20c997", "#ffc107",
];

function pickColor(id) {
    return AVATAR_COLORS[id % AVATAR_COLORS.length];
}

function initials(name) {
    if (!name) return "?";
    const parts = name.trim().split(/\s+/);
    if (parts.length === 1) return parts[0][0].toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// ─── Date helpers ────────────────────────────────────────────────────────────

/** Return a Date at midnight in LOCAL time for the given Date */
function startOfDay(d) {
    const r = new Date(d);
    r.setHours(0, 0, 0, 0);
    return r;
}

/** Add N whole days */
function addDays(d, n) {
    const r = new Date(d);
    r.setDate(r.getDate() + n);
    return r;
}

/** Monday of the week containing d */
function startOfWeek(d) {
    const r = startOfDay(d);
    const dow = r.getDay(); // 0=Sun
    const diff = dow === 0 ? -6 : 1 - dow;
    r.setDate(r.getDate() + diff);
    return r;
}

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

/** Format: "Mon, Jul 14" */
function fmtDate(d) {
    return `${DAY_NAMES[d.getDay()]}, ${MONTH_NAMES[d.getMonth()]} ${d.getDate()}`;
}

/** Format: "Jul 14 – Jul 20, 2025" */
function fmtWeekRange(start, end) {
    const s = `${MONTH_NAMES[start.getMonth()]} ${start.getDate()}`;
    const e = `${MONTH_NAMES[end.getMonth()]} ${end.getDate()}, ${end.getFullYear()}`;
    return `${s} – ${e}`;
}

function isToday(d) {
    const t = new Date();
    return d.getFullYear() === t.getFullYear()
        && d.getMonth() === t.getMonth()
        && d.getDate() === t.getDate();
}

function isWeekend(d) {
    const dow = d.getDay();
    return dow === 0 || dow === 6;
}

// ─── Day mode: hours 7 → 20 ──────────────────────────────────────────────────
const DAY_HOUR_START = 7;
const DAY_HOUR_END = 20; // exclusive

// ─── Main component ──────────────────────────────────────────────────────────

export class FsPlanningBoard extends Component {
    static template = "hudson_field_service.FsPlanningBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.gridWrapper = useRef("gridWrapper");

        this.state = useState({
            mode: "week",          // "day" | "week"
            anchorDate: startOfDay(new Date()),
            loading: true,
            employees: [],         // [{id, employeeId, name, avatar, initials, color}]
            orders: [],            // [{id, name, title, employeeId, datePlanned, durationHours, state, partner}]
            slots: [],             // [{key, label, date, hour, cssClass}]
            dateLabel: "",
            dragState: null,       // { empId: null, startSlot: null, currentSlot: null }
        });

        this._refreshTimer = null;

        onMounted(async () => {
            await this._loadData();
            this._startRefreshTimer();
        });

        onWillUnmount(() => {
            if (this._refreshTimer) clearInterval(this._refreshTimer);
        });
    }

    // ── Timer: refresh every 5 min ───────────────────────────────────────────
    _startRefreshTimer() {
        this._refreshTimer = setInterval(() => this._loadData(), 5 * 60 * 1000);
    }

    // ── Slot computation ─────────────────────────────────────────────────────

    _computeSlots() {
        const slots = [];
        if (this.state.mode === "day") {
            const d = this.state.anchorDate;
            for (let h = DAY_HOUR_START; h < DAY_HOUR_END; h++) {
                const cls = [];
                if (isToday(d)) cls.push("is-today");
                if (isWeekend(d)) cls.push("is-weekend");
                slots.push({
                    key: `h${h}`,
                    label: `${h}:00`,
                    date: d,
                    hour: h,
                    cssClass: cls.join(" "),
                });
            }
            this.state.dateLabel = fmtDate(d) + ", " + d.getFullYear();
        } else {
            // week: Mon–Sun
            const weekStart = startOfWeek(this.state.anchorDate);
            for (let i = 0; i < 7; i++) {
                const d = addDays(weekStart, i);
                const cls = [];
                if (isToday(d)) cls.push("is-today");
                if (isWeekend(d)) cls.push("is-weekend");
                slots.push({
                    key: `d${i}`,
                    label: `${DAY_NAMES[d.getDay()]} ${d.getDate()}`,
                    date: d,
                    hour: null,
                    cssClass: cls.join(" "),
                });
            }
            const weekEnd = addDays(weekStart, 6);
            this.state.dateLabel = fmtWeekRange(weekStart, weekEnd);
        }
        this.state.slots = slots;
    }

    // ── Grid CSS template columns ────────────────────────────────────────────

    get gridTemplateColumns() {
        const n = this.state.slots.length;
        // Use minmax with 1fr so the columns expand to fill any remaining blank space on the right
        return `var(--fs-board-employee-col-w) repeat(${n}, minmax(var(--fs-board-hour-col-w), 1fr))`;
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    async _loadData() {
        this.state.loading = true;
        this._computeSlots();

        try {
            // Determine date range for order fetch
            let dateFrom, dateTo;
            if (this.state.mode === "day") {
                dateFrom = new Date(this.state.anchorDate);
                dateTo = addDays(dateFrom, 1);
            } else {
                dateFrom = startOfWeek(this.state.anchorDate);
                dateTo = addDays(dateFrom, 7);
            }

            const [empRaw, ordersRaw] = await Promise.all([
                this._fetchEmployees(),
                this._fetchOrders(dateFrom, dateTo),
            ]);

            this.state.employees = empRaw;
            this.state.orders = ordersRaw;
        } catch (e) {
            console.error("Planning board load error:", e);
            this.notification.add(
                "Failed to load planning board data: " + (e.message || e),
                { type: "danger" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    async _fetchEmployees() {
        // Fetch active employees that have a linked user account
        const records = await this.orm.searchRead(
            "hr.employee",
            [["active", "=", true]],
            ["id", "name", "image_128"],
            { limit: 100, order: "name asc" }
        );

        const employees = records.map((r) => ({
            id: r.id,
            employeeId: r.id,
            name: r.name,
            avatar: r.image_128
                ? `/web/image/hr.employee/${r.id}/image_128`
                : null,
            initials: initials(r.name),
            color: pickColor(r.id),
        }));

        // Always add an "Unassigned" row at the end
        employees.push({
            id: 0,
            employeeId: null,
            name: "Unassigned",
            avatar: null,
            initials: "?",
            color: "#adb5bd",
        });

        return employees;
    }

    async _fetchOrders(dateFrom, dateTo) {
        // Fetch orders in the date range (include orders without a date too for unassigned row)
        const domain = [
            ["state", "not in", ["cancelled"]],
            "|",
            ["date_planned", "=", false],
            "&",
            ["date_planned", ">=", this._toOdooDatetime(dateFrom)],
            ["date_planned", "<", this._toOdooDatetime(dateTo)],
        ];

        const records = await this.orm.searchRead(
            "field.service.order",
            domain,
            ["id", "name", "title", "employee_id", "extra_employee_ids", "date_planned", "duration_planned", "state", "partner_id", "is_published"],
            { limit: 500, order: "date_planned asc" }
        );

        return records.map((r) => ({
            id: r.id,
            name: r.name,
            title: r.title || "",
            employeeId: r.employee_id ? r.employee_id[0] : null,
            extraEmployeeIds: r.extra_employee_ids || [],
            datePlanned: r.date_planned ? new Date(r.date_planned) : null,
            durationHours: r.duration_planned || 1,
            state: r.state,
            partner: r.partner_id ? r.partner_id[1] : "",
            isPublished: r.is_published || false,
        }));
    }

    _toOdooDatetime(d) {
        // Odoo expects UTC datetimes as strings "YYYY-MM-DD HH:MM:SS"
        const pad = (n) => String(n).padStart(2, "0");
        return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
    }

    // ── Slot ↔ order matching ────────────────────────────────────────────────

    getOrdersForSlot(employeeId, slot) {
        return this.state.orders.filter((order) => {
            // Employee matching
            const empMatch = order.employeeId === employeeId || order.extraEmployeeIds.includes(employeeId);
            if (!empMatch) return false;

            if (!order.datePlanned) {
                // Unscheduled orders: show in first slot of unassigned or first slot of employee
                return slot === this.state.slots[0];
            }

            if (this.state.mode === "day") {
                // Match by hour
                const orderHour = order.datePlanned.getHours();
                return orderHour === slot.hour;
            } else {
                // Match by day
                const orderDay = startOfDay(order.datePlanned);
                const slotDay = startOfDay(slot.date);
                return orderDay.getTime() === slotDay.getTime();
            }
        });
    }

    getCardStyle(order, slot) {
        if (this.state.mode === "day") {
            // Position card based on minutes within the hour and span duration
            const startMin = order.datePlanned ? order.datePlanned.getMinutes() : 0;
            const slotWidthPx = 80; // matches --fs-board-hour-col-w
            const left = (startMin / 60) * slotWidthPx;
            const totalHours = order.durationHours || 1;
            // How many slot-widths does this order span?
            const width = Math.max(totalHours * slotWidthPx - left - 4, 30);
            return `left: ${left + 2}px; width: ${width}px;`;
        } else {
            // Week mode: fill the cell (minus padding)
            return "left: 4px; right: 4px;";
        }
    }

    // ── Navigation ───────────────────────────────────────────────────────────

    async prevPeriod() {
        if (this.state.mode === "day") {
            this.state.anchorDate = addDays(this.state.anchorDate, -1);
        } else {
            this.state.anchorDate = addDays(this.state.anchorDate, -7);
        }
        await this._loadData();
    }

    async nextPeriod() {
        if (this.state.mode === "day") {
            this.state.anchorDate = addDays(this.state.anchorDate, 1);
        } else {
            this.state.anchorDate = addDays(this.state.anchorDate, 7);
        }
        await this._loadData();
    }

    async goToday() {
        this.state.anchorDate = startOfDay(new Date());
        await this._loadData();
    }

    async setMode(mode) {
        this.state.mode = mode;
        await this._loadData();
    }

    // ── Interactions ─────────────────────────────────────────────────────────

    openOrder(ev, orderId) {
        ev.stopPropagation();
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "field.service.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get hasUnpublishedDrafts() {
        return this.state.orders.some(o => !o.isPublished);
    }

    async publishDrafts() {
        const draftIds = this.state.orders.filter(o => !o.isPublished).map(o => o.id);
        if (draftIds.length === 0) return;

        try {
            await this.orm.call("field.service.order", "action_publish_order", [draftIds]);
            this.notification.add("Drafts published successfully!", { type: "success" });
            await this._loadData();
        } catch (e) {
            this.notification.add("Failed to publish drafts: " + e.message, { type: "danger" });
        }
    }

    // ── Drag Selection ───────────────────────────────────────────────────────

    onDragStart(ev, emp, slot) {
        if (ev.button !== 0) return; // Only left click
        this.state.dragState = {
            empId: emp.id,
            startSlot: slot,
            currentSlot: slot
        };
    }

    onDragEnter(ev, emp, slot) {
        if (this.state.dragState && this.state.dragState.empId === emp.id) {
            this.state.dragState.currentSlot = slot;
        }
    }

    onDragEnd(ev, emp, slot) {
        if (!this.state.dragState) return;
        
        const state = this.state.dragState;
        this.state.dragState = null;

        // Ensure we dropped on the same employee
        if (state.empId !== emp.id) return;

        // Calculate slot indices
        const startIndex = this.state.slots.indexOf(state.startSlot);
        const endIndex = this.state.slots.indexOf(slot);
        
        if (startIndex === -1 || endIndex === -1) return;

        const minIdx = Math.min(startIndex, endIndex);
        const maxIdx = Math.max(startIndex, endIndex);
        const slotCount = maxIdx - minIdx + 1;

        const firstSlot = this.state.slots[minIdx];
        const defaultDatetime = this._slotToDatetime(firstSlot);

        const context = {};
        if (emp.employeeId) {
            context.default_employee_id = emp.employeeId;
        }
        if (defaultDatetime) {
            context.default_date_planned = this._toOdooDatetime(defaultDatetime);
        }

        // Set duration based on number of selected slots
        if (this.state.mode === "day") {
            context.default_duration_planned = slotCount;
        } else {
            // Week mode: each slot is 1 day, assume 8 hours per day
            context.default_duration_planned = slotCount * 8;
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "field.service.order",
            views: [[false, "form"]],
            target: "new",
            context,
        });
    }

    isSlotSelected(emp, slot) {
        const ds = this.state.dragState;
        if (!ds || ds.empId !== emp.id) return false;

        const sIdx = this.state.slots.indexOf(ds.startSlot);
        const cIdx = this.state.slots.indexOf(ds.currentSlot);
        const myIdx = this.state.slots.indexOf(slot);

        if (sIdx === -1 || cIdx === -1 || myIdx === -1) return false;

        const minIdx = Math.min(sIdx, cIdx);
        const maxIdx = Math.max(sIdx, cIdx);

        return myIdx >= minIdx && myIdx <= maxIdx;
    }

    onClickSlot(ev, emp, slot) {
        // Handled by onDragEnd now to support multi-select.
        // We keep this empty just in case any leftover references exist, 
        // though the XML was updated to use mouse events instead.
    }

    openNewOrder() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "field.service.order",
            views: [[false, "form"]],
            target: "new",
        });
    }

    _slotToDatetime(slot) {
        if (this.state.mode === "day") {
            const d = new Date(slot.date);
            d.setHours(slot.hour, 0, 0, 0);
            return d;
        } else {
            return new Date(slot.date);
        }
    }
}

registry.category("actions").add("field_service_planning_board", FsPlanningBoard);
