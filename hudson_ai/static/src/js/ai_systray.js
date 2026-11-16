/** @odoo-module **/
// Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { Chatter } from "@mail/chatter/web_portal_project/chatter";

import { openAIPanel, toggleAIPanel } from "./ai_panel";

/** "Ask AI" button in the top bar. */
export class HudsonAISystray extends Component {
    static template = "hudson_ai.Systray";

    setup() {
        this.action = useService("action");
    }

    onClick() {
        toggleAIPanel({ actionService: this.action });
    }
}

registry.category("systray").add("hudson_ai.systray", { Component: HudsonAISystray }, { sequence: 90 });

/** "AI" button in the chatter: opens the panel about the current record. */
patch(Chatter.prototype, {
    onClickHudsonAI() {
        const thread = this.state.thread;
        if (!thread?.id) {
            return;
        }
        openAIPanel({
            record: { model: thread.model, id: thread.id, name: thread.displayName },
            actionService: this.env.services.action,
        });
    },
});
