import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

patch(PosOrderline.prototype, {
    canBeMergedWith(orderline) {
        // A prescription line stays its own line: it carries the prescription link and dosage
        if (this.dental_rx_line_ref || orderline.dental_rx_line_ref) {
            return false;
        }
        return super.canBeMergedWith(...arguments);
    },
});
