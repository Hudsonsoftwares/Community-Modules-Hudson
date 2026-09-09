/** @odoo-module **/
import { Component, xml } from "@odoo/owl";

export class KnowledgeKanbanMockup extends Component {
    static template = xml`<div class="km-mockup km-kanban-mockup">
        <h3><t t-esc="props.itemName || 'Kanban'" /></h3>
        <div class="mockup-content">Kanban View Mockup</div>
    </div>`;
    static props = ["itemName"];
}
