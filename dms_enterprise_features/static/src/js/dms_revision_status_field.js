/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class DmsRevisionStatusField extends Component {
    static template = xml`
        <span t-if="props.record.data[props.name]" class="badge rounded-pill text-bg-success">
            Active
        </span>
    `;
    static props = {
        ...standardFieldProps,
    };
}

export const dmsRevisionStatusField = {
    component: DmsRevisionStatusField,
    supportedTypes: ["boolean"],
};

registry.category("fields").add("dms_revision_status", dmsRevisionStatusField);
