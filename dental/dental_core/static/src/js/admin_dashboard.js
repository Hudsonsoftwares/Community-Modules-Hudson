/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy } from "@odoo/owl";
import { user } from "@web/core/user";

export class AdminDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.userName = user.name;
        
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
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');
            const todayStr = `${year}-${month}-${day}`;
            const utcStart = `${todayStr} 00:00:00`;
            const utcEnd = `${todayStr} 23:59:59`;

            // 1. Appointments Today (Pure Real-time from database)
            const appts = await this.orm.searchRead(
                "dental.appointment",
                [
                    ["date_start", ">=", utcStart],
                    ["date_start", "<=", utcEnd]
                ],
                ["name", "patient_id", "doctor_id", "treatment_id", "date_start", "state", "reason"],
                { order: "date_start ASC" }
            );

            const totalApptsCount = appts.length;
            const inConsultation = appts.filter(a => a.state === 'in_consultation').length;
            const checkedIn = appts.filter(a => a.state === 'checked_in').length;
            const completed = appts.filter(a => a.state === 'completed').length;
            const cancelled = appts.filter(a => a.state === 'cancelled').length;
            const followups = appts.filter(a => (a.reason || '').toLowerCase().includes('follow')).length;

            // 2. New Patients Today & Recent Patients
            const newPatientsCount = await this.orm.searchCount("res.partner", [
                ["is_dental_patient", "=", true],
                ["create_date", ">=", utcStart],
                ["create_date", "<=", utcEnd]
            ]);

            const recentPartners = await this.orm.searchRead(
                "res.partner",
                [["is_dental_patient", "=", true]],
                ["name", "email", "phone", "create_date"],
                { order: "create_date DESC, id DESC", limit: 5 }
            );

            // 3. Clinical Cases
            let activeClinicalCases = 0;
            try {
                activeClinicalCases = await this.orm.searchCount("dental.case", [
                    ["state", "in", ["open", "under_treatment"]]
                ]);
            } catch (ignore) {}

            // 4. Prescriptions
            let prescriptionsCount = 0;
            try {
                prescriptionsCount = await this.orm.searchCount("dental.prescription", [
                    "|",
                    ["prescription_date", "=", todayStr],
                    ["create_date", ">=", utcStart]
                ]);
            } catch (ignore) {}

            // 5. Lab Orders
            let labOrdersCount = 0;
            try {
                labOrdersCount = await this.orm.searchCount("dental.lab.order", [
                    "|",
                    ["order_date", "=", todayStr],
                    ["create_date", ">=", utcStart]
                ]);
            } catch (ignore) {}

            // 6. Radiology
            let xrayCount = 0;
            try {
                xrayCount = await this.orm.searchCount("ir.attachment", [
                    ["res_model", "in", ["dental.case", "dental.clinical.examination", "dental.treatment.plan", "res.partner"]]
                ]);
            } catch (ignore) {}

            // 7. Company Branch
            let branchName = "Main Branch";
            try {
                const companies = await this.orm.searchRead("res.company", [], ["name"], { limit: 1 });
                if (companies.length > 0) {
                    branchName = companies[0].name;
                }
            } catch (ignore) {}

            // Format Real Today's Appointments List
            const statusMap = {
                'checked_in': { label: 'Checked In', class: 'badge-checked-in' },
                'waiting': { label: 'Waiting', class: 'badge-waiting' },
                'in_consultation': { label: 'Ongoing', class: 'badge-ongoing' },
                'confirmed': { label: 'Scheduled', class: 'badge-scheduled' },
                'pending': { label: 'Scheduled', class: 'badge-scheduled' },
                'completed': { label: 'Completed', class: 'badge-completed' },
                'cancelled': { label: 'Cancelled', class: 'badge-cancelled' },
            };

            const formattedAppts = appts.map(a => {
                let timeStr = "09:00";
                if (a.date_start) {
                    const dt = new Date(a.date_start.replace(' ', 'T') + "Z");
                    timeStr = dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
                }
                const stInfo = statusMap[a.state] || { label: 'Scheduled', class: 'badge-scheduled' };
                let tName = 'Consultation';
                if (a.treatment_id && a.treatment_id[1]) {
                    tName = typeof a.treatment_id[1] === 'object' ? (a.treatment_id[1].en_US || 'Consultation') : a.treatment_id[1];
                } else if (a.reason) {
                    tName = a.reason;
                }
                return {
                    id: a.id,
                    time: timeStr,
                    patient_id: a.patient_id ? a.patient_id[0] : null,
                    patient_name: a.patient_id ? a.patient_id[1] : 'Patient',
                    treatment: tName,
                    state: a.state,
                    status_label: stInfo.label,
                    status_class: stInfo.class
                };
            });

            // Format Real Recent Patients
            const formattedPatients = recentPartners.map(p => {
                let timeStr = "Today";
                if (p.create_date) {
                    const dt = new Date(p.create_date.replace(' ', 'T') + "Z");
                    timeStr = dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
                }
                return {
                    id: p.id,
                    name: p.name,
                    treatment: 'OPD Patient',
                    time: timeStr,
                    badge: 'OPD'
                };
            });

            // Chairs Occupancy
            const totalChairs = 16;
            const chairsOccupancyPct = totalChairs > 0 ? Math.round((inConsultation / totalChairs) * 100) : 0;

            // Real Hourly Slot distribution
            const hourlySlots = [
                { label: '8AM', start: 8, end: 9, count: 0, x: 20 },
                { label: '10AM', start: 10, end: 11, count: 0, x: 80 },
                { label: '12PM', start: 12, end: 13, count: 0, x: 150 },
                { label: '2PM', start: 14, end: 15, count: 0, x: 220 },
                { label: '4PM', start: 16, end: 17, count: 0, x: 290 },
                { label: '6PM', start: 18, end: 20, count: 0, x: 350 },
            ];

            for (const a of appts) {
                if (a.date_start) {
                    const dt = new Date(a.date_start.replace(' ', 'T') + "Z");
                    const hr = dt.getHours();
                    for (const slot of hourlySlots) {
                        if (hr >= slot.start && hr <= slot.end) {
                            slot.count++;
                            break;
                        }
                    }
                }
            }

            let maxCount = 0;
            let peakSlot = hourlySlots[2];
            for (const slot of hourlySlots) {
                if (slot.count > maxCount) {
                    maxCount = slot.count;
                    peakSlot = slot;
                }
            }
            if (maxCount === 0) {
                maxCount = totalApptsCount > 0 ? totalApptsCount : 1;
            }

            const maxY = 85;
            const minY = 20;
            const rangeY = maxY - minY;
            const peakVal = Math.max(...hourlySlots.map(s => s.count), 1);
            
            const points = hourlySlots.map(s => {
                const ratio = s.count / peakVal;
                const y = maxY - (ratio * rangeY);
                return { x: s.x, y: Math.round(y) };
            });

            const lineD = `M ${points[0].x} ${points[0].y} ` +
                          `C 50 ${points[0].y}, 55 ${points[1].y}, ${points[1].x} ${points[1].y} ` +
                          `C 110 ${points[1].y}, 125 ${points[2].y}, ${points[2].x} ${points[2].y} ` +
                          `C 180 ${points[2].y}, 195 ${points[3].y}, ${points[3].x} ${points[3].y} ` +
                          `C 250 ${points[3].y}, 265 ${points[4].y}, ${points[4].x} ${points[4].y} ` +
                          `C 315 ${points[4].y}, 335 ${points[5].y}, ${points[5].x} ${points[5].y}`;
            const areaD = `${lineD} L ${points[5].x} 100 L ${points[0].x} 100 Z`;

            const peakX = peakSlot.x;
            const peakPct = Math.round((peakX / 360) * 100);

            // Real comparison vs yesterday for trend percentages
            const yesterdayDate = new Date(now);
            yesterdayDate.setDate(yesterdayDate.getDate() - 1);
            const yYear = yesterdayDate.getFullYear();
            const yMonth = String(yesterdayDate.getMonth() + 1).padStart(2, '0');
            const yDay = String(yesterdayDate.getDate()).padStart(2, '0');
            const yStart = `${yYear}-${yMonth}-${yDay} 00:00:00`;
            const yEnd = `${yYear}-${yMonth}-${yDay} 23:59:59`;

            let yesterdayApptsCount = 0;
            try {
                yesterdayApptsCount = await this.orm.searchCount("dental.appointment", [
                    ["date_start", ">=", yStart],
                    ["date_start", "<=", yEnd]
                ]);
            } catch (ignore) {}

            const calcTrend = (curr, prev) => {
                if (prev > 0) {
                    const pct = Math.round(Math.abs((curr - prev) / prev) * 100);
                    const dir = curr >= prev ? 'up' : 'down';
                    return { pct, dir };
                }
                return { pct: 0, dir: 'up' };
            };

            const apptTrend = calcTrend(totalApptsCount, yesterdayApptsCount);

            // Real 6-day sparkline from actual database counts
            const sparklineAppts = [];
            for (let i = 5; i >= 0; i--) {
                const d = new Date(now);
                d.setDate(d.getDate() - i);
                const dYear = d.getFullYear();
                const dMonth = String(d.getMonth() + 1).padStart(2, '0');
                const dDay = String(d.getDate()).padStart(2, '0');
                const dStart = `${dYear}-${dMonth}-${dDay} 00:00:00`;
                const dEnd = `${dYear}-${dMonth}-${dDay} 23:59:59`;
                try {
                    const c = await this.orm.searchCount("dental.appointment", [
                        ["date_start", ">=", dStart],
                        ["date_start", "<=", dEnd]
                    ]);
                    sparklineAppts.push(c);
                } catch (ignore) {
                    sparklineAppts.push(0);
                }
            }

            this.state.data = {
                header: {
                    clinic_name: branchName,
                    current_branch_name: branchName,
                    date_str: this.currentDateStr,
                },
                floorplan: {
                    opd: { count: totalApptsCount, capacity: 24 },
                    chairs: { occupied: inConsultation, total: totalChairs },
                    radiology: { count: xrayCount, capacity: 4 },
                    lab: { count: labOrdersCount, capacity: 6 },
                    reception: { waiting: checkedIn, label: `${checkedIn} Waiting` },
                    clinical: { active: activeClinicalCases, capacity: 8 },
                    pharmacy: { status: 'Active', count: prescriptionsCount },
                    sterilization: { status: 'Active' }
                },
                kpis: {
                    opd_patients: { 
                        val: totalApptsCount, 
                        trend_pct: apptTrend.pct, 
                        trend_dir: apptTrend.dir, 
                        trend_label: 'vs yesterday', 
                        sparkline: sparklineAppts 
                    },
                    appointments: { 
                        val: totalApptsCount, 
                        trend_pct: apptTrend.pct, 
                        trend_dir: apptTrend.dir, 
                        trend_label: 'vs yesterday', 
                        sparkline: sparklineAppts 
                    },
                    chairs_occupancy: { 
                        pct: chairsOccupancyPct, 
                        occupied: inConsultation, 
                        total: totalChairs, 
                        label: `${inConsultation} / ${totalChairs} chairs in use` 
                    },
                    prescriptions: { 
                        val: prescriptionsCount, 
                        trend_pct: 0, 
                        trend_dir: 'up', 
                        trend_label: 'vs yesterday', 
                        sparkline: [prescriptionsCount] 
                    },
                    lab_tests: { 
                        val: labOrdersCount, 
                        trend_pct: 0, 
                        trend_dir: 'up', 
                        trend_label: 'vs yesterday', 
                        sparkline: [labOrdersCount] 
                    },
                    radiology: { 
                        val: xrayCount, 
                        trend_pct: 0, 
                        trend_dir: 'up', 
                        trend_label: 'vs yesterday', 
                        sparkline: [xrayCount] 
                    }
                },
                patient_flow: {
                    filter: 'Today',
                    peak_time: peakSlot.label === '12PM' ? '12:00 PM' : peakSlot.label,
                    peak_count: maxCount,
                    peak_x: peakX,
                    peak_y: 20,
                    peak_pct: peakPct,
                    line_path: lineD,
                    area_path: areaD,
                    opd_visits: totalApptsCount,
                    new_patients: newPatientsCount,
                    follow_ups: followups,
                    cancellations: cancelled
                },
                today_appointments: formattedAppts,
                recent_patients: formattedPatients
            };

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
                this.action.doAction('dental_lab.action_dental_lab_order');
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
                this.action.doAction('dental_lab.action_dental_lab_order');
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
