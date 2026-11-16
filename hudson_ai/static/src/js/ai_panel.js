/** @odoo-module **/
// Part of Hudson Community. See LICENSE file for full copyright and licensing details.

/**
 * Hudson AI chat panel.
 *
 * One floating panel per browser tab, opened from the "Ask AI" systray button
 * (general questions) or from the chatter "AI" button (questions about the
 * record). Only the typed message, the last few chat turns and the current
 * record reference (model + id) are sent to the server.
 */

import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

const HISTORY_LENGTH = 10;

const GENERAL_PROMPTS = [
    [_t("Sales this month"), _t("What are the total confirmed sales this month, and the top 5 customers?")],
    [_t("Overdue invoices"), _t("Which customer invoices are overdue? Give the total per customer.")],
    [_t("Open opportunities"), _t("Show my open CRM opportunities with the highest expected revenue.")],
    [_t("Create a contact"), _t("Help me create a new contact. Ask me for the details.")],
];

const RECORD_PROMPTS = [
    [_t("Summarize"), "summarize"],
    [_t("Draft a reply"), "draft"],
    [_t("Next steps"), _t("Based on this record and its history, what should I do next?")],
];

const ICONS = {
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    clear: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/>',
    send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><path d="M12 17v5"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
};

function icon(name) {
    // Odoo 20 does not ship Font Awesome in the backend: use inline SVG.
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/** Tiny, safe Markdown renderer (the text is escaped first). */
function renderMarkdown(text) {
    const inline = (s) =>
        s
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    const lines = escapeHtml(text).split("\n");
    const html = [];
    let list = null;
    let table = null;
    const closeBlocks = () => {
        if (list) {
            html.push(`</${list}>`);
            list = null;
        }
        if (table) {
            html.push("</tbody></table></div>");
            table = null;
        }
    };
    for (const raw of lines) {
        const line = raw.trim();
        const cells = line.startsWith("|") && line.endsWith("|") ? line.slice(1, -1).split("|") : null;
        if (cells) {
            if (cells.every((c) => /^\s*:?-{2,}:?\s*$/.test(c))) {
                continue; // header separator
            }
            if (!table) {
                closeBlocks();
                html.push('<div class="o_ai_table"><table class="table table-sm"><tbody>');
                table = true;
                html.push(`<tr>${cells.map((c) => `<th>${inline(c.trim())}</th>`).join("")}</tr>`);
                continue;
            }
            html.push(`<tr>${cells.map((c) => `<td>${inline(c.trim())}</td>`).join("")}</tr>`);
            continue;
        }
        const bullet = line.match(/^[-*•]\s+(.*)/);
        const numbered = line.match(/^\d+[.)]\s+(.*)/);
        if (bullet || numbered) {
            const tag = bullet ? "ul" : "ol";
            if (list !== tag) {
                closeBlocks();
                html.push(`<${tag}>`);
                list = tag;
            }
            html.push(`<li>${inline((bullet || numbered)[1])}</li>`);
            continue;
        }
        closeBlocks();
        const heading = line.match(/^#{1,4}\s+(.*)/);
        if (heading) {
            html.push(`<p class="o_ai_heading">${inline(heading[1])}</p>`);
        } else if (line) {
            html.push(`<p>${inline(line)}</p>`);
        }
    }
    closeBlocks();
    return html.join("");
}

class AIPanel {
    constructor() {
        this.history = [];
        this.busy = false;
        this.record = null;
        this.actionService = null;
        this.el = this.build();
        document.body.appendChild(this.el);
    }

    build() {
        const el = document.createElement("div");
        el.className = "o_hudson_ai_panel d-none";
        el.innerHTML = `
            <div class="o_ai_header">
                <span class="o_ai_logo">✦</span>
                <div class="o_ai_title">
                    <div class="fw-bold">Hudson AI</div>
                    <div class="o_ai_context small text-truncate"></div>
                </div>
                <button class="o_ai_icon_btn" data-act="clear" title="${escapeHtml(_t("New conversation"))}">${icon("clear")}</button>
                <button class="o_ai_icon_btn" data-act="close" title="${escapeHtml(_t("Close"))}">${icon("close")}</button>
            </div>
            <div class="o_ai_chips"></div>
            <div class="o_ai_messages"></div>
            <div class="o_ai_input">
                <textarea rows="1" placeholder="${escapeHtml(_t("Ask anything about your data…"))}"></textarea>
                <button class="o_ai_icon_btn o_ai_mic" data-act="mic" title="${escapeHtml(_t("Speak"))}">${icon("mic")}</button>
                <button class="o_ai_send" data-act="send" title="${escapeHtml(_t("Send"))}">${icon("send")}</button>
            </div>`;
        this.messagesEl = el.querySelector(".o_ai_messages");
        this.chipsEl = el.querySelector(".o_ai_chips");
        this.contextEl = el.querySelector(".o_ai_context");
        this.input = el.querySelector("textarea");
        this.sendBtn = el.querySelector(".o_ai_send");
        el.addEventListener("click", (ev) => this.onClick(ev));
        this.input.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" && !ev.shiftKey) {
                ev.preventDefault();
                this.send(this.input.value);
            }
        });
        this.input.addEventListener("input", () => {
            this.input.style.height = "auto";
            this.input.style.height = Math.min(this.input.scrollHeight, 120) + "px";
        });
        if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
            el.querySelector(".o_ai_mic").remove();
        }
        return el;
    }

    open({ record = null, actionService = null } = {}) {
        if (actionService) {
            this.actionService = actionService;
        }
        const sameContext =
            (this.record && record && this.record.model === record.model && this.record.id === record.id) ||
            (!this.record && !record);
        if (!sameContext) {
            this.record = record;
            this.setDraftMode(false);
            this.history = [];
            this.messagesEl.innerHTML = "";
        }
        this.contextEl.textContent = this.record
            ? _t("About: %s", this.record.name || `${this.record.model} #${this.record.id}`)
            : _t("Ask about any of your data");
        this.renderChips();
        if (!this.messagesEl.children.length) {
            this.renderWelcome();
        }
        this.el.classList.remove("d-none");
        this.input.focus();
    }

    setDraftMode(active) {
        this.draftMode = active;
        this.input.placeholder = active
            ? _t("What should the message say? e.g. ask for payment confirmation")
            : _t("Ask anything about your data…");
        this.el.classList.toggle("o_ai_drafting", active);
    }

    toggle(options) {
        if (this.el.classList.contains("d-none")) {
            this.open(options);
        } else {
            this.close();
        }
    }

    close() {
        this.el.classList.add("d-none");
    }

    clear() {
        this.history = [];
        this.messagesEl.innerHTML = "";
        this.renderWelcome();
    }

    renderChips() {
        const prompts = this.record ? RECORD_PROMPTS : GENERAL_PROMPTS;
        this.chipsEl.innerHTML = "";
        for (const [label, prompt] of prompts) {
            const chip = document.createElement("button");
            chip.className = "o_ai_chip";
            chip.textContent = label;
            chip.addEventListener("click", () => this.runPrompt(prompt));
            this.chipsEl.appendChild(chip);
        }
    }

    renderWelcome() {
        const text = this.record
            ? _t("Ask me anything about this record, or use a shortcut above.")
            : _t("I can search, summarize, count and create records for you. Try a shortcut above.");
        this.messagesEl.innerHTML = `<div class="o_ai_welcome"><div class="o_ai_logo">✦</div><p>${escapeHtml(text)}</p></div>`;
    }

    onClick(ev) {
        const btn = ev.target.closest("[data-act]");
        if (!btn) {
            return;
        }
        const act = btn.dataset.act;
        if (act === "close") {
            this.close();
        } else if (act === "clear") {
            this.clear();
        } else if (act === "send") {
            this.send(this.input.value);
        } else if (act === "mic") {
            this.listen(btn);
        } else if (act === "copy") {
            navigator.clipboard?.writeText(btn.closest(".o_ai_msg").dataset.raw || "");
            btn.classList.add("o_ai_done");
        } else if (act === "open") {
            this.actionService?.doAction({
                type: "ir.actions.act_window",
                res_model: btn.dataset.model,
                res_id: parseInt(btn.dataset.id),
                views: [[false, "form"]],
            });
        }
    }

    runPrompt(prompt) {
        if (prompt === "summarize") {
            return this.call(_t("Summarize this record's discussion"), "/hudson_ai/summarize", {
                model: this.record.model,
                res_id: this.record.id,
            });
        }
        if (prompt === "draft") {
            this.setDraftMode(true);
            this.input.focus();
            return;
        }
        return this.send(prompt);
    }

    send(text) {
        text = (text || "").trim();
        if (!text) {
            return;
        }
        if (this.draftMode && this.record) {
            this.setDraftMode(false);
            return this.call(_t("Draft: %s", text), "/hudson_ai/draft", {
                model: this.record.model,
                res_id: this.record.id,
                instruction: text,
            }, { copy: true });
        }
        return this.call(text, "/hudson_ai/chat", {
            message: text,
            history: this.history.slice(-HISTORY_LENGTH),
            record: this.record && { model: this.record.model, id: this.record.id },
        });
    }

    async call(text, route, params, { copy = false } = {}) {
        if (this.busy) {
            return;
        }
        this.busy = true;
        this.input.value = "";
        this.input.style.height = "auto";
        this.messagesEl.querySelector(".o_ai_welcome")?.remove();
        this.addMessage("user", text);
        const typing = this.addTyping();
        this.sendBtn.disabled = true;
        try {
            const result = await rpc(route, params, { silent: true });
            typing.remove();
            if (result.error) {
                this.addMessage("error", result.error);
            } else {
                this.addMessage("assistant", result.reply, { records: result.records, copy });
                this.history.push({ role: "user", content: text }, { role: "assistant", content: result.reply });
            }
        } catch (error) {
            typing.remove();
            this.addMessage("error", error.data?.message || error.message || String(error));
        } finally {
            this.busy = false;
            this.sendBtn.disabled = false;
            this.input.focus();
        }
    }

    addMessage(role, text, { records = [], copy = false } = {}) {
        const row = document.createElement("div");
        row.className = `o_ai_msg o_ai_msg_${role}`;
        row.dataset.raw = text || "";
        let html = role === "user" ? `<p>${escapeHtml(text)}</p>` : renderMarkdown(text);
        if (records?.length) {
            const seen = new Set();
            const links = records
                .filter((r) => !seen.has(`${r.model},${r.id}`) && seen.add(`${r.model},${r.id}`))
                .map(
                    (r) =>
                        `<button class="o_ai_record" data-act="open" data-model="${escapeHtml(r.model)}" data-id="${r.id}">${escapeHtml(r.name)}</button>`
                )
                .join("");
            html += `<div class="o_ai_records">${links}</div>`;
        }
        if (copy) {
            html += `<button class="o_ai_icon_btn o_ai_copy" data-act="copy" title="${escapeHtml(_t("Copy"))}">${icon("copy")}</button>`;
        }
        row.innerHTML = html;
        this.messagesEl.appendChild(row);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        return row;
    }

    addTyping() {
        const row = document.createElement("div");
        row.className = "o_ai_msg o_ai_msg_assistant o_ai_typing";
        row.innerHTML = "<span></span><span></span><span></span>";
        this.messagesEl.appendChild(row);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        return row;
    }

    listen(btn) {
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (this.recognition) {
            this.recognition.stop();
            return;
        }
        const recognition = new Recognition();
        recognition.lang = document.documentElement.lang || "en-US";
        recognition.onresult = (ev) => {
            const said = Array.from(ev.results).map((r) => r[0].transcript).join(" ");
            this.input.value = (this.input.value ? this.input.value + " " : "") + said;
        };
        recognition.onend = () => {
            this.recognition = null;
            btn.classList.remove("o_ai_recording");
        };
        this.recognition = recognition;
        btn.classList.add("o_ai_recording");
        recognition.start();
    }
}

let panel = null;

/**
 * @param {{record?: {model: string, id: number, name?: string}, actionService?: object}} options
 */
export function toggleAIPanel(options = {}) {
    panel ??= new AIPanel();
    panel.toggle(options);
}

export function openAIPanel(options = {}) {
    panel ??= new AIPanel();
    panel.open(options);
}
