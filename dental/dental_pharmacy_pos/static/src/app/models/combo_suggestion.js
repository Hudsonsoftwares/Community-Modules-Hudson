import { patch } from "@web/core/utils/patch";
import { ComboSuggestion } from "@point_of_sale/app/models/utils/combo_suggestion";

// The product screen recomputes combo suggestions reactively. When the current order is
// replaced (deleted, finished, switched), it can briefly be undefined, and the standard code
// then crashes with "Cannot read properties of undefined (reading 'unsentLines')".
patch(ComboSuggestion.prototype, {
    getApplicableProductCombo(order, mode = "limited") {
        if (!order) {
            return [];
        }
        return super.getApplicableProductCombo(...arguments);
    },
    getPotentialCombos(order) {
        if (!order) {
            return [];
        }
        return super.getPotentialCombos(...arguments);
    },
});
