/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, proxy } from "@odoo/owl";
import { user } from "@web/core/user";

const AUTO_REFRESH_MS = 60000;

const PERIOD_CAPTIONS = {
    day: "today",
    week: "this week",
    month: "this month",
    year: "this year",
};

export class DentistDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.periods = [
            { key: "day", label: "Day" },
            { key: "week", label: "Week" },
            { key: "month", label: "Month" },
            { key: "year", label: "Year" },
        ];
        this.scheduleFilters = [
            { key: "all", label: "All" },
            { key: "upcoming", label: "Upcoming" },
            { key: "active", label: "In Clinic" },
            { key: "done", label: "Completed" },
            { key: "cancelled", label: "Cancelled" },
        ];

        this.state = proxy({
            loading: true,
            refreshing: false,
            busyId: null,
            chartPeriod: "day", // 'day' | 'week' | 'month' | 'year'
            scheduleFilter: "all",
            hasDoctor: false,
            dateLabel: "",
            refreshedAt: "",
            doctorInfo: {
                id: false,
                name: user.name || "Doctor",
                display_name: user.name ? `Dr. ${user.name}` : "Doctor",
                greeting: "",
                specialization: "",
                branch_name: "",
                avatar_url: `/web/image?model=res.users&field=avatar_128&id=${user.userId}`,
            },
            kpiStats: {
                appointments_today: 0,
                remaining_today: 0,
                waiting: 0,
                longest_wait_mins: 0,
                completed_today: 0,
                completion_pct: 0,
                cancelled_today: 0,
                new_patients_today: 0,
                followups_due: 0,
                patients_month: 0,
                treatment_value_month: "0",
            },
            currentPatient: false,
            waitingQueue: [],
            todaySchedule: [],
            overviewCharts: { day: [], week: [], month: [], year: [] },
        });

        onWillStart(async () => {
            await this.loadData();
        });
        onMounted(() => {
            this.refreshTimer = setInterval(() => this.loadData({ silent: true }), AUTO_REFRESH_MS);
        });
        onWillUnmount(() => {
            clearInterval(this.refreshTimer);
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async loadData({ silent = false } = {}) {
        if (silent) {
            this.state.refreshing = true;
        } else {
            this.state.loading = true;
        }
        try {
            // Always the current user's own dentist profile (resolved server-side)
            const res = await this.orm.call("dental.appointment", "get_dentist_dashboard_data", []);
            if (res) {
                this.state.hasDoctor = Boolean(res.has_doctor);
                this.state.dateLabel = res.date_label || "";
                this.state.refreshedAt = res.refreshed_at;
                Object.assign(this.state.doctorInfo, res.doctor_info || {});
                Object.assign(this.state.kpiStats, res.kpi_stats || {});
                Object.assign(this.state.overviewCharts, res.overview_charts || {});
                this.state.currentPatient = res.current_patient || false;
                this.state.waitingQueue = res.waiting_queue || [];
                this.state.todaySchedule = res.today_schedule || [];
            }
        } catch (e) {
            console.error("Dentist Dashboard data load error:", e);
            if (!silent) {
                this.notification.add("Could not load dashboard data.", { type: "danger" });
            }
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    refresh() {
        return this.loadData({ silent: true });
    }

    // ------------------------------------------------------------------
    // Chart
    // ------------------------------------------------------------------

    setChartPeriod(period) {
        this.state.chartPeriod = period;
    }

    get currentChartBars() {
        return this.state.overviewCharts[this.state.chartPeriod] || [];
    }

    get chartTotal() {
        return this.currentChartBars.reduce((sum, bar) => sum + bar.count, 0);
    }

    get chartCaption() {
        return PERIOD_CAPTIONS[this.state.chartPeriod];
    }

    /** Rounded axis maximum (1/2/5 x 10^n steps) so gridlines show real values. */
    get chartScale() {
        const max = Math.max(0, ...this.currentChartBars.map((b) => b.count));
        const rawStep = Math.max(1, max / 4);
        const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
        const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep);
        return { max: step * 4, ticks: [4, 3, 2, 1, 0].map((i) => i * step) };
    }

    barHeight(count) {
        return count ? Math.max(3, (count / this.chartScale.max) * 100) : 0;
    }

    // ------------------------------------------------------------------
    // Schedule
    // ------------------------------------------------------------------

    setScheduleFilter(key) {
        this.state.scheduleFilter = key;
    }

    scheduleMatches(appt, key) {
        switch (key) {
            case "upcoming":
                return ["pending", "confirmed"].includes(appt.state);
            case "active":
                return ["checked_in", "in_consultation"].includes(appt.state);
            case "done":
                return appt.state === "completed";
            case "cancelled":
                return ["cancelled", "no_show"].includes(appt.state);
            default:
                return true;
        }
    }

    scheduleCount(key) {
        return this.state.todaySchedule.filter((a) => this.scheduleMatches(a, key)).length;
    }

    get filteredSchedule() {
        return this.state.todaySchedule.filter((a) => this.scheduleMatches(a, this.state.scheduleFilter));
    }

    formatMinutes(mins) {
        if (mins < 60) {
            return `${mins} min`;
        }
        return `${Math.floor(mins / 60)}h ${mins % 60}m`;
    }

    // ------------------------------------------------------------------
    // Clinical workflow actions
    // ------------------------------------------------------------------

    async _runAppointmentMethod(appointmentId, method) {
        if (this.state.busyId) {
            return;
        }
        this.state.busyId = appointmentId;
        try {
            const result = await this.orm.call("dental.appointment", method, [[appointmentId]]);
            if (result && typeof result === "object" && result.type) {
                await this.action.doAction(result);
            } else {
                await this.loadData({ silent: true });
            }
            return true;
        } finally {
            this.state.busyId = null;
        }
    }

    /** Call the patient into the chair and open their clinical case. */
    startConsultation(appt) {
        return this._runAppointmentMethod(appt.id, "action_start_consultation");
    }

    callNextPatient() {
        if (this.state.waitingQueue.length) {
            return this.startConsultation(this.state.waitingQueue[0]);
        }
    }

    openCase(appt) {
        return this._runAppointmentMethod(appt.id, "action_open_clinical_case");
    }

    async finishConsultation(appt) {
        const done = await this._runAppointmentMethod(appt.id, "action_dashboard_finish");
        if (done) {
            this.notification.add(`Visit completed for ${appt.patient_name}.`, { type: "success" });
        }
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    get doctorDomain() {
        return [["doctor_id", "=", this.state.doctorInfo.id || 0]];
    }

    openPatientQueue() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Patient Queue",
            res_model: "dental.appointment",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["checked_in", "in_consultation"]], ...this.doctorDomain],
            target: "current",
        });
    }

    openMyAppointments() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Schedule",
            res_model: "dental.appointment",
            views: [[false, "calendar"], [false, "list"], [false, "form"]],
            domain: this.doctorDomain,
            target: "current",
        });
    }

    openTodayAppointments() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Today's Appointments",
            res_model: "dental.appointment",
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", this.state.todaySchedule.map((a) => a.id)]],
            target: "current",
        });
    }

    openClinicalCases() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Clinical Consultations",
            res_model: "dental.case",
            views: [[false, "list"], [false, "form"]],
            domain: this.doctorDomain,
            target: "current",
        });
    }

    openFollowUps() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Follow-ups Due",
            res_model: "dental.follow.up",
            views: [[false, "list"], [false, "form"]],
            domain: [...this.doctorDomain, ["state", "=", "pending"]],
            target: "current",
        });
    }

    openPatientRecords() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Patients",
            res_model: "res.partner",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_dental_patient", "=", true]],
            target: "current",
        });
    }

    addAppointment() {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: "New Appointment",
                res_model: "dental.appointment",
                views: [[false, "form"]],
                target: "new",
                context: { default_doctor_id: this.state.doctorInfo.id || false },
            },
            { onClose: () => this.loadData({ silent: true }) }
        );
    }

    openAppointment(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dental.appointment",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPatient(patientId) {
        if (!patientId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: patientId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

DentistDashboard.template = "dental_core.DentistDashboard";
registry.category("actions").add("dental_core.dentist_dashboard", DentistDashboard);
