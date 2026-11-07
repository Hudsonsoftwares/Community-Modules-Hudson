/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy, markup } from "@odoo/owl";
import { user } from "@web/core/user";

export class BookAppointmentFlow extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const todayStr = new Date().toISOString().split("T")[0];

        this.state = proxy({
            step: 1, // 1: Patient, 2: Type, 3: Doctor, 4: Slots, 5: Form, 6: Success
            patientType: "new", // 'new' | 'returning'
            searchIdentifier: "",
            searchingPatient: false,
            searchMessage: "",
            foundPatient: null,

            // Step 2: Types
            types: [],
            selectedTypeId: null,
            selectedTypeName: "",
            selectedTypeDuration: 30,

            // Step 3: Doctors
            doctors: [],
            selectedDoctorId: null, // null = Any Specialist
            selectedDoctorName: "Any Specialist",
            selectedDoctorSpec: "Dental Specialist",

            // Step 4: Schedule & Slots
            selectedDate: todayStr,
            slots: [],
            loadingSlots: false,
            selectedSlotTime: null,
            selectedSlotLabel: "",

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
            // 1. Load appointment types
            const types = await this.orm.searchRead(
                "dental.appointment.type",
                [["active", "=", true]],
                ["id", "name", "duration", "description", "price"],
                { order: "id asc" }
            );
            this.state.types = types || [];
            if (this.state.types.length > 0) {
                this.state.selectedTypeId = this.state.types[0].id;
                this.state.selectedTypeName = this.state.types[0].name;
                this.state.selectedTypeDuration = this.state.types[0].duration || 30;
            }

            // 2. Load dentists
            const doctors = await this.orm.searchRead(
                "hr.employee",
                [["is_dentist", "=", true], ["active", "=", true]],
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

    goToStep(stepNumber) {
        this.state.errorMessage = "";
        if (stepNumber === 4) {
            this.fetchSlots();
        }
        this.state.step = stepNumber;
    }

    // Step 1: Patient Type & Lookup
    setPatientType(type) {
        this.state.patientType = type;
        this.state.searchMessage = "";
        if (type === "new") {
            this.state.foundPatient = null;
        }
    }

    async lookupPatient() {
        const idVal = (this.state.searchIdentifier || "").trim();
        if (!idVal) {
            this.state.searchMessage = "Please enter a phone number, email, or Patient ID.";
            return;
        }

        this.state.searchingPatient = true;
        this.state.searchMessage = "Looking up patient records...";

        try {
            const res = await this.orm.call(
                "dental.appointment",
                "check_patient",
                [],
                { identifier: idVal }
            );

            this.state.searchingPatient = false;
            if (res && res.found) {
                const p = res.patient || res;
                this.state.foundPatient = p;
                this.state.searchMessage = `Found patient: ${p.name} (${p.dental_patient_id || ""})`;

                // Pre-fill details
                const parts = (p.name || "").split(" ");
                this.state.firstName = parts[0] || "";
                this.state.lastName = parts.slice(1).join(" ") || "";
                this.state.phone = p.phone || idVal;
                this.state.email = p.email || "";
                this.state.dob = p.date_of_birth || "";
                this.state.gender = p.gender || "male";

                // Automatically proceed to service selection after short delay
                setTimeout(() => {
                    this.goToStep(2);
                }, 600);
            } else {
                this.state.foundPatient = null;
                this.state.searchMessage = res.message || `No record found for "${idVal}". You can continue as a New Patient.`;
            }
        } catch (err) {
            this.state.searchingPatient = false;
            this.state.searchMessage = "Lookup failed: " + (err.message || err);
        }
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
    selectType(type) {
        this.state.selectedTypeId = type.id;
        this.state.selectedTypeName = type.name;
        this.state.selectedTypeDuration = type.duration || 30;
        this.goToStep(3);
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
        this.state.selectedDate = ev.target.value;
        this.state.selectedSlotTime = null;
        await this.fetchSlots();
    }

    async fetchSlots() {
        this.state.loadingSlots = true;
        this.state.selectedSlotTime = null;
        try {
            const res = await this.orm.call(
                "dental.appointment",
                "get_available_slots",
                [],
                {
                    date: this.state.selectedDate,
                    doctor_id: this.state.selectedDoctorId,
                    duration: this.state.selectedTypeDuration
                }
            );
            this.state.slots = (res && res.slots) ? res.slots : [];
        } catch (e) {
            console.error("Error loading slots:", e);
            this.state.slots = [];
        } finally {
            this.state.loadingSlots = false;
        }
    }

    selectSlot(slot) {
        if (!slot.available) return;
        this.state.selectedSlotTime = slot.time;
        this.state.selectedSlotLabel = slot.label;
    }

    // Step 5: Insurance toggle
    setInsurance(val) {
        this.state.hasInsurance = val;
    }

    // Submit Booking
    async submitBooking() {
        this.state.errorMessage = "";

        const fName = (this.state.firstName || "").trim();
        const lName = (this.state.lastName || "").trim();
        const fullName = `${fName} ${lName}`.trim();
        const phone = (this.state.phone || "").trim();

        if (!fullName) {
            this.state.errorMessage = "Please enter patient's name.";
            return;
        }
        if (!phone) {
            this.state.errorMessage = "Please enter patient's mobile phone number.";
            return;
        }
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
            doctor_id: this.state.selectedDoctorId,
            appointment_date: this.state.selectedDate,
            appointment_time: this.state.selectedSlotTime,
            date_str: this.state.selectedDate,
            time_str: this.state.selectedSlotTime,
            duration: this.state.selectedTypeDuration,
            duration_minutes: this.state.selectedTypeDuration,
            notes: fullNotes,
            priority: this.state.priority || "1"
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
            }
        } catch (err) {
            this.state.submitting = false;
            this.state.errorMessage = "Booking failed: " + (err.message || err);
        }
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
        this.state.patientType = "new";
        this.state.foundPatient = null;
        this.state.searchIdentifier = "";
        this.state.searchMessage = "";
        this.state.selectedSlotTime = null;
        this.state.selectedSlotLabel = "";
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
