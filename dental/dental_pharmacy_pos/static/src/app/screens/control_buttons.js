import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

patch(ControlButtons.prototype, {
    async onClickDentalPrescriptions() {
        await this.pos.dentalOpenPrescriptions();
    },
    async onClickDentalPatientInfo() {
        const partner = this.pos.getOrder()?.getPartner();
        if (partner) {
            await this.pos.dentalShowPatientInfo(partner);
        }
    },
});
