/** @odoo-module **/
import { Component, xml } from "@odoo/owl";

export class KnowledgeCalendarMockup extends Component {
    static template = xml`<div class="km-mockup km-calendar-mockup">
        <h3><t t-esc="props.itemName || 'Calendar'" /></h3>
        <div class="mockup-content">Calendar View Mockup</div>
    </div>`;
    static props = ["itemName"];
}
