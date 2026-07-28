/** @odoo-module **/

/**
 * Hudson AI Systray — floating chat panel registered in the top navbar.
 *
 * Architecture (flat, no sub-components):
 *  • HudsonAISystray  — The systray icon rendered via the systray registry.
 *    It mounts/unmounts a HudsonAIPanel component on demand.
 *  • HudsonAIPanel    — The floating chat window; all services are injected
 *    directly here to avoid OWL child-service scoping issues.
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    Component,
    useState,
    useRef,
    onMounted,
    onWillUnmount,
    mount,
} from "@odoo/owl";

// ─── Quick-action chip definitions ───────────────────────────────────────────

const QUICK_ACTIONS = [
    { label: "📊 Sales Summary",     prompt: "Give me a summary of sales orders this month. Show total amounts and top customers." },
    { label: "👥 Top Employees",     prompt: "Who are the most active employees? Check timesheets or tasks." },
    { label: "📦 Low Stock",         prompt: "Show me products with low stock levels (below reorder point)." },
    { label: "💼 Create Lead",       prompt: "Help me create a new CRM lead. Ask me for the details." },
    { label: "📋 Open Quotations",   prompt: "List all open sales quotations (state = draft or sent)." },
    { label: "💰 Overdue Invoices",  prompt: "Show me all overdue customer invoices." },
];

// ─── HudsonAIPanel ────────────────────────────────────────────────────────────

class HudsonAIPanel extends Component {
    static template = "hudson_ai.HudsonAIPanel";
    static props = {
        onClose: Function,
    };

    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.notification = useService("notification");
        this.messagesEl = useRef("messagesEl");
        this.inputEl = useRef("inputEl");

        this.quickActions = QUICK_ACTIONS;

        this.state = useState({
            messages: [],        // { id, role: 'user'|'assistant'|'tool', content }
            isLoading: false,
            isRecording: false,
            modelName: "",
        });

        // Conversation history for the API (role + content pairs)
        this._history = [];
        this._msgCounter = 0;
        this._recognition = null;

        onMounted(async () => {
            this._fetchConfig();
            this.inputEl.el && this.inputEl.el.focus();
        });

        onWillUnmount(() => {
            this._stopVoice();
        });
    }

    // ── Internal helpers ──────────────────────────────────────────────────────

    async _fetchConfig() {
        try {
            const resp = await fetch("/hudson_ai/config", { credentials: "same-origin" });
            const data = await resp.json();
            if (data.model_name) {
                this.state.modelName = data.model_name;
            }
        } catch (_) {
            /* ignore */
        }
    }

    _nextId() {
        return ++this._msgCounter;
    }

    _pushMsg(role, content) {
        this.state.messages.push({ id: this._nextId(), role, content });
        this._scrollToBottom();
    }

    _scrollToBottom() {
        const el = this.messagesEl.el;
        if (el) {
            // Use requestAnimationFrame to ensure DOM has updated
            requestAnimationFrame(() => {
                el.scrollTop = el.scrollHeight;
            });
        }
    }

    _getInputValue() {
        return this.inputEl.el ? this.inputEl.el.value.trim() : "";
    }

    _clearInput() {
        if (this.inputEl.el) {
            this.inputEl.el.value = "";
            this.inputEl.el.style.height = "auto";
        }
    }

    // ── User interactions ─────────────────────────────────────────────────────

    async sendMessage() {
        const text = this._getInputValue();
        if (!text || this.state.isLoading) return;
        this._clearInput();
        await this._processMessage(text);
    }

    async sendQuickAction(prompt) {
        if (this.state.isLoading) return;
        await this._processMessage(prompt);
    }

    async _processMessage(userText) {
        // Show user bubble
        this._pushMsg("user", userText);

        // Build history for the API (only user/assistant turns, not tool)
        const historyForApi = this._history.map(m => ({ role: m.role, content: m.content }));

        // Set loading
        this.state.isLoading = true;

        try {
            const result = await this.rpc("/hudson_ai/chat", {
                user_message: userText,
                conversation_history: historyForApi,
            });

            const reply = result.reply || result.error || "No response received.";

            // Save to history
            this._history.push({ role: "user", content: userText });
            this._history.push({ role: "assistant", content: reply });

            // Keep history trimmed
            if (this._history.length > 40) {
                this._history = this._history.slice(-40);
            }

            this._pushMsg("assistant", reply);
        } catch (err) {
            const errMsg =
                "❌ Failed to reach the AI backend. " +
                "Please check that LM Studio is running and the module configuration is correct.\n\n" +
                `Error: ${err.message || err}`;
            this._pushMsg("assistant", errMsg);
        } finally {
            this.state.isLoading = false;
            this._scrollToBottom();
        }
    }

    onKeyDown(ev) {
        // Send on Enter (without Shift)
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
        // Auto-resize textarea
        const el = ev.target;
        el.style.height = "auto";
        el.style.height = Math.min(el.scrollHeight, 120) + "px";
    }

    clearConversation() {
        this.state.messages = [];
        this._history = [];
    }

    closePanel() {
        this.props.onClose();
    }

    async openSettings() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Hudson AI Configuration",
            res_model: "hudson.ai.config",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
        this.props.onClose();
    }

    // ── Voice input ───────────────────────────────────────────────────────────

    toggleVoice() {
        if (this.state.isRecording) {
            this._stopVoice();
        } else {
            this._startVoice();
        }
    }

    _startVoice() {
        const SpeechRecognition =
            window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            this.notification.add(
                "Your browser does not support voice input. Please use Chrome or Edge.",
                { type: "warning" }
            );
            return;
        }
        this._recognition = new SpeechRecognition();
        this._recognition.lang = "en-US";
        this._recognition.interimResults = false;
        this._recognition.continuous = false;

        this._recognition.onstart = () => {
            this.state.isRecording = true;
        };
        this._recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            if (this.inputEl.el) {
                this.inputEl.el.value = transcript;
            }
            this.state.isRecording = false;
        };
        this._recognition.onerror = (event) => {
            console.error("Speech recognition error:", event.error);
            this.state.isRecording = false;
            this.notification.add(
                `Voice input error: ${event.error}`,
                { type: "warning" }
            );
        };
        this._recognition.onend = () => {
            this.state.isRecording = false;
        };

        this._recognition.start();
    }

    _stopVoice() {
        if (this._recognition) {
            try { this._recognition.stop(); } catch (_) {}
            this._recognition = null;
        }
        this.state.isRecording = false;
    }
}

// ─── HudsonAISystray ─────────────────────────────────────────────────────────

class HudsonAISystray extends Component {
    static template = "hudson_ai.HudsonAISystray";

    setup() {
        this._panelApp = null;
        this._panelContainer = null;
        this.state = useState({ open: false });

        onWillUnmount(() => {
            this._destroyPanel();
        });
    }

    togglePanel() {
        if (this.state.open) {
            this._destroyPanel();
        } else {
            this._mountPanel();
        }
    }

    _mountPanel() {
        if (this._panelContainer) return;

        this._panelContainer = document.createElement("div");
        document.body.appendChild(this._panelContainer);

        this._panelApp = mount(HudsonAIPanel, this._panelContainer, {
            env: this.__owl__.app.env,
            props: {
                onClose: () => this._destroyPanel(),
            },
        });

        this.state.open = true;
    }

    _destroyPanel() {
        if (this._panelApp) {
            try { this._panelApp.destroy(); } catch (_) {}
            this._panelApp = null;
        }
        if (this._panelContainer) {
            this._panelContainer.remove();
            this._panelContainer = null;
        }
        this.state.open = false;
    }
}

// Register in the systray registry
registry.category("systray").add(
    "hudson_ai.systray",
    { Component: HudsonAISystray },
    { sequence: 5 }
);
