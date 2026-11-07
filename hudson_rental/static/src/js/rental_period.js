import { Interaction } from "@web/public/interaction";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { AddToCart } from "@website_sale/interactions/add_to_cart";

const PERIOD_SELECTOR = ".o_rental_period";

function toDateInput(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * Pickup and return times picked by the visitor, in minutes after midnight.
 */
function getTimes(block) {
    const minutes = (name) => parseInt(block.querySelector(`select[name="${name}"]`).value) || 0;
    return { pickup: minutes("rental_pickup_time"), return: minutes("rental_return_time") };
}

/**
 * Read the rental period chosen in the product page block, as UTC ISO strings.
 * Dates and times are entered in the visitor's (browser) timezone.
 */
export function getRentalPeriod(el) {
    const block = el.querySelector(PERIOD_SELECTOR);
    if (!block) {
        return {};
    }
    const times = getTimes(block);
    const read = (dateName, minutes) => {
        const date = block.querySelector(`input[name="${dateName}"]`).value;
        if (!date) {
            return undefined;
        }
        const [y, m, d] = date.split("-").map(Number);
        return new Date(y, m - 1, d, 0, minutes).toISOString();
    };
    return {
        rental_start_date: read("rental_start_date", times.pickup),
        rental_end_date: read("rental_end_date", times.return),
        rental_tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
}

/**
 * Show what is wrong with the chosen period inside the Rental Period block (instead of
 * the small cart toast, easy to miss), with the period fields outlined.
 */
export function showRentalError(block, message) {
    const alert = block.querySelector(".o_rental_period_error");
    alert.querySelector(".o_rental_period_error_text").textContent = message;
    alert.classList.replace("d-none", "d-flex");
    block.classList.add("o_rental_period_invalid");
    alert.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

export function clearRentalError(block) {
    block.querySelector(".o_rental_period_error")?.classList.replace("d-flex", "d-none");
    block.classList.remove("o_rental_period_invalid");
}

/** Checks done in the browser, before asking the server. */
function getLocalRentalError(period) {
    if (!period.rental_start_date || !period.rental_end_date) {
        return _t("Please select a pickup and a return date.");
    }
    if (period.rental_end_date <= period.rental_start_date) {
        return _t("The return must be after the pickup.");
    }
    return false;
}

/**
 * "Rental Period" block of a rental product page: shows the visitor's timezone and
 * proposes a first rental period (one period of the product's periodicity).
 */
export class RentalPeriod extends Interaction {
    static selector = PERIOD_SELECTOR;
    dynamicContent = {
        'input[name="rental_start_date"]': { "t-on-change": this.onStartChange },
        "input, select": { "t-on-change": () => clearRentalError(this.el) },
    };

    setup() {
        this.isHourly = this.el.dataset.periodicity === "hour";
        this.startInput = this.el.querySelector('input[name="rental_start_date"]');
        this.endInput = this.el.querySelector('input[name="rental_end_date"]');
        this.pickupSelect = this.el.querySelector('select[name="rental_pickup_time"]');
        this.returnSelect = this.el.querySelector('select[name="rental_return_time"]');

        const offset = -new Date().getTimezoneOffset();
        const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
        this.el.querySelector(".o_rental_tz").textContent =
            `(UTC ${offset < 0 ? "-" : "+"} ${pad(offset / 60)}:${pad(offset % 60)})`;

        if (!this.startInput.value) {
            this.setDefaultPeriod();
        }
        this.startInput.min = toDateInput(new Date());
        this.updateEndMin();
    }

    setDefaultPeriod() {
        const periodicity = this.el.dataset.periodicity;
        const now = new Date();
        const start = new Date(now);
        if (this.isHourly) {
            start.setHours(now.getHours() + 1, 0, 0, 0);
            const end = new Date(start);
            end.setHours(end.getHours() + 1);
            this.startInput.value = toDateInput(start);
            this.endInput.value = toDateInput(end);
            this.pickupSelect.value = String(start.getHours() * 60);
            this.returnSelect.value = String(end.getHours() * 60);
            return;
        }
        // Proposed: pickup at the product's pickup time (today if still to come), return
        // one period later at the product's return time. The visitor can change both.
        const pickupMinutes = parseInt(this.el.dataset.pickupMinutes) || 0;
        const returnMinutes = parseInt(this.el.dataset.returnMinutes) || 0;
        start.setHours(0, pickupMinutes, 0, 0);
        if (start <= now) {
            start.setDate(start.getDate() + 1);
        }
        // One period: e.g. a daily product with times 8:00 -> 18:00 is returned the same
        // day; with 14:00 -> 10:00 (window over midnight) the next morning.
        const end = new Date(start);
        if (periodicity === "month") {
            end.setMonth(end.getMonth() + 1);
        } else {
            end.setDate(end.getDate() + (periodicity === "week" ? 7 : 1));
        }
        if (returnMinutes > pickupMinutes) {
            end.setDate(end.getDate() - 1);
        }
        this.startInput.value = toDateInput(start);
        this.endInput.value = toDateInput(end);
        this.pickupSelect.value = String(pickupMinutes);
        this.returnSelect.value = String(returnMinutes);
    }

    updateEndMin() {
        if (!this.startInput.value) {
            return;
        }
        this.endInput.min = this.startInput.value;
        if (!this.endInput.value || this.endInput.value < this.endInput.min) {
            this.endInput.value = this.endInput.min;
        }
    }

    onStartChange() {
        this.updateEndMin();
    }
}

registry.category("public.interactions").add("hudson_rental.rental_period", RentalPeriod);

// The shop's "Add to cart" checks the chosen rental period first (errors are shown in the
// Rental Period block), then sends it along with the product.
patch(AddToCart.prototype, {
    async addToCart(ev) {
        const button = ev.currentTarget;
        const productEl = button.closest(".js_product");
        const block = productEl?.querySelector(PERIOD_SELECTOR);
        if (block) {
            clearRentalError(block);
            const period = getRentalPeriod(productEl);
            let error = getLocalRentalError(period);
            if (!error) {
                // If the check itself fails, adding to the cart still checks the period
                const result = await this.waitFor(
                    rpc("/rental/period/check", {
                        product_template_id: parseInt(button.dataset.productTemplateId),
                        product_id: parseInt(button.dataset.productId),
                        quantity: parseFloat(productEl.querySelector('input[name="add_qty"]')?.value) || 1,
                        ...period,
                    }).catch(() => ({ error: false }))
                );
                error = result.error;
            }
            if (error) {
                showRentalError(block, error);
                return 0;
            }
            // After an await the event's currentTarget is gone: give the button explicitly
            return super.addToCart({ currentTarget: button });
        }
        return super.addToCart(ev);
    },

    _getOptionalParams(el) {
        return { ...super._getOptionalParams(el), ...getRentalPeriod(el) };
    },
});
