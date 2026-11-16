import { patch } from "@web/core/utils/patch";
import { BookAppointmentFlow } from "@dental_appointment/js/book_appointment_flow";

/**
 * Staff booking flow: book the visit at the clinic or as an online video consultation.
 * get_bookable_services flags each service with `allow_online` (branch enabled + type allowed).
 */
patch(BookAppointmentFlow.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.consultationMode = "in_clinic";
    },

    get teleconsultService() {
        return (this.state.types || []).find((s) => s.key === this.state.selectedServiceKey) || null;
    },

    get teleconsultAllowed() {
        return Boolean(this.teleconsultService?.allow_online);
    },

    get teleconsultMode() {
        return this.teleconsultAllowed ? this.state.consultationMode : "in_clinic";
    },

    setConsultationMode(mode) {
        this.state.consultationMode = mode;
    },

    getExtraBookingParams() {
        return { ...super.getExtraBookingParams(), consultation_mode: this.teleconsultMode };
    },

    bookAnother() {
        super.bookAnother(...arguments);
        this.state.consultationMode = "in_clinic";
    },
});
