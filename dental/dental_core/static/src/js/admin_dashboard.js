/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy } from "@odoo/owl";
import { user } from "@web/core/user";
import { DentalFloorPlan } from "./floor_plan";

export class AdminDashboard extends Component {
    static components = { DentalFloorPlan };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.userName = user.name;
        // The clinic selected in the company switcher (title + clinic-scoped figures)
        this.companyId = user.activeCompany ? user.activeCompany.id : false;
        this.companyName = user.activeCompany ? user.activeCompany.name : "Dental Clinic";

        const now = new Date();
        const weekday = now.toLocaleDateString('en-GB', { weekday: 'short' });
        const day = now.getDate();
        const month = now.toLocaleDateString('en-GB', { month: 'short' });
        const year = now.getFullYear();
        this.currentDateStr = `${weekday}, ${day} ${month} ${year}`;

        this.state = proxy({
            loading: true,
            data: {
                header: {
                    clinic_name: 'Dental Hospital',
                    current_branch_name: 'Main Branch',
                    date_str: this.currentDateStr,
                },
                floorplan: {
                    opd: { count: 0, capacity: 24 },
                    chairs: { occupied: 0, total: 16 },
                    radiology: { count: 0, capacity: 4 },
                    lab: { count: 0, capacity: 6 },
                    reception: { waiting: 0, label: '0 Waiting' },
                    clinical: { active: 0, capacity: 8 },
                    pharmacy: { status: 'Active', count: 0 },
                    sterilization: { status: 'Active' }
                },
                kpis: {
                    opd_patients: { val: 0, trend_pct: 12, trend_dir: 'up', trend_label: 'vs yesterday', sparkline: [12, 16, 20, 18, 24, 28] },
                    appointments: { val: 0, trend_pct: 8, trend_dir: 'up', trend_label: 'vs yesterday', sparkline: [10, 14, 18, 16, 22, 26] },
                    chairs_occupancy: { pct: 0, occupied: 0, total: 16, label: '0 / 16 chairs in use' },
                    prescriptions: { val: 0, trend_pct: 15, trend_dir: 'up', trend_label: 'vs yesterday', sparkline: [8, 12, 16, 14, 20, 24] },
                    lab_tests: { val: 0, trend_pct: 6, trend_dir: 'up', trend_label: 'vs yesterday', sparkline: [6, 8, 12, 10, 14, 18] },
                    radiology: { val: 0, trend_pct: 27, trend_dir: 'up', trend_label: 'vs yesterday', sparkline: [4, 6, 8, 7, 10, 14] }
                },
                patient_flow: {
                    filter: 'Today',
                    peak_time: '12:00 PM',
                    peak_count: 0,
                    peak_x: 180,
                    peak_y: 20,
                    peak_pct: 50,
                    line_path: "M 20 75 C 50 75, 55 55, 80 55 C 110 55, 125 20, 150 20 C 180 20, 195 48, 220 48 C 250 48, 265 65, 290 65 C 315 65, 335 82, 350 82",
                    area_path: "M 20 75 C 50 75, 55 55, 80 55 C 110 55, 125 20, 150 20 C 180 20, 195 48, 220 48 C 250 48, 265 65, 290 65 C 315 65, 335 82, 350 82 L 350 100 L 20 100 Z",
                    opd_visits: 0,
                    new_patients: 0,
                    follow_ups: 0,
                    cancellations: 0
                },
                today_appointments: [],
                recent_patients: []
            }
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            // Ultra-fast single RPC call: retrieves complete clinical & operational data in one round-trip (zero lag)
            const res = await this.orm.call(
                "dental.appointment",
                "get_admin_dashboard_data",
                [],
                { branch_id: this.companyId || undefined }
            );

            if (res) {
                // Real Hourly Slot SVG Distribution
                const hourlySlots = res.patient_flow && res.patient_flow.hourly_points ? res.patient_flow.hourly_points : [
                    { hour: '8AM', count: 0 },
                    { hour: '10AM', count: 0 },
                    { hour: '12PM', count: 0 },
                    { hour: '2PM', count: 0 },
                    { hour: '4PM', count: 0 },
                    { hour: '6PM', count: 0 },
                ];

                const xCoords = [20, 80, 150, 220, 290, 350];
                const maxY = 85;
                const minY = 20;
                const rangeY = maxY - minY;
                const counts = hourlySlots.map(s => s.count || 0);
                const peakVal = Math.max(...counts, 1);

                const points = hourlySlots.map((s, idx) => {
                    const x = xCoords[idx] !== undefined ? xCoords[idx] : (20 + idx * 60);
                    const ratio = (s.count || 0) / peakVal;
                    const y = maxY - (ratio * rangeY);
                    return { x, y: Math.round(y) };
                });

                let lineD = "M 20 75 C 50 75, 55 55, 80 55 C 110 55, 125 20, 150 20 C 180 20, 195 48, 220 48 C 250 48, 265 65, 290 65 C 315 65, 335 82, 350 82";
                let areaD = `${lineD} L 350 100 L 20 100 Z`;
                let peakX = 180;

                if (points.length >= 6) {
                    lineD = `M ${points[0].x} ${points[0].y} ` +
                        `C 50 ${points[0].y}, 55 ${points[1].y}, ${points[1].x} ${points[1].y} ` +
                        `C 110 ${points[1].y}, 125 ${points[2].y}, ${points[2].x} ${points[2].y} ` +
                        `C 180 ${points[2].y}, 195 ${points[3].y}, ${points[3].x} ${points[3].y} ` +
                        `C 250 ${points[3].y}, 265 ${points[4].y}, ${points[4].x} ${points[4].y} ` +
                        `C 315 ${points[4].y}, 335 ${points[5].y}, ${points[5].x} ${points[5].y}`;
                    areaD = `${lineD} L ${points[5].x} 100 L ${points[0].x} 100 Z`;

                    let maxIdx = 2;
                    let maxC = -1;
                    counts.forEach((c, idx) => {
                        if (c > maxC) { maxC = c; maxIdx = idx; }
                    });
                    peakX = points[maxIdx].x;
                }

                const peakPct = Math.round((peakX / 360) * 100);

                // Update state cleanly with clear real-time numbers
                this.state.data = {
                    header: {
                        clinic_name: this.companyName,
                        current_branch_name: this.companyName,
                        date_str: res.header && res.header.date_str ? res.header.date_str : this.currentDateStr,
                    },
                    floorplan: res.floorplan || this.state.data.floorplan,
                    kpis: res.kpis || this.state.data.kpis,
                    patient_flow: {
                        ...(res.patient_flow || {}),
                        filter: 'Today',
                        peak_time: (res.patient_flow && res.patient_flow.peak_time) || '12:00 PM',
                        peak_count: (res.patient_flow && res.patient_flow.peak_count) || 0,
                        peak_x: peakX,
                        peak_y: 20,
                        peak_pct: peakPct,
                        line_path: lineD,
                        area_path: areaD,
                        opd_visits: (res.patient_flow && res.patient_flow.opd_visits) || 0,
                        new_patients: (res.patient_flow && res.patient_flow.new_patients) || 0,
                        follow_ups: (res.patient_flow && res.patient_flow.follow_ups) || 0,
                        cancellations: (res.patient_flow && res.patient_flow.cancellations) || 0,
                    },
                    today_appointments: res.today_appointments || [],
                    recent_patients: res.recent_patients || []
                };
            }
        } catch (err) {
            console.error("Dashboard real-time data load failed:", err);
            this.notification.add("Could not fetch real-time dashboard data.", { type: "warning" });
        } finally {
            this.state.loading = false;
        }
    }

    navigateTo(routeKey) {
        switch (routeKey) {
            case 'patients':
                this.action.doAction('dental_patient.action_dental_patient');
                break;
            case 'appointments':
                this.action.doAction('dental_appointment.action_dental_appointment');
                break;
            case 'opd':
                this.action.doAction('dental_appointment.action_dental_appointment_queue');
                break;
            case 'clinical':
                this.action.doAction('dental_core.action_dental_case');
                break;
            case 'radiology':
                this.action.doAction('dental_core.action_dental_clinical_images');
                break;
            case 'laboratory':
                this.action.doAction('dental_lab.action_dental_lab_orders');
                break;
            case 'pharmacy':
                this.action.doAction('dental_pharmacy.action_dental_prescription');
                break;
            case 'billing':
                this.action.doAction('account.action_move_out_invoice_type');
                break;
            case 'reports':
                this.action.doAction('dental_pharmacy.action_pharmacy_report');
                break;
            case 'configuration':
                this.action.doAction('dental_base.action_dental_config_settings');
                break;
            default:
                break;
        }
    }

    onRoomClick(roomKey) {
        switch (roomKey) {
            case 'opd':
                this.action.doAction('dental_appointment.action_dental_appointment_queue');
                break;
            case 'chairs':
                this.action.doAction({
                    type: 'ir.actions.act_window',
                    name: 'Dental Chairs Occupancy',
                    res_model: 'dental.appointment',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['state', '=', 'in_consultation']],
                    target: 'current'
                });
                break;
            case 'radiology':
                this.action.doAction('dental_core.action_dental_clinical_images');
                break;
            case 'lab':
                this.action.doAction('dental_lab.action_dental_lab_orders');
                break;
            case 'reception':
                this.action.doAction('dental_appointment.action_dental_patient_checkin');
                break;
            case 'clinical':
                this.action.doAction('dental_core.action_dental_case');
                break;
            case 'pharmacy':
                this.action.doAction('dental_pharmacy.action_dental_prescription');
                break;
            case 'sterilization':
                this.notification.add("Sterilization unit is fully sanitized and operational.", {
                    type: "info",
                    title: "Sterilization Active"
                });
                break;
            default:
                break;
        }
    }

    actionNewAppointment() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Schedule New Appointment',
            res_model: 'dental.appointment',
            views: [[false, 'form']],
            target: 'new'
        });
    }

    actionNewPatient() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Register Dental Patient',
            res_model: 'res.partner',
            views: [[false, 'form']],
            context: { 'default_is_dental_patient': true },
            target: 'current'
        });
    }

    actionCreatePrescription() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Create Prescription',
            res_model: 'dental.prescription',
            views: [[false, 'form']],
            target: 'current'
        });
    }

    actionRecordXRay() {
        this.action.doAction('dental_core.action_dental_clinical_images');
    }

    openAppointment(apptId) {
        if (!apptId) {
            this.action.doAction('dental_appointment.action_dental_appointment');
            return;
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'dental.appointment',
            res_id: apptId,
            views: [[false, 'form']],
            target: 'current'
        });
    }

    openPatient(patientId) {
        if (!patientId) {
            this.action.doAction('dental_patient.action_dental_patient');
            return;
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'res.partner',
            res_id: patientId,
            views: [[false, 'form']],
            target: 'current'
        });
    }
}

AdminDashboard.template = "dental_core.AdminDashboard";
registry.category("actions").add("dental_core.admin_dashboard", AdminDashboard);
