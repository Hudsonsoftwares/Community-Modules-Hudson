/** @odoo-module **/

import { Component, proxy, onMounted, signal, useProps } from "@odoo/owl";

export class LotDialog extends Component {
    // props: product, onApply, onCancel
    props = useProps();

    setup() {
        this.state = proxy({
            lotName: '',
        });
        this.lotInput = signal.ref();

        onMounted(() => {
            if (this.lotInput()) {
                this.lotInput().focus();
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
