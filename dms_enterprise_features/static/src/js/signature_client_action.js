/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, xml } from "@odoo/owl";

export class DmsSignaturePdfViewer extends Component {
    static template = xml`
        <div class="o_action h-100 w-100">
            <iframe 
                t-att-src="'/dms/signature/setup/' + props.action.context.default_revision_id" 
                style="width: 100%; height: 100%; border: none;">
            </iframe>
        </div>
    `;
}

registry.category("actions").add("dms_signature_pdf_viewer", DmsSignaturePdfViewer);
