/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, proxy } from "@odoo/owl";

export class ReceptionistDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = proxy({
            loading: true,
            stats: {
                today_appointments: 0,
                waiting_patients: 0,
                checked_in_patients: 0,
                new_patients_today: 0,
                upcoming_follow_ups: 0,
                arrivals: 0,
                needs_registration: 0,
                next_token: "—",
                crm_new_enquiries: 0,
                crm_open_enquiries: 0,
                crm_pending_followups: 0,
                crm_converted_appointments: 0,
            },
            queue_list: [],
            canStartConsultation: false,
            timeline_list: [],
            doctors_availability: [],
            crm_enquiries: [],
            crm_source_breakdown: {},
            unavailable_equipment: [],
            scrapped_equipment: [],
            maintenance_equipment: [],
            showEquipmentAlerts: false,
            enquiryFilter: "all",
            searchQuery: "",
            patientResults: [],
            patientSearching: false,
            showPatientResults: false,
            statusFilter: "all",
            greeting: "Good Morning!",
            currentTimeStr: "",
            currentDateStr: "",
        });

        this.updateClock();

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this.clockInterval = setInterval(() => this.updateClock(), 15000);
            this.handleKeyDown = (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
                    e.preventDefault();
                    const searchInput = document.getElementById("reception-search-input");
                    if (searchInput) searchInput.focus();
                }
            };
            window.addEventListener("keydown", this.handleKeyDown);
            // Close the maintenance alerts popover when clicking outside it
            this.handleOutsideAlertClick = (e) => {
                if (this.state.showEquipmentAlerts && !e.target.closest(".equip-alert-box-wrap")) {
                    this.state.showEquipmentAlerts = false;
                }
            };
            document.addEventListener("mousedown", this.handleOutsideAlertClick);
        });

        onWillUnmount(() => {
            if (this.clockInterval) clearInterval(this.clockInterval);
            if (this.searchTimer) clearTimeout(this.searchTimer);
            if (this.handleKeyDown) window.removeEventListener("keydown", this.handleKeyDown);
            if (this.handleOutsideAlertClick) document.removeEventListener("mousedown", this.handleOutsideAlertClick);
        });
    }

    /** Unavailable equipment not already listed as scrapped or under maintenance. */
    get otherUnavailableEquipment() {
        const known = new Set([
            ...(this.state.scrapped_equipment || []).map((e) => e.id),
            ...(this.state.maintenance_equipment || []).map((e) => e.id),
        ]);
        return (this.state.unavailable_equipment || []).filter((e) => !known.has(e.id));
    }

    get equipmentAlertCount() {
        return (
            (this.state.scrapped_equipment || []).length +
            (this.state.maintenance_equipment || []).length +
            this.otherUnavailableEquipment.length
        );
    }

    toggleEquipmentAlerts() {
        this.state.showEquipmentAlerts = !this.state.showEquipmentAlerts;
    }

    updateClock() {
        const now = new Date();
        const hour = now.getHours();
        if (hour < 12) {
            this.state.greeting = "Good Morning!";
        } else if (hour < 17) {
            this.state.greeting = "Good Afternoon!";
        } else {
            this.state.greeting = "Good Evening!";
        }

        const weekday = now.toLocaleDateString("en-US", { weekday: "short" });
        const day = now.getDate();
        const month = now.toLocaleDateString("en-US", { month: "short" });
        const year = now.getFullYear();
        const timeStr = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

        this.state.currentDateStr = `${weekday}, ${day} ${month} ${year}`;
        this.state.currentTimeStr = timeStr;
    }

    async loadData() {
        this.state.loading = true;
        try {
            const res = await this.orm.call("dental.appointment", "get_reception_dashboard_data", []);
            if (res) {
                if (res.stats) {
                    Object.assign(this.state.stats, res.stats);
                }
                this.state.canStartConsultation = Boolean(res.can_start_consultation);
                this.state.canCheckIn = Boolean(res.can_check_in);
                if (res.queue_list) {
                    this.state.queue_list = res.queue_list;
                }
                if (res.timeline_list) {
                    this.state.timeline_list = res.timeline_list;
                }
                if (res.doctors_availability) {
                    this.state.doctors_availability = res.doctors_availability;
                }
                if (res.crm_enquiries) {
                    this.state.crm_enquiries = res.crm_enquiries;
                }
                if (res.crm_source_breakdown) {
                    this.state.crm_source_breakdown = res.crm_source_breakdown;
                }
                if (res.unavailable_equipment) {
                    this.state.unavailable_equipment = res.unavailable_equipment;
                }
                if (res.scrapped_equipment) {
                    this.state.scrapped_equipment = res.scrapped_equipment;
                }
                if (res.maintenance_equipment) {
                    this.state.maintenance_equipment = res.maintenance_equipment;
                }
            }
        } catch (err) {
            console.error("Failed to load reception dashboard data:", err);
        } finally {
            this.state.loading = false;
        }
    }

    get filteredQueue() {
        let list = this.state.queue_list || [];
        if (this.state.statusFilter !== "all") {
            list = list.filter((item) => item.status_key === this.state.statusFilter);
        }
        if (this.state.searchQuery && this.state.searchQuery.trim()) {
            const query = this.state.searchQuery.toLowerCase().trim();
            list = list.filter(
                (item) =>
                    (item.patient_name && item.patient_name.toLowerCase().includes(query)) ||
                    (item.token && item.token.toLowerCase().includes(query)) ||
                    (item.appointment_info && item.appointment_info.toLowerCase().includes(query)) ||
                    (item.patient_phone && item.patient_phone.includes(query))
            );
        }
        return list;
    }

    get filteredTimeline() {
        let list = this.state.timeline_list || [];
        if (this.state.searchQuery && this.state.searchQuery.trim()) {
            const query = this.state.searchQuery.toLowerCase().trim();
            list = list.filter(
                (item) =>
                    (item.patient_name && item.patient_name.toLowerCase().includes(query)) ||
                    (item.treatment_name && item.treatment_name.toLowerCase().includes(query)) ||
                    (item.status_label && item.status_label.toLowerCase().includes(query))
            );
        }
        return list;
    }

    get filteredEnquiries() {
        let list = this.state.crm_enquiries || [];
        if (this.state.enquiryFilter === "new") {
            list = list.filter((item) => item.conversion_status === "new" || (!item.appointment_id && item.conversion_status === "contacted"));
        } else if (this.state.enquiryFilter === "follow_up") {
            list = list.filter((item) => item.activity_status === "overdue" || item.activity_status === "today" || item.conversion_status === "follow_up");
        } else if (this.state.enquiryFilter === "converted") {
            list = list.filter((item) => item.appointment_id || item.conversion_status === "appointment_scheduled" || item.conversion_status === "appointment_completed");
        }
        if (this.state.searchQuery && this.state.searchQuery.trim()) {
            const query = this.state.searchQuery.toLowerCase().trim();
            list = list.filter(
                (item) =>
                    (item.name && item.name.toLowerCase().includes(query)) ||
                    (item.contact_name && item.contact_name.toLowerCase().includes(query)) ||
                    (item.phone && item.phone.includes(query)) ||
                    (item.email && item.email.toLowerCase().includes(query)) ||
                    (item.treatment_name && item.treatment_name.toLowerCase().includes(query)) ||
                    (item.source_label && item.source_label.toLowerCase().includes(query))
            );
        }
        return list;
    }

    setEnquiryFilter(filterKey) {
        this.state.enquiryFilter = filterKey;
    }

    onSearchChange(ev) {
        this.state.searchQuery = ev.target.value;
        this.state.showPatientResults = true;
        if (this.searchTimer) clearTimeout(this.searchTimer);
        const term = this.state.searchQuery.trim();
        if (term.length < 2) {
            this.state.patientResults = [];
            this.state.patientSearching = false;
            return;
        }
        this.state.patientSearching = true;
        this.searchTimer = setTimeout(() => this.searchPatients(term), 250);
    }

    /** Look up registered patients (name, phone, email, Patient ID) across the whole clinic. */
    async searchPatients(term) {
        try {
            const results = await this.orm.call("dental.appointment", "search_booking_patients", [term], { limit: 8 });
            // Ignore responses for an outdated query
            if (term === this.state.searchQuery.trim()) {
                this.state.patientResults = results || [];
            }
        } catch (e) {
            console.error("Patient search failed:", e);
            this.state.patientResults = [];
        } finally {
            if (term === this.state.searchQuery.trim()) {
                this.state.patientSearching = false;
            }
        }
    }

    onSearchKeyDown(ev) {
        if (ev.key === "Escape") {
            this.state.showPatientResults = false;
            ev.target.blur();
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            const results = this.state.patientResults;
            if (results.length === 1) {
                this.openPatient(results[0].id);
            } else if (this.state.searchQuery.trim()) {
                this.openPatientSearchList();
            }
        }
    }

    onSearchFocus() {
        this.state.showPatientResults = true;
    }

    onSearchBlur() {
        // Delay so a click on a result registers before the dropdown closes
        setTimeout(() => {
            this.state.showPatientResults = false;
        }, 200);
    }

    clearSearch() {
        this.state.searchQuery = "";
        this.state.patientResults = [];
        this.state.patientSearching = false;
    }

    openPatient(patientId) {
        this.state.showPatientResults = false;
        this.openRecord("res.partner", patientId);
    }

    printPatientIdCard(patientId) {
        this.state.showPatientResults = false;
        this.action.doAction("dental_patient.action_report_dental_patient_id_card", {
            additionalContext: { active_ids: [patientId], active_id: patientId },
            resIds: [patientId],
        });
    }

    openPatientSearchList() {
        const term = this.state.searchQuery.trim();
        this.state.showPatientResults = false;
        const domain = [["is_dental_patient", "=", true]];
        if (term) {
            domain.push("|", "|", "|",
                ["name", "ilike", term],
                ["phone", "ilike", term],
                ["email", "ilike", term],
                ["dental_patient_id", "ilike", term]);
        }
        this.action.doAction({
            name: "Patients",
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [[false, "list"], [false, "form"]],
            domain,
            context: { default_is_dental_patient: true },
            target: "current",
        });
    }

    onStatusFilterChange(ev) {
        this.state.statusFilter = ev.target.value;
    }

    async callPatient(appt) {
        try {
            await this.orm.call("dental.appointment", "action_call_patient", [[appt.id]]);
            if (this.notification) {
                this.notification.add(`Patient ${appt.patient_name} (Token ${appt.token}) called to Dental Surgery!`, {
                    title: "Patient Called",
                    type: "info",
                });
            }
            await this.loadData();
        } catch (e) {
            console.error(e);
        }
    }

    async checkInPatient(id) {
        try {
            await this.orm.call("dental.appointment", "action_check_in", [[id]]);
            if (this.notification) {
                this.notification.add("Patient check-in recorded successfully.", {
                    type: "success",
                });
            }
            await this.loadData();
        } catch (e) {
            console.error(e);
        }
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

    async startVisit(id) {
        try {
            const action = await this.orm.call("dental.appointment", "action_start_consultation", [[id]]);
            if (action && typeof action === "object") {
                this.action.doAction(action);
            } else {
                await this.loadData();
            }
        } catch (e) {
            console.error(e);
        }
    }

    openAction(actionXmlId) {
        this.action.doAction(actionXmlId);
    }

    openRecord(model, id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openNewPatient() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [[false, "form"]],
            target: "current",
            context: { default_is_dental_patient: true },
        });
    }

    openBookAppointment() {
        this.action.doAction("dental_appointment.action_dental_appointment_book_flow");
    }

    openWaitingQueue() {
        this.action.doAction("dental_core.action_dental_waiting_queue_board");
    }

    openCheckedInPatients() {
        this.action.doAction("dental_core.action_reception_checked_in", {
            viewType: "list",
        });
    }

    openTodaysAppointments() {
        this.action.doAction("dental_core.action_reception_todays_appointments");
    }

    bookWithDoctor(doctorId) {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        const formattedDate = `${now.getUTCFullYear()}-${pad(now.getUTCMonth() + 1)}-${pad(now.getUTCDate())} ${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}`;
        this.action.doAction({
            name: "Book Appointment",
            type: "ir.actions.act_window",
            res_model: "dental.appointment",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_doctor_id: doctorId,
                default_date_start: formattedDate,
            },
        });
    }

    openDoctorsList() {
        this.action.doAction("dental_core.action_reception_available_doctors");
    }

    openDoctorRecord(docId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            res_id: docId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openNewEnquiry() {
        this.action.doAction({
            name: "New Prospective Patient Enquiry",
            type: "ir.actions.act_window",
            res_model: "crm.lead",
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_type: "opportunity",
                default_source_type: "phone",
            },
        });
    }

    openCrmLead(leadId) {
        this.action.doAction({
            name: "Patient Enquiry",
            type: "ir.actions.act_window",
            res_model: "crm.lead",
            res_id: leadId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openEnquiriesAction() {
        this.action.doAction("dental_core.action_reception_crm_enquiries");
    }

    openEnquiryFollowupsAction() {
        this.action.doAction("dental_core.action_reception_crm_followups");
    }

    openEnquiryReportsAction() {
        this.action.doAction("dental_core.action_reception_crm_reports");
    }

    async bookAppointmentFromLead(leadId) {
        try {
            const action = await this.orm.call("crm.lead", "action_book_appointment", [[leadId]]);
            if (action && typeof action === "object") {
                this.action.doAction(action);
            }
        } catch (e) {
            console.error("Failed to book appointment from lead:", e);
        }
    }

    async scheduleLeadFollowup(leadId) {
        try {
            const action = await this.orm.call("crm.lead", "action_schedule_followup", [[leadId]]);
            if (action && typeof action === "object") {
                this.action.doAction(action);
            }
        } catch (e) {
            console.error("Failed to schedule follow-up:", e);
        }
    }

    async matchPatient(leadId) {
        try {
            const res = await this.orm.call("crm.lead", "action_match_patient", [[leadId]]);
            if (res && res.type === "ir.actions.client") {
                this.action.doAction(res);
            } else if (this.notification) {
                this.notification.add("Patient matched and linked successfully.", { type: "success" });
            }
            await this.loadData();
        } catch (e) {
            console.error("Failed to match patient:", e);
        }
    }

    contactPatient(phone, email) {
        if (phone) {
            window.location.href = "tel:" + phone;
        } else if (email) {
            window.location.href = "mailto:" + email;
        }
    }

    openReportEquipmentIssue() {
        this.action.doAction("dental_core.action_reception_report_equipment_issue", {
            onClose: () => this.loadData(),
        });
    }

    openUnavailableEquipmentList() {
        this.action.doAction("dental_core.action_reception_unavailable_equipment");
    }

    openScrappedEquipmentList() {
        this.action.doAction("dental_core.action_reception_scrapped_equipment");
    }

    openAffectedAppointments() {
        this.action.doAction("dental_core.action_reception_affected_appointments");
    }

    openReassignAppointments() {
        this.action.doAction({
            name: "Reassign Operatory / Appointments",
            type: "ir.actions.act_window",
            res_model: "dental.appointment",
            views: [[false, "calendar"], [false, "list"], [false, "form"]],
            domain: [["has_equipment_conflict", "=", true]],
        });
    }

    async openEndOfDaySummary() {
        try {
            const action = await this.orm.call("dental.payment.summary", "action_open_or_create_today", []);
            if (action && typeof action === "object") {
                if (!action.views && action.view_mode) {
                    action.views = action.view_mode.split(",").map((m) => [false, m.trim()]);
                }
                await this.action.doAction(action);
            }
        } catch (e) {
            console.error("Failed to open End of Day Summary:", e);
            if (this.notification) {
                this.notification.add(e.message || "Failed to open End of Day Summary", { type: "danger" });
            }
        }
    }
}

ReceptionistDashboard.template = "dental_core.ReceptionistDashboard";
registry.category("actions").add("dental_core.receptionist_dashboard", ReceptionistDashboard);
