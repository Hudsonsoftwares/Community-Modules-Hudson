import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

patch(PaymentScreen.prototype, {
    async toggleIsToInvoice() {
        // Every pharmacy counter sale is invoiced
        if (this.pos.isPharmacyCounter && this.currentOrder.isToInvoice()) {
            this.notification.add(_t("Pharmacy sales are always invoiced."));
            return;
        }
        return await super.toggleIsToInvoice(...arguments);
    },
});
