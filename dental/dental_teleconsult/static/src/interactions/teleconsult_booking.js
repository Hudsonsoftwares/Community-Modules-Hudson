import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

// Service cards and success panes of the two website booking pages
// (dental_appointment.book_appointment and dental_website_appointment.book_appointment)
const SERVICE_CARD_SELECTOR = ".type-grid-card, .type-choice-card";
const SUCCESS_PANE_IDS = ["pane_step_6", "pane_step_success"];

/**
 * Website booking: "At the clinic" / "Online video call" choice.
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
        this.emailInput = this.el.ownerDocument.getElementById("inp_email");
        this.emailWasRequired = Boolean(this.emailInput?.required);
    }

    start() {
        const doc = this.el.ownerDocument;
        // Capture phase: the booking page's own onclick handler runs afterwards
        this.addListener(doc, "click", this.onDocumentClick, { capture: true });
        this.addListener(doc, "dental:booking-submit", this.onBookingSubmit);
        this.addListener(doc, "dental:booking-success", this.onBookingSuccess);
        // A service may already be selected (e.g. browser back/forward)
        const selected = doc.querySelector(".type-grid-card.selected, .type-choice-card.selected");
        if (selected) {
            this.onlineAllowed = selected.dataset.allowOnline !== "0";
        }
        // Mark the choice as live (until then the page's own script runs without it)
        this.el.classList.add("o_dental_tc_ready");
        this.registerCleanup(() => {
            this.el.classList.remove("o_dental_tc_ready");
            this.syncEmailRequired("in_clinic");
        });
    }

    setMode(mode) {
        this.mode = mode;
        this.syncEmailRequired(mode);
    }

    /** The secure join link is emailed: an email address is mandatory for an online visit. */
    syncEmailRequired(mode) {
        if (this.emailInput) {
            this.emailInput.required = mode === "online" || this.emailWasRequired;
        }
    }

    onModeClick(ev) {
        const mode = ev.currentTarget.dataset.mode;
        if (mode === "online" && !this.onlineAllowed) {
            return;
        }
        this.setMode(mode);
    }

    onDocumentClick(ev) {
        const card = ev.target.closest?.(SERVICE_CARD_SELECTOR);
        if (!card) {
            return;
        }
        this.onlineAllowed = card.dataset.allowOnline !== "0";
        if (!this.onlineAllowed && this.mode === "online") {
            this.setMode("in_clinic");
        }
    }

    onBookingSubmit(ev) {
        if (ev.detail) {
            ev.detail.consultation_mode = this.onlineAllowed ? this.mode : "in_clinic";
        }
    }

    onBookingSuccess(ev) {
        const result = ev.detail || {};
        const doc = this.el.ownerDocument;
        const pane = SUCCESS_PANE_IDS.map((id) => doc.getElementById(id)).find(Boolean);
        const note = pane?.querySelector(".o_dental_tc_success_online");
        if (!pane || !note) {
            return;
        }
        const online = result.consultation_mode === "online";
        note.classList.toggle("d-none", !online);
        note.textContent = online ? result.teleconsult_message || "" : "";
        const title = pane.querySelector("h2, h3");
        if (title) {
            title.dataset.dentalTcTitle ??= title.textContent;
            title.textContent = online
                ? result.status === "Confirmed"
                    ? "Online Consultation Confirmed!"
                    : "Online Consultation Requested!"
                : title.dataset.dentalTcTitle;
        }
        const service = pane.querySelector("#res_succ_service, #succ_service");
        if (service && online && result.service_name) {
            service.textContent = result.service_name;
        }
        // Next booking starts again from the default
        this.setMode("in_clinic");
    }
}

registry.category("public.interactions").add("dental_teleconsult.booking_mode", DentalTeleconsultBookingMode);
