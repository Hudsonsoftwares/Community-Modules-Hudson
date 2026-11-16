/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onWillUnmount, proxy, markup } from "@odoo/owl";
import { user } from "@web/core/user";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

const SEARCH_DELAY_MS = 250;

// YYYY-MM-DD in the browser's local time (toISOString() would give the UTC date)
function toLocalDateStr(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseDateStr(s) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
}

export class BookAppointmentFlow extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");

        const todayStr = toLocalDateStr(new Date());

        this.state = proxy({
            step: 1, // 1: Patient, 2: Type, 3: Doctor, 4: Slots, 5: Confirm, 6: Success
            // Staff book for registered patients only; new patients are registered first (popup)
            patientType: "returning",
            searchIdentifier: "",
            searchingPatient: false,
            searchMessage: "",
            suggestions: [],
            showSuggestions: false,
            activeIndex: -1,
            foundPatient: null,

            // Step 2: Services (appointment types + catalog treatments)
            types: [],
            serviceSearch: "",
            selectedServiceKey: null,
            selectedTypeId: null,
            selectedTreatmentId: null,
            selectedTypeName: "",
            selectedTypeDuration: 30,

            // Step 3: Doctors
            doctors: [],
            doctorSearch: "",
            selectedDoctorId: null, // null = Any Specialist
            selectedDoctorName: "Any Specialist",
            selectedDoctorSpec: "Dental Specialist",

            // Step 4: Schedule & Slots (times are clinic-local, computed by the server)
            todayDate: todayStr,
            selectedDate: todayStr,
            dateLabel: "",
            slots: [],
            slotPeriods: [],
            slotMessage: "",
            nextAvailableDate: false,
            nextAvailableLabel: "",
            loadingSlots: false,
            selectedSlotTime: null,
            selectedSlotLabel: "",
            selectedSlotEndLabel: "",

            // Step 5: Patient Details Form
            firstName: "",
            lastName: "",
            phone: "",
            email: "",
            dob: "",
            gender: "male",
            zipCode: "",
            notes: "",
            priority: "1",
            hasInsurance: "no",
            insuranceInfo: "",

            // Booking status
            submitting: false,
            errorMessage: "",
            createdAppointment: null,
            isStaff: true, // Will check via user service
            company: {
                name: "Dental Clinic",
                phone: "",
                address: ""
            }
        });

        onWillUnmount(() => clearTimeout(this._searchTimer));

        onWillStart(async () => {
            try {
                this.state.isStaff = await user.hasGroup("base.group_user");
            } catch (err) {
                this.state.isStaff = false;
            }
            await this.loadInitialData();

            // Check if patient was pre-passed from Patient Form or Context
            const actionContext = this.props?.action?.context || {};
            const patientId = actionContext.default_patient_id || 
                              (actionContext.active_model === "res.partner" ? actionContext.active_id : null);
            if (patientId) {
                try {
                    const patients = await this.orm.searchRead(
                        "res.partner",
                        [["id", "=", Number(patientId)]],
                        ["id", "name", "phone", "email", "dental_patient_id", "gender", "date_of_birth"],
                        { limit: 1 }
                    );
                    if (patients && patients.length > 0) {
                        const p = patients[0];
                        this.state.foundPatient = p;
                        this.state.patientType = "returning";
                        const parts = (p.name || "").trim().split(" ");
                        this.state.firstName = parts[0] || "";
                        this.state.lastName = parts.slice(1).join(" ") || "";
                        this.state.phone = p.phone || "";
                        this.state.email = p.email || "";
                        this.state.dob = p.date_of_birth || "";
                        this.state.gender = p.gender || "male";
                        this.state.step = 2; // Automatically proceed to Procedure / Doctor selection
                    }
                } catch (e) {
                    console.warn("Could not load pre-filled patient in booking flow:", e);
                }
            }
        });
    }

    async loadInitialData() {
        try {
            // 1. Load every bookable service for the current branch
            const res = await this.orm.call("dental.appointment", "get_bookable_services", [], {
                branch_id: user.activeCompany?.id || false,
            });
            this.state.types = (res && res.services) || [];
            if (this.state.types.length > 0) {
                this.applyService(this.state.types[0]);
            }

            // 2. Load dentists of the current branch (or shared across branches)
            const branchId = user.activeCompany?.id;
            const doctors = await this.orm.searchRead(
                "hr.employee",
                [["is_dentist", "=", true], ["active", "=", true],
                 ...(branchId ? ["|", ["company_id", "=", false], ["company_id", "=", branchId]] : [])],
                ["id", "name", "job_title", "work_email", "work_phone"],
                { order: "id asc" }
            );
            this.state.doctors = doctors || [];

            // 3. Load active company info
            const companies = await this.orm.searchRead(
                "res.company",
                [["id", "=", user.companyId || 1]],
                ["name", "phone", "street", "city"],
                { limit: 1 }
            );
            if (companies && companies.length > 0) {
                const c = companies[0];
                this.state.company = {
                    name: c.name || "Dental Clinic",
                    phone: c.phone || "",
                    address: [c.street, c.city].filter(Boolean).join(", ")
                };
            }
        } catch (e) {
            console.error("Error loading appointment initial data:", e);
        }
    }

    get steps() {
        return [
            { number: 1, label: "Patient", icon: "fa-user" },
            { number: 2, label: "Service", icon: "fa-stethoscope" },
            { number: 3, label: "Dentist", icon: "fa-user-md" },
            { number: 4, label: "Schedule", icon: "fa-calendar-check-o" },
            { number: 5, label: "Confirm", icon: "fa-check-square-o" },
        ];
    }

    canGoToStep(targetStep) {
        if (targetStep === 1) return true;
        if (targetStep === 2) return Boolean(this.state.foundPatient);
        if (targetStep === 3) return Boolean(this.state.foundPatient && this.state.selectedServiceKey);
        if (targetStep === 4) return Boolean(this.state.foundPatient && this.state.selectedServiceKey);
        if (targetStep === 5) return Boolean(this.state.foundPatient && this.state.selectedServiceKey && this.state.selectedSlotTime);
        return false;
    }

    goToStep(stepNumber) {
        if (stepNumber > this.state.step && !this.canGoToStep(stepNumber)) {
            return;
        }
        this.state.errorMessage = "";
        if (stepNumber === 4) {
            this.fetchSlots();
        }
        this.state.step = stepNumber;
    }

    get filteredServices() {
        const q = (this.state.serviceSearch || "").toLowerCase().trim();
        if (!q) return this.state.types;
        return this.state.types.filter(t => 
            (t.name && t.name.toLowerCase().includes(q)) || 
            (t.description && t.description.toLowerCase().includes(q))
        );
    }

    clearServiceSearch() {
        this.state.serviceSearch = "";
    }

    get filteredDoctors() {
        const q = (this.state.doctorSearch || "").toLowerCase().trim();
        if (!q) return this.state.doctors;
        return this.state.doctors.filter(d => 
            (d.name && d.name.toLowerCase().includes(q)) || 
            (d.job_title && d.job_title.toLowerCase().includes(q))
        );
    }

    clearDoctorSearch() {
        this.state.doctorSearch = "";
    }

    // ------------------------------------------------------------------
    // Step 1: find the registered patient (name, phone, email or Patient ID)
    // ------------------------------------------------------------------

    onSearchInput(ev) {
        this.state.searchIdentifier = ev.target.value;
        clearTimeout(this._searchTimer);
        const term = this.state.searchIdentifier.trim();
        if (term.length < 2) {
            this.state.suggestions = [];
            this.state.showSuggestions = false;
            this.state.searchMessage = "";
            return;
        }
        this._searchTimer = setTimeout(() => this.runSearch(term), SEARCH_DELAY_MS);
    }

    async runSearch(term = (this.state.searchIdentifier || "").trim()) {
        clearTimeout(this._searchTimer);
        if (term.length < 2) {
            this.state.searchMessage = "Type at least 2 characters of the name, phone, email or Patient ID.";
            return;
        }
        const requestId = (this._searchRequest = (this._searchRequest || 0) + 1);
        this.state.searchingPatient = true;
        try {
            const results = await this.orm.call("dental.appointment", "search_booking_patients", [], {
                term,
                limit: 8,
            });
            if (requestId !== this._searchRequest) {
                return; // a newer search is running (fast typing)
            }
            this.state.suggestions = results || [];
            this.state.activeIndex = this.state.suggestions.length ? 0 : -1;
            this.state.showSuggestions = true;
            this.state.searchMessage = this.state.suggestions.length
                ? ""
                : `No patient found for "${term}". Check the spelling or register a new patient.`;
        } catch (err) {
            this.state.searchMessage = "Search failed: " + (err.message || err);
        } finally {
            if (requestId === this._searchRequest) {
                this.state.searchingPatient = false;
            }
        }
    }

    onSearchKeydown(ev) {
        const list = this.state.suggestions;
        if (ev.key === "ArrowDown" && list.length) {
            ev.preventDefault();
            this.state.showSuggestions = true;
            this.state.activeIndex = (this.state.activeIndex + 1) % list.length;
        } else if (ev.key === "ArrowUp" && list.length) {
            ev.preventDefault();
            this.state.activeIndex = (this.state.activeIndex - 1 + list.length) % list.length;
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            // Enter picks the highlighted suggestion; it never skips the explicit choice
            if (this.state.showSuggestions && list[this.state.activeIndex]) {
                this.selectPatient(list[this.state.activeIndex]);
            } else {
                this.runSearch();
            }
        } else if (ev.key === "Escape") {
            this.state.showSuggestions = false;
        }
    }

    onSearchBlur() {
        // Let a click on a suggestion land first
        setTimeout(() => (this.state.showSuggestions = false), 150);
    }

    onSearchFocus() {
        if (this.state.suggestions.length && !this.state.foundPatient) {
            this.state.showSuggestions = true;
        }
    }

    onSuggestionMouseDown(ev, p) {
        ev.preventDefault(); // keep focus so the blur handler does not close the list first
        this.selectPatient(p);
    }

    onRegisterLinkClick(ev) {
        ev.preventDefault();
        this.registerNewPatient();
    }

    selectPatient(p) {
        this.state.foundPatient = p;
        this.state.patientType = "returning";
        this.state.showSuggestions = false;
        this.state.searchMessage = "";
        this.state.searchIdentifier = p.name || "";
        const parts = (p.name || "").trim().split(" ");
        this.state.firstName = parts[0] || "";
        this.state.lastName = parts.slice(1).join(" ") || "";
        this.state.phone = p.phone || "";
        this.state.email = p.email || "";
        this.state.dob = p.date_of_birth || "";
        this.state.gender = p.gender || "male";
    }

    clearPatient() {
        this.state.foundPatient = null;
        this.state.searchIdentifier = "";
        this.state.suggestions = [];
        this.state.showSuggestions = false;
        this.state.searchMessage = "";
    }

    continueWithPatient() {
        if (!this.state.foundPatient) {
            this.state.searchMessage = "Select the patient from the search results first.";
            return;
        }
        this.goToStep(2);
    }

    registerNewPatient() {
        // Patient registration form in a popup: the booking in progress is kept and the new patient is selected
        this.dialog.add(FormViewDialog, {
            resModel: "res.partner",
            title: "Register New Patient",
            context: {
                default_is_dental_patient: true,
                default_customer_rank: 1,
                default_name: /\d/.test(this.state.searchIdentifier) ? "" : this.state.searchIdentifier.trim(),
            },
            onRecordSaved: async (record) => {
                const patient = await this.orm.call("dental.appointment", "get_booking_patient", [record.resId]);
                if (patient) {
                    this.selectPatient(patient);
                    this.notification.add(`${patient.name} registered and selected.`, { type: "success" });
                }
            },
        });
    }

    // Procedure Type Icon & Class Helpers
    getTypeClass(type) {
        const name = (type && type.name ? type.name : "").toLowerCase();
        if (name.includes("emergency") || name.includes("pain") || name.includes("broken")) return "emergency";
        if (name.includes("child") || name.includes("pediatric") || name.includes("kid")) return "child";
        if (name.includes("clean") || name.includes("polish") || name.includes("scaling")) return "cleaning";
        if (name.includes("cosmetic") || name.includes("whiten") || name.includes("smile")) return "cosmetic";
        if (name.includes("root") || name.includes("canal") || name.includes("endo")) return "rootcanal";
        if (name.includes("adult") || name.includes("exam") || name.includes("check")) return "adult";
        return "regular";
    }

    getTypeIconMarkup(type) {
        const name = (type && type.name ? type.name : "").toLowerCase();

        // 1. Emergency Consultation: Tooth with urgent medical cross badge & red accent
        if (name.includes("emergency") || name.includes("pain") || name.includes("broken")) {
            return markup(`
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                    <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#fef2f2" stroke="#ef4444" stroke-width="2.8"/>
                    <rect x="22" y="14" width="4" height="12" rx="2" fill="#ef4444"/>
                    <rect x="18" y="18" width="12" height="4" rx="2" fill="#ef4444"/>
                </svg>
            `);
        }

        // 2. Child Examination: Pediatric happy smiling tooth with warm amber star
        if (name.includes("child") || name.includes("pediatric") || name.includes("kid")) {
            return markup(`
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                    <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#fffbeb" stroke="#f59e0b" stroke-width="2.8"/>
                    <circle cx="19" cy="18" r="2.2" fill="#d97706"/>
                    <circle cx="29" cy="18" r="2.2" fill="#d97706"/>
                    <path d="M19 24c1.8 2.6 8.2 2.6 10 0" stroke="#d97706" stroke-width="2.5" stroke-linecap="round"/>
                    <path d="M36 8l1.2 2.6 2.8 1.2-2.8 1.2-1.2 2.6-1.2-2.6-2.8-1.2 2.8-1.2 1.2-2.6z" fill="#f59e0b"/>
                </svg>
            `);
        }

        // 3. Teeth Cleaning & Polish: Sparkle shine bubbles with mint green accent
        if (name.includes("clean") || name.includes("polish") || name.includes("scaling")) {
            return markup(`
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                    <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#ecfdf5" stroke="#10b981" stroke-width="2.8"/>
                    <path d="M20 15l1.8 3 3 1.8-3 1.8-1.8 3-1.8-3-3-1.8 3-1.8 1.8-3z" fill="#10b981"/>
                    <path d="M28 22l1.2 2 2 1.2-2 1.2-1.2 2-1.2-2-2-1.2 2-1.2 1.2-2z" fill="#34d399"/>
                </svg>
            `);
        }

        // 4. Cosmetic & Whitening: Radiant diamond sparkle with violet / gold accent
        if (name.includes("cosmetic") || name.includes("whiten") || name.includes("smile")) {
            return markup(`
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                    <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#f5f3ff" stroke="#8b5cf6" stroke-width="2.8"/>
                    <path d="M24 10l2.5 4.5 4.5 2.5-4.5 2.5-2.5 4.5-2.5-4.5-4.5-2.5 4.5-2.5 2.5-4.5z" fill="#8b5cf6"/>
                    <path d="M16 26l1.2 2 2 1.2-2 1.2-1.2 2-1.2-2-2-1.2 2-1.2 1.2-2z" fill="#a78bfa"/>
                </svg>
            `);
        }

        // 5. Root Canal Evaluation: Anatomical tooth showing root canal & endodontic lines
        if (name.includes("root") || name.includes("canal") || name.includes("endo")) {
            return markup(`
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                    <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#fff7ed" stroke="#ea580c" stroke-width="2.8"/>
                    <path d="M20 20c0 4-1 9-2 14M28 20c0 4 1 9 2 14M24 14v8" stroke="#ea580c" stroke-width="2.6" stroke-linecap="round"/>
                </svg>
            `);
        }

        // 6. Adult Full Examination: Tooth with dental inspection lens
        if (name.includes("adult") || name.includes("exam") || name.includes("check")) {
            return markup(`
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                    <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#f0f9ff" stroke="#0284c7" stroke-width="2.8"/>
                    <circle cx="23" cy="20" r="6.5" stroke="#0284c7" stroke-width="2.4" fill="none"/>
                    <path d="M28 25l6 6" stroke="#0284c7" stroke-width="2.8" stroke-linecap="round"/>
                </svg>
            `);
        }

        // 7. Regular / Default: Classic clean medical tooth
        return markup(`
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="30" height="30" fill="none">
                <path d="M24 4C16 4 12 10 12 18c0 6 3 12 4 18 1 6 4 8 8 8s7-2 8-8c1-6 4-12 4-18 0-8-4-14-12-14z" fill="#f0f9ff" stroke="#0284c7" stroke-width="2.8"/>
                <path d="M20 18c0-2.5 1.8-4 4-4s4 1.5 4 4" stroke="#0284c7" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
        `);
    }

    // Step 2: Appointment Type Selection
    applyService(service) {
        this.state.selectedServiceKey = service.key;
        this.state.selectedTypeId = service.appointment_type_id || null;
        this.state.selectedTreatmentId = service.treatment_id || null;
        this.state.selectedTypeName = service.name;
        this.state.selectedTypeDuration = service.duration || 30;
    }

    selectType(service) {
        if (service.key !== this.state.selectedServiceKey) {
            // A different service has a different length: the chosen time must be re-picked
            this.clearSlotSelection();
        }
        this.applyService(service);
        this.goToStep(3);
    }

    clearSlotSelection() {
        this.state.selectedSlotTime = null;
        this.state.selectedSlotLabel = "";
        this.state.selectedSlotEndLabel = "";
    }

    // Step 3: Doctor Selection
    selectDoctor(doc) {
        if (!doc) {
            this.state.selectedDoctorId = null;
            this.state.selectedDoctorName = "Any Specialist";
            this.state.selectedDoctorSpec = "Dental Specialist";
        } else {
            this.state.selectedDoctorId = doc.id;
            this.state.selectedDoctorName = doc.name;
            this.state.selectedDoctorSpec = doc.job_title || "Dental Specialist";
        }
        this.goToStep(4);
    }

    // Step 4: Slots & Date
    async onDateChange(ev) {
        await this.setDate(ev.target.value);
    }

    async setDate(dateStr) {
        if (!dateStr) return;
        // Never go before today
        this.state.selectedDate = dateStr < this.state.todayDate ? this.state.todayDate : dateStr;
        await this.fetchSlots();
    }

    async shiftDate(days) {
        const d = parseDateStr(this.state.selectedDate);
        d.setDate(d.getDate() + days);
        await this.setDate(toLocalDateStr(d));
    }

    get canGoToPreviousDay() {
        return this.state.selectedDate > this.state.todayDate;
    }

    // Quick-pick chips for the next 7 days
    get upcomingDays() {
        const days = [];
        const start = parseDateStr(this.state.todayDate);
        for (let i = 0; i < 7; i++) {
            const d = new Date(start);
            d.setDate(start.getDate() + i);
            days.push({
                value: toLocalDateStr(d),
                weekday: i === 0 ? "Today" : i === 1 ? "Tomorrow" : d.toLocaleDateString(undefined, { weekday: "short" }),
                day: d.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
            });
        }
        return days;
    }

    get availableSlotCount() {
        return this.state.slots.filter((s) => s.available).length;
    }

    slotsForPeriod(periodKey) {
        return this.state.slots.filter((s) => s.period === periodKey);
    }

    async fetchSlots() {
        this.state.loadingSlots = true;
        this.clearSlotSelection();
        try {
            const res = await this.orm.call(
                "dental.appointment",
                "get_available_slots",
                [],
                {
                    date: this.state.selectedDate,
                    doctor_id: this.state.selectedDoctorId,
                    duration: this.state.selectedTypeDuration,
                    branch_id: user.activeCompany?.id || false,
                }
            );
            this.state.slots = res?.slots || [];
            this.state.slotPeriods = res?.periods || [];
            this.state.slotMessage = res?.message || "";
            this.state.dateLabel = res?.date_label || this.state.selectedDate;
            this.state.nextAvailableDate = res?.next_available_date || false;
            this.state.nextAvailableLabel = res?.next_available_label || "";
            if (res?.today) {
                this.state.todayDate = res.today;  // clinic's "today" wins over the browser's
            }
        } catch (e) {
            console.error("Error loading slots:", e);
            this.state.slots = [];
            this.state.slotPeriods = [];
            this.state.slotMessage = "Could not load availability. Please try again.";
        } finally {
            this.state.loadingSlots = false;
        }
    }

    selectSlot(slot) {
        if (!slot.available) return;
        this.state.selectedSlotTime = slot.time;
        this.state.selectedSlotLabel = slot.label;
        this.state.selectedSlotEndLabel = slot.end_label || "";
    }

    // Step 5: Insurance toggle
    setInsurance(val) {
        this.state.hasInsurance = val;
    }

    // Submit Booking
    async submitBooking() {
        this.state.errorMessage = "";

        // Bookings are always for a registered patient (their details are kept in the patient record)
        if (!this.state.foundPatient) {
            this.state.errorMessage = "Please select the patient first.";
            this.goToStep(1);
            return;
        }
        const fullName = this.state.foundPatient.name;
        const phone = this.state.foundPatient.phone || "";
        if (!this.state.selectedDate || !this.state.selectedSlotTime) {
            this.state.errorMessage = "Please select an appointment date and time slot.";
            return;
        }

        let fullNotes = (this.state.notes || "").trim();
        if (this.state.zipCode) fullNotes += `\nZip: ${this.state.zipCode}`;
        if (this.state.hasInsurance === "yes" && this.state.insuranceInfo) {
            fullNotes += `\nInsurance: ${this.state.insuranceInfo}`;
        }

        const payload = {
            patient_type: this.state.patientType,
            patient_id: this.state.foundPatient ? this.state.foundPatient.id : false,
            name: fullName,
            phone: phone,
            email: (this.state.email || "").trim(),
            dob: this.state.dob || false,
            gender: this.state.gender,
            appointment_type_id: this.state.selectedTypeId,
            treatment_id: this.state.selectedTreatmentId,
            branch_id: user.activeCompany?.id || false,
            doctor_id: this.state.selectedDoctorId,
            appointment_date: this.state.selectedDate,
            appointment_time: this.state.selectedSlotTime,
            date_str: this.state.selectedDate,
            time_str: this.state.selectedSlotTime,
            duration: this.state.selectedTypeDuration,
            duration_minutes: this.state.selectedTypeDuration,
            notes: fullNotes,
            priority: this.state.priority || "1",
            ...this.getExtraBookingParams(),
        };

        this.state.submitting = true;

        try {
            const res = await this.orm.call(
                "dental.appointment",
                "create_appointment_booking",
                [payload]
            );

            this.state.submitting = false;

            if (res && res.success) {
                this.state.createdAppointment = res;
                this.state.step = 6; // Success step
                this.notification.add(`Appointment ${res.appointment_name} successfully booked!`, {
                    type: "success"
                });
            } else {
                this.state.errorMessage = (res && res.error) || "Failed to book appointment. Please verify details.";
                if (/no longer available|not available at|booked at|outside clinic hours/i.test(this.state.errorMessage)) {
                    // Someone took the slot meanwhile: refresh and send the user back to pick another time
                    const message = this.state.errorMessage;
                    this.goToStep(4);
                    this.state.errorMessage = message;
                }
            }
        } catch (err) {
            this.state.submitting = false;
            this.state.errorMessage = "Booking failed: " + (err.message || err);
        }
    }

    /**
     * Extra values sent to create_appointment_booking. Extension point for add-ons
     * (e.g. dental_teleconsult adds the consultation mode).
     */
    getExtraBookingParams() {
        return {};
    }

    // Success Screen Actions
    openCreatedAppointment() {
        if (!this.state.createdAppointment) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dental.appointment",
            res_id: this.state.createdAppointment.appointment_id,
            views: [[false, "form"]],
            target: "current"
        });
    }

    bookAnother() {
        this.state.step = 1;
        this.state.patientType = "returning";
        this.clearPatient();
        this.clearSlotSelection();
        this.state.selectedDate = this.state.todayDate;
        this.state.firstName = "";
        this.state.lastName = "";
        this.state.phone = "";
        this.state.email = "";
        this.state.dob = "";
        this.state.notes = "";
        this.state.createdAppointment = null;
        this.state.errorMessage = "";
    }

    backToAppointmentsList() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Appointments",
            res_model: "dental.appointment",
            views: [[false, "list"], [false, "calendar"], [false, "form"]],
            context: { search_default_upcoming: 1 },
            target: "current"
        });
    }
}

BookAppointmentFlow.template = "dental_appointment.BookAppointmentFlow";
registry.category("actions").add("dental_appointment.book_appointment_flow", BookAppointmentFlow);
