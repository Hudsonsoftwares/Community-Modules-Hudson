import { Component, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class PatientInfoPopup extends Component {
    static template = "dental_pharmacy_pos.PatientInfoPopup";
    static components = { Dialog };
    props = useProps({
        partnerName: t.string(),
        info: t.object(),
        getPayload: t.function(),
        close: t.function(),
    });

    get allergyClass() {
        const status = this.props.info.allergy.status;
        if (status === "known") {
            return "alert-danger";
        }
        return status === "none" ? "alert-success" : "alert-warning";
    }

    openPrescriptions() {
        this.props.getPayload(true);
        this.props.close();
    }
}
