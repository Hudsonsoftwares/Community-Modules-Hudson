/** @odoo-module **/

import { Component, useState, onMounted, useRef } from "@odoo/owl";

export class LotDialog extends Component {
    setup() {
        this.state = useState({
            lotName: '',
        });
        this.lotInput = useRef("lotInput");
        
        onMounted(() => {
            if (this.lotInput.el) {
                this.lotInput.el.focus();
            }
        });
    }

    onApply() {
        if (this.state.lotName.trim()) {
            this.props.onApply(this.state.lotName.trim());
        }
    }
}
LotDialog.template = "custom_barcode_scanner.LotDialog";
LotDialog.props = ["product", "onApply", "onCancel"];
