/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy } from "@odoo/owl";
import { user } from "@web/core/user";

export class DentistDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.userName = user.name || "Doctor";

        this.state = proxy({
            loading: true,
            chartPeriod: "week", // 'week' | 'month' | 'year'
            selectedDoctorId: null,
            doctorInfo: {
                id: false,
                name: user.name || "Doctor",
                display_name: user.name ? `Dr. ${user.name}` : "Doctor",
                greeting: `Good Day, ${user.name || "Doctor"}`,
                subtitle: "Here's what's happening with your schedule today.",
                specialization: "Dental Surgeon",
                avatar_url: `/web/image?model=res.users&field=avatar_128&id=${user.userId}`,
                today_appointments: 0,
                completed_today: 0,
                waiting_today: 0,
            },
            kpiStats: {
                new_patients_today: 0,
                appointments_today: 0,
                treatment_today: 0,
                total_revenue: "0",
                total_patients: "0",
                upcoming_patients: 0,
            },
            overviewCharts: {
                week: [],
                month: [],
                year: [],
            },
            doctors: [],
            upcomingAppointments: [],
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData(doctorId = null) {
        this.state.loading = true;
        try {
            const res = await this.orm.call(
                "dental.appointment",
                "get_dentist_dashboard_data",
                [],
                {
                    doctor_id: doctorId,
                    period: this.state.chartPeriod,
                }
            );

            if (res) {
                if (res.doctor_info) {
                    Object.assign(this.state.doctorInfo, res.doctor_info);
                }
                if (res.kpi_stats) {
                    Object.assign(this.state.kpiStats, res.kpi_stats);
                }
                if (res.overview_charts) {
                    Object.assign(this.state.overviewCharts, res.overview_charts);
                }
                if (res.doctors && res.doctors.length > 0) {
                    this.state.doctors = res.doctors;
                }
                if (res.upcoming_appointments) {
                    this.state.upcomingAppointments = res.upcoming_appointments;
                }
            }
        } catch (e) {
            console.error("Dentist Dashboard data load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    setChartPeriod(period) {
        this.state.chartPeriod = period;
    }

    get currentChartBars() {
        if (this.state.chartPeriod === "month") {
            return this.state.overviewCharts.month || [];
        } else if (this.state.chartPeriod === "year") {
            return this.state.overviewCharts.year || [];
        }
        return this.state.overviewCharts.week || [];
    }

    async selectDoctor(docId) {
        if (this.state.selectedDoctorId === docId) {
            this.state.selectedDoctorId = null;
        } else {
            this.state.selectedDoctorId = docId;
        }
        await this.loadData(this.state.selectedDoctorId);
    }

    openPatientQueue() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Patient Queue",
            res_model: "dental.appointment",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["state", "in", ["checked_in", "in_consultation"]],
                ["doctor_id.user_id", "=", user.userId]
            ],
            target: "current",
        });
    }

    openMyAppointments() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "My Appointments",
            res_model: "dental.appointment",
            views: [[false, "list"], [false, "calendar"], [false, "form"]],
            domain: [["doctor_id.user_id", "=", user.userId]],
            target: "current",
        });
    }

    addAppointment() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Appointment",
            res_model: "dental.appointment",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_doctor_id: this.state.selectedDoctorId || (this.state.doctorInfo ? this.state.doctorInfo.id : false),
            },
        }, {
            onClose: () => this.loadData(this.state.selectedDoctorId),
        });
    }

    generateInvoice() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Customer Invoice",
            res_model: "account.move",
            views: [[false, "form"]],
            context: {
                default_move_type: "out_invoice",
            },
            target: "current",
        });
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
        if (!patientId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: patientId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    viewAllAppointments() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "All Appointments",
            res_model: "dental.appointment",
            views: [[false, "list"], [false, "calendar"], [false, "form"]],
            target: "current",
        });
    }

    viewTotalPatients() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Patients",
            res_model: "res.partner",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_dental_patient", "=", true]],
            target: "current",
        });
    }
}

DentistDashboard.template = "dental_core.DentistDashboard";
registry.category("actions").add("dental_core.dentist_dashboard", DentistDashboard);
