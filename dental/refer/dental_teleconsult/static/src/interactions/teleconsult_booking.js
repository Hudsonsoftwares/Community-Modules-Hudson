import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * Website booking (dental_website_appointment): "At the clinic" / "Online video call" choice.
 * The booking page fires `dental:booking-submit` (mutable request params) and
 * `dental:booking-success` (server result); this interaction plugs into both.
 */
export class DentalTeleconsultBookingMode extends Interaction {
    static selector = ".o_dental_tc_booking_mode";
    dynamicContent = {
        ".o_dental_tc_mode_btn": {
            "t-on-click": this.onModeClick,
            "t-att-class": (btn) => ({ active: btn.dataset.mode === this.mode }),
            "t-att-aria-pressed": (btn) => String(btn.dataset.mode === this.mode),
            "t-att-disabled": (btn) => (btn.dataset.mode === "online" && !this.onlineAllowed ? "disabled" : false),
        },
        ".o_dental_tc_online_hint": { "t-att-class": () => ({ "d-none": this.mode !== "online" }) },
        ".o_dental_tc_unavailable": { "t-att-class": () => ({ "d-none": this.onlineAllowed }) },
    };

    setup() {
        this.mode = "in_clinic";
        this.onlineAllowed = true;
    }

    start() {
        const doc = this.el.ownerDocument;
        // Capture phase: the booking page's own onclick handler runs afterwards
        this.addListener(doc, "click", this.onDocumentClick, { capture: true });
        this.addListener(doc, "dental:booking-submit", this.onBookingSubmit);
        this.addListener(doc, "dental:booking-success", this.onBookingSuccess);
        // Mark the choice as live (until then the page's own script runs without it)
        this.el.classList.add("o_dental_tc_ready");
        this.registerCleanup(() => this.el.classList.remove("o_dental_tc_ready"));
    }

    onModeClick(ev) {
        const mode = ev.currentTarget.dataset.mode;
        if (mode === "online" && !this.onlineAllowed) {
            return;
        }
        this.mode = mode;
    }

    onDocumentClick(ev) {
        const card = ev.target.closest?.(".type-choice-card");
        if (!card) {
            return;
        }
        this.onlineAllowed = card.dataset.allowOnline !== "0";
        if (!this.onlineAllowed) {
            this.mode = "in_clinic";
        }
    }

    onBookingSubmit(ev) {
        if (ev.detail) {
            ev.detail.consultation_mode = this.mode;
        }
    }

    onBookingSuccess(ev) {
        const result = ev.detail || {};
        const pane = this.el.ownerDocument.getElementById("pane_step_success");
        const note = pane?.querySelector(".o_dental_tc_success_online");
        if (!pane || !note) {
            return;
        }
        const online = result.consultation_mode === "online";
        note.classList.toggle("d-none", !online);
        note.textContent = online ? result.teleconsult_message || "" : "";
        const title = pane.querySelector("h3");
        if (title) {
            title.dataset.dentalTcTitle ??= title.textContent;
            title.textContent = online
                ? result.status === "Confirmed"
                    ? "Online Consultation Confirmed!"
                    : "Online Consultation Requested!"
                : title.dataset.dentalTcTitle;
        }
        // "We're looking forward to seeing you at <clinic>" does not apply to a video call
        const clinicLine = note.nextElementSibling;
        if (clinicLine?.tagName === "P") {
            clinicLine.classList.toggle("d-none", online);
        }
        const service = pane.querySelector("#succ_service");
        if (service && online && result.service_name) {
            service.textContent = result.service_name;
        }
    }
}

registry.category("public.interactions").add("dental_teleconsult.booking_mode", DentalTeleconsultBookingMode);
