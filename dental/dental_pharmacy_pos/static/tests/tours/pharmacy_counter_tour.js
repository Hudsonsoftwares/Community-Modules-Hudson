import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import { registry } from "@web/core/registry";

function openPrescriptions() {
    return [
        {
            content: "Open the prescription queue",
            trigger: ".o_dental_rx_button",
            run: "click",
        },
        {
            content: "The patient's prescription is listed and selected",
            trigger: ".o_dental_rx_item.active:contains('Tour Rx Patient')",
        },
        {
            content: "Allergy alert is shown",
            trigger: ".o_dental_rx_allergy:contains('Known Allergies'):contains('Penicillin')",
        },
        {
            content: "Dosage and remaining quantity are shown",
            trigger: ".o_dental_rx_lines tr:contains('Tour Amoxicillin'):contains('Three times daily')",
        },
    ];
}

registry.category("web_tour.tours").add("DentalPharmacyCounterTour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            openPrescriptions(),
            {
                content: "Add the prescribed medicine to the order",
                trigger: ".o_dental_rx_add:not([disabled])",
                run: "click",
            },
            ProductScreen.selectedOrderlineHas("Tour Amoxicillin", "6.00"),
            ProductScreen.clickPayButton(),
            PaymentScreen.isInvoiceButtonChecked(),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            FeedbackScreen.isShown(),
            Chrome.waitRequest(),
        ].flat(),
});
