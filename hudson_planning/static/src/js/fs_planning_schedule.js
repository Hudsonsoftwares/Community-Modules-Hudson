/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

// Helpers
function startOfDay(d) {
    const r = new Date(d);
    r.setHours(0, 0, 0, 0);
    return r;
}
function addDays(d, n) {
    const r = new Date(d);
    r.setDate(r.getDate() + n);
    return r;
}
function startOfWeek(d) {
    const r = startOfDay(d);
    const dow = r.getDay(); // 0=Sun
    const diff = dow === 0 ? -6 : 1 - dow;
    r.setDate(r.getDate() + diff);
    return r;
}
function isToday(d) {
    const t = new Date();
    return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
}
function isWeekend(d) {
    const dow = d.getDay();
    return dow === 0 || dow === 6;
}

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export class FsPlanningSchedule extends Component {
    static template = "hudson_planning.FsPlanningSchedule";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: [Number, String], optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        
        const myPlanningContext = this.props.action && this.props.action.context && this.props.action.context.default_my_planning;

        this.state = useState({
            mode: "week",
            anchorDate: startOfDay(new Date()),
            customStartDate: new Date().toISOString().split('T')[0],
            customEndDate: new Date().toISOString().split('T')[0],
            loading: true,
            resources: [], // {id, name, checked}
            slots: [],     // slot records
            columns: [],   // grid columns
            dateLabel: "",
            monthLabel: "",
            searchQuery: "",
            filterMyPlanning: !!myPlanningContext,
        });

        // Bind event handlers used in inline arrow functions
        this.toggleMyPlanning = this.toggleMyPlanning.bind(this);
        this.onCellClick = this.onCellClick.bind(this);
        this.openSlot = this.openSlot.bind(this);
        this.setMode = this.setMode.bind(this);

        onMounted(async () => {
            await this._loadData();
        });
    }

    get filteredResources() {
        let res = this.state.resources.filter(r => r.checked);
        if (this.state.searchQuery) {
            const q = this.state.searchQuery.toLowerCase();
            res = res.filter(r => r.name.toLowerCase().includes(q));
        }
        return res;
    }

    getSlots(resourceId, col) {
        // Return slots for this resource on this specific date/month
        return this.state.slots.filter(s => {
            const sd = new Date(s.date_start.replace(' ', 'T') + 'Z');
            if (s.resource_id[0] !== resourceId) return false;
            
            if (col.isMonth) {
                return sd.getFullYear() === col.date.getFullYear() &&
                       sd.getMonth() === col.date.getMonth();
            } else {
                return sd.getFullYear() === col.date.getFullYear() &&
                       sd.getMonth() === col.date.getMonth() &&
                       sd.getDate() === col.date.getDate();
            }
        });
    }

    formatTime(dateStr) {
        if (!dateStr) return "";
        const d = new Date(dateStr.replace(' ', 'T') + 'Z');
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    async _loadData() {
        this.state.loading = true;
        
        // Setup columns based on mode
        const cols = [];
        let dateFromStr, dateToStr;
        
        if (this.state.mode === "day") {
            const d = startOfDay(this.state.anchorDate);
            cols.push({
                key: 'd0',
                date: d,
                labelTop: DAY_NAMES[d.getDay()],
                labelBottom: String(d.getDate()),
                cssClass: isToday(d) ? 'is-today' : ''
            });
            this.state.columns = cols;
            this.state.dateLabel = `${MONTH_NAMES[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
            this.state.monthLabel = `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
            
            const pad = (n) => String(n).padStart(2, "0");
            const toUtcStr = (dateObj) => `${dateObj.getUTCFullYear()}-${pad(dateObj.getUTCMonth()+1)}-${pad(dateObj.getUTCDate())} 00:00:00`;
            dateFromStr = toUtcStr(d);
            dateToStr = toUtcStr(addDays(d, 1));
        } else if (this.state.mode === "month") {
            const y = this.state.anchorDate.getFullYear();
            const m = this.state.anchorDate.getMonth();
            const daysInMonth = new Date(y, m + 1, 0).getDate();
            const mStart = new Date(y, m, 1);
            for (let i = 0; i < daysInMonth; i++) {
                const d = addDays(mStart, i);
                cols.push({
                    key: `d${i}`,
                    date: d,
                    labelTop: DAY_NAMES[d.getDay()],
                    labelBottom: String(d.getDate()),
                    cssClass: `${isToday(d) ? 'is-today' : ''} ${isWeekend(d) ? 'is-weekend' : ''}`.trim()
                });
            }
            this.state.columns = cols;
            this.state.dateLabel = `${MONTH_NAMES[m]} ${y}`;
            this.state.monthLabel = this.state.dateLabel;
            
            const pad = (n) => String(n).padStart(2, "0");
            const toUtcStr = (dateObj) => `${dateObj.getUTCFullYear()}-${pad(dateObj.getUTCMonth()+1)}-${pad(dateObj.getUTCDate())} 00:00:00`;
            dateFromStr = toUtcStr(mStart);
            dateToStr = toUtcStr(addDays(new Date(y, m, daysInMonth), 1));
            
        } else if (this.state.mode === "quarter") {
            const y = this.state.anchorDate.getFullYear();
            const m = this.state.anchorDate.getMonth();
            const qMonth = Math.floor(m / 3) * 3;
            const qStart = new Date(y, qMonth, 1);
            const qEnd = new Date(y, qMonth + 3, 0);
            const daysInQuarter = Math.round((qEnd - qStart) / (1000*60*60*24)) + 1;
            for (let i = 0; i < daysInQuarter; i++) {
                const d = addDays(qStart, i);
                cols.push({
                    key: `d${i}`,
                    date: d,
                    labelTop: DAY_NAMES[d.getDay()],
                    labelBottom: String(d.getDate()),
                    cssClass: `${isToday(d) ? 'is-today' : ''} ${isWeekend(d) ? 'is-weekend' : ''}`.trim()
                });
            }
            this.state.columns = cols;
            this.state.dateLabel = `Q${Math.floor(m / 3) + 1} ${y}`;
            this.state.monthLabel = this.state.dateLabel;
            
            const pad = (n) => String(n).padStart(2, "0");
            const toUtcStr = (dateObj) => `${dateObj.getUTCFullYear()}-${pad(dateObj.getUTCMonth()+1)}-${pad(dateObj.getUTCDate())} 00:00:00`;
            dateFromStr = toUtcStr(qStart);
            dateToStr = toUtcStr(addDays(qEnd, 1));
            
        } else if (this.state.mode === "year") {
            const y = this.state.anchorDate.getFullYear();
            const yStart = new Date(y, 0, 1);
            const yEnd = new Date(y + 1, 0, 0); // last day of year
            const daysInYear = Math.round((yEnd - yStart) / (1000*60*60*24)) + 1;
            for (let i = 0; i < daysInYear; i++) {
                const d = addDays(yStart, i);
                cols.push({
                    key: `d${i}`,
                    date: d,
                    labelTop: DAY_NAMES[d.getDay()],
                    labelBottom: String(d.getDate()),
                    cssClass: `${isToday(d) ? 'is-today' : ''} ${isWeekend(d) ? 'is-weekend' : ''}`.trim()
                });
            }
            this.state.columns = cols;
            this.state.dateLabel = `${y}`;
            this.state.monthLabel = `${y}`;
            
            const pad = (n) => String(n).padStart(2, "0");
            const toUtcStr = (dateObj) => `${dateObj.getUTCFullYear()}-${pad(dateObj.getUTCMonth()+1)}-${pad(dateObj.getUTCDate())} 00:00:00`;
            dateFromStr = toUtcStr(new Date(y, 0, 1));
            dateToStr = toUtcStr(new Date(y + 1, 0, 1));
            
        } else if (this.state.mode === "custom") {
            const dStart = startOfDay(new Date(this.state.customStartDate));
            let dEnd = startOfDay(new Date(this.state.customEndDate));
            if (dEnd < dStart) dEnd = dStart;
            
            const days = Math.min(Math.round((dEnd - dStart) / (1000*60*60*24)) + 1, 90);
            for (let i = 0; i < days; i++) {
                const d = addDays(dStart, i);
                cols.push({
                    key: `d${i}`,
                    date: d,
                    labelTop: DAY_NAMES[d.getDay()],
                    labelBottom: String(d.getDate()),
                    cssClass: `${isToday(d) ? 'is-today' : ''} ${isWeekend(d) ? 'is-weekend' : ''}`.trim()
                });
            }
            this.state.columns = cols;
            this.state.dateLabel = `${dStart.toLocaleDateString()} - ${dEnd.toLocaleDateString()}`;
            this.state.monthLabel = this.state.dateLabel;
            
            const pad = (n) => String(n).padStart(2, "0");
            const toUtcStr = (dateObj) => `${dateObj.getUTCFullYear()}-${pad(dateObj.getUTCMonth()+1)}-${pad(dateObj.getUTCDate())} 00:00:00`;
            dateFromStr = toUtcStr(dStart);
            dateToStr = toUtcStr(addDays(addDays(dStart, days - 1), 1));
            
        } else {
            const weekStart = startOfWeek(this.state.anchorDate);
            for (let i = 0; i < 7; i++) {
                const d = addDays(weekStart, i);
                cols.push({
                    key: `d${i}`,
                    date: d,
                    labelTop: DAY_NAMES[d.getDay()],
                    labelBottom: String(d.getDate()),
                    cssClass: `${isToday(d) ? 'is-today' : ''} ${isWeekend(d) ? 'is-weekend' : ''}`.trim()
                });
            }
            this.state.columns = cols;
            const weekEnd = addDays(weekStart, 6);
            this.state.dateLabel = `${MONTH_NAMES[weekStart.getMonth()]} ${weekStart.getDate()} – ${MONTH_NAMES[weekEnd.getMonth()]} ${weekEnd.getDate()}, ${weekEnd.getFullYear()}`;
            this.state.monthLabel = `${MONTH_NAMES[weekStart.getMonth()]} ${weekStart.getFullYear()}`;
            
            const pad = (n) => String(n).padStart(2, "0");
            const toUtcStr = (dateObj) => `${dateObj.getUTCFullYear()}-${pad(dateObj.getUTCMonth()+1)}-${pad(dateObj.getUTCDate())} 00:00:00`;
            dateFromStr = toUtcStr(weekStart);
            dateToStr = toUtcStr(addDays(weekEnd, 1));
        }

        try {
            // Fetch resources (employees that have planning roles)
            let empDomain = [["active", "=", true]];
            if (this.state.filterMyPlanning) {
                empDomain.push(["user_id", "=", this.env.uid]);
            }
            const employees = await this.orm.searchRead("hr.employee", empDomain, ["id", "name"]);
            
            // Map to state, preserving checkbox state if already loaded
            const currentChecked = new Set(this.state.resources.filter(r => r.checked).map(r => r.id));
            this.state.resources = employees.map(e => ({
                id: e.id,
                name: e.name,
                checked: this.state.resources.length === 0 || currentChecked.has(e.id)
            }));

            const slotDomain = [
                ["date_start", ">=", dateFromStr],
                ["date_start", "<", dateToStr]
            ];
            
            const slotRecords = await this.orm.searchRead(
                "fs.planning.slot",
                slotDomain,
                ["id", "name", "resource_id", "role_id", "date_start", "date_end", "state", "partner_id", "attendance_status", "allocated_hours"]
            );

            this.state.slots = slotRecords.map(s => ({
                ...s,
                role_name: s.role_id ? s.role_id[1] : "",
                partner_name: s.partner_id ? s.partner_id[1] : "",
                color: s.role_id ? s.role_id[0] : 0,
            }));

            // Calculate total allocated hours per resource
            const hoursByResource = {};
            for (const slot of this.state.slots) {
                if (slot.resource_id) {
                    const resId = slot.resource_id[0];
                    hoursByResource[resId] = (hoursByResource[resId] || 0) + (slot.allocated_hours || 0);
                }
            }
            
            // Assign to resources
            for (const res of this.state.resources) {
                res.allocatedHours = hoursByResource[res.id] || 0;
            }

        } catch (e) {
            console.error(e);
            this.notification.add("Failed to load planning data", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async toggleMyPlanning(val) {
        this.state.filterMyPlanning = val;
        this.state.resources = []; // Reset resources to reload based on filter
        await this._loadData();
    }

    async setMode(mode) {
        this.state.mode = mode;
        await this._loadData();
    }

    async onPrevPeriod() {
        if (this.state.mode === "day") {
            this.state.anchorDate = addDays(this.state.anchorDate, -1);
        } else if (this.state.mode === "week") {
            this.state.anchorDate = addDays(this.state.anchorDate, -7);
        } else if (this.state.mode === "month") {
            this.state.anchorDate = new Date(this.state.anchorDate.getFullYear(), this.state.anchorDate.getMonth() - 1, 1);
        } else if (this.state.mode === "quarter") {
            this.state.anchorDate = new Date(this.state.anchorDate.getFullYear(), this.state.anchorDate.getMonth() - 3, 1);
        } else if (this.state.mode === "year") {
            this.state.anchorDate = new Date(this.state.anchorDate.getFullYear() - 1, 0, 1);
        } else if (this.state.mode === "custom") {
            return; // No prev period for custom range
        }
        await this._loadData();
    }

    async onNextPeriod() {
        if (this.state.mode === "day") {
            this.state.anchorDate = addDays(this.state.anchorDate, 1);
        } else if (this.state.mode === "week") {
            this.state.anchorDate = addDays(this.state.anchorDate, 7);
        } else if (this.state.mode === "month") {
            this.state.anchorDate = new Date(this.state.anchorDate.getFullYear(), this.state.anchorDate.getMonth() + 1, 1);
        } else if (this.state.mode === "quarter") {
            this.state.anchorDate = new Date(this.state.anchorDate.getFullYear(), this.state.anchorDate.getMonth() + 3, 1);
        } else if (this.state.mode === "year") {
            this.state.anchorDate = new Date(this.state.anchorDate.getFullYear() + 1, 0, 1);
        } else if (this.state.mode === "custom") {
            return; // No next period for custom range
        }
        await this._loadData();
    }

    async onApplyCustomDate() {
        this.state.mode = "custom";
        await this._loadData();
        
        // Try to close dropdown by clicking body
        document.body.click();
    }

    async onToday() {
        this.state.anchorDate = startOfDay(new Date());
        await this._loadData();
    }

    async onSearch(ev) {
        if (ev.key === "Enter") {
            // Already handled by getter filteredResources via v-model bound
        }
    }

    async onCellClick(resourceId, col) {
        // Quick create dialog via action
        const action = {
            type: "ir.actions.act_window",
            res_model: "fs.planning.slot",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_resource_id: resourceId,
                default_date_start: this._localToUtcStr(col.date, 8), // default 8am
                default_date_end: this._localToUtcStr(col.date, 12),  // default 12pm
            },
        };
        this.action.doAction(action, {
            onClose: () => this._loadData(),
        });
    }
    
    _localToUtcStr(date, hour) {
        const d = new Date(date);
        d.setHours(hour, 0, 0, 0);
        const pad = (n) => String(n).padStart(2, "0");
        return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
    }

    async openSlot(slotId) {
        const action = {
            type: "ir.actions.act_window",
            res_model: "fs.planning.slot",
            res_id: slotId,
            views: [[false, "form"]],
            target: "new",
        };
        this.action.doAction(action, {
            onClose: () => this._loadData(),
        });
    }

    async onPublish() {
        // Publish all draft slots in current view
        const draftIds = this.state.slots.filter(s => s.state === 'draft').map(s => s.id);
        if (draftIds.length > 0) {
            await this.orm.call("fs.planning.slot", "action_publish", [draftIds]);
            this.notification.add(`${draftIds.length} slots published`, { type: "success" });
            await this._loadData();
        } else {
            this.notification.add("No draft slots to publish in the current view", { type: "warning" });
        }
    }
    
    async onCopyPrevious() {
        this.notification.add("Copy previous week feature is under construction", { type: "info" });
    }
    
    async onAutoPlan() {
        const action = {
            type: "ir.actions.act_window",
            res_model: "fs.auto.plan.wizard",
            views: [[false, "form"]],
            target: "new",
        };
        this.action.doAction(action, {
            onClose: () => this._loadData(),
        });
    }
    
    async onPrint() {
        window.print();
    }
}

registry.category("actions").add("hudson_planning.fs_planning_schedule", FsPlanningSchedule);
