/** @odoo-module **/

/**
 * Hudson AI Chatter Integration
 *
 * Injects two AI buttons ("✦ Summarize" and "✏️ Draft with AI") directly into
 * the DOM of the Odoo chatter. This approach is highly compatible across versions.
 */

// ─── Patch the Chatter component via DOM Mutation ─────────────────────────────

function injectAIButtonsIntoChatter() {
    // Observe for chatter elements appearing in the DOM
    const observer = new MutationObserver(() => {
        const chatters = document.querySelectorAll(".o-mail-Chatter");
        chatters.forEach((chatterEl) => {
            // Avoid double-injection
            if (chatterEl.dataset.hudsonAiInjected) return;
            chatterEl.dataset.hudsonAiInjected = "1";

            // Find toolbar or header area
            const toolbar = chatterEl.querySelector(
                ".o-mail-Chatter-top, .o-mail-ChatterTopbar, .o_chatter_topbar"
            );
            if (!toolbar) return;

            // Create container div
            const btnContainer = document.createElement("div");
            btnContainer.className = "o_hudson_ai_chatter_container";
            btnContainer.style.cssText = "display:inline-flex; align-items:center; gap:6px; margin-left:8px;";

            // Summarize button
            const sumBtn = document.createElement("button");
            sumBtn.className = "o_hudson_ai_chatter_btn summarize";
            sumBtn.title = "Summarize the chatter conversation with AI";
            sumBtn.innerHTML = "✦ Summarize";
            sumBtn.addEventListener("click", () =>
                handleSummarize(chatterEl, sumBtn)
            );

            // Draft button
            const draftBtn = document.createElement("button");
            draftBtn.className = "o_hudson_ai_chatter_btn draft";
            draftBtn.title = "Draft a message with AI assistance";
            draftBtn.innerHTML = "✏️ Draft with AI";
            draftBtn.addEventListener("click", () =>
                handleDraft(chatterEl, draftBtn)
            );

            btnContainer.appendChild(sumBtn);
            btnContainer.appendChild(draftBtn);
            toolbar.appendChild(btnContainer);
        });
    });
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }
}
async function handleSummarize(chatterEl, btn) {
    // Extract model/id from the nearest form view
    const { resModel, resId } = getChatterContext(chatterEl);
    if (!resModel || !resId) {
        showNotification("Could not determine the current record.", "warning");
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="o_ai_spinner dark"></span> Summarizing…';

    try {
        const result = await callRpc("/hudson_ai/summarize_chatter", {
            model_name: resModel,
            record_id: resId,
        });
        const content = result.summary || result.error || "No summary generated.";
        showSummaryDialog(content);
    } catch (err) {
        showNotification(`Summary failed: ${err.message || err}`, "danger");
    } finally {
        btn.disabled = false;
        btn.innerHTML = "✦ Summarize";
    }
}

async function handleDraft(chatterEl, btn) {
    const { resModel, resId } = getChatterContext(chatterEl);
    if (!resModel || !resId) {
        showNotification("Could not determine the current record.", "warning");
        return;
    }
    showDraftPromptDialog(resModel, resId);
}

function getChatterContext(chatterEl) {
    let resModel = "";
    let resId = 0;
    
    // 1. Aggressively search up the DOM tree for any OWL component with the record context
    try {
        let currentEl = chatterEl;
        while (currentEl && currentEl.tagName !== "BODY") {
            if (currentEl.__owl__) {
                const comp = currentEl.__owl__.component || (currentEl.__owl__.bdom && currentEl.__owl__.bdom.component);
                const props = comp && comp.props ? comp.props : null;
                
                if (props) {
                    // Check various known prop structures for model/id
                    if (props.thread && props.thread.model) {
                        resModel = props.thread.model;
                        resId = props.thread.id;
                        break;
                    } else if (props.record && props.record.resModel) {
                        resModel = props.record.resModel;
                        resId = props.record.resId;
                        break;
                    } else if (props.resModel) {
                        resModel = props.resModel;
                        resId = props.resId || 0;
                        break;
                    } else if (props.action && props.action.res_model) {
                        resModel = props.action.res_model;
                        resId = props.action.res_id || 0;
                        break;
                    }
                }
            }
            currentEl = currentEl.parentElement;
        }
    } catch (e) {
        console.warn("Failed to walk OWL component tree", e);
    }

    // 2. Fallback to dataset attributes (Odoo 15/16)
    if (!resModel || !resId) {
        const closestModel = chatterEl.closest("[data-model]");
        resModel = (closestModel && closestModel.dataset.model) || chatterEl.dataset.model || "";
        
        const closestResId = chatterEl.closest("[data-res-id]");
        resId = parseInt((closestResId && closestResId.dataset.resId) || chatterEl.dataset.resId || "0") || 0;
    }

    // 3. Fallback to global tracker (URL / History State)
    if (!resModel || !resId) {
        resModel = resModel || window.__lastResModel || "";
        resId = resId || window.__lastResId || 0;
    }

    return { resModel, resId };
}

// ── Utility: plain JSON-RPC call without OWL useService ──────────────────────

async function callRpc(route, params) {
    const resp = await fetch(route, {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
            jsonrpc: "2.0",
            method: "call",
            id: Date.now(),
            params: params,
        }),
    });
    const data = await resp.json();
    if (data.error) {
        const msg = data.error.data ? data.error.data.message : data.error.message;
        throw new Error(msg);
    }
    return data.result;
}

// ── DOM-based modal helpers ───────────────────────────────────────────────────

function showSummaryDialog(content) {
    const overlay = document.createElement("div");
    overlay.className = "o_ai_summary_overlay";
    overlay.innerHTML = `
        <div class="o_ai_summary_card">
            <div class="o_ai_summary_card_header">
                <h4>✦ AI Chatter Summary</h4>
                <button class="o_ai_summary_card_close">×</button>
            </div>
            <div class="o_ai_summary_card_body">${escapeHtml(content)}</div>
            <div class="o_ai_summary_card_footer">
                <button class="btn btn-secondary">Close</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.querySelector(".o_ai_summary_card_close").addEventListener("click", close);
    overlay.querySelector(".btn-secondary").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
}

function showDraftPromptDialog(resModel, resId) {
    const overlay = document.createElement("div");
    overlay.className = "o_ai_draft_prompt_overlay";
    overlay.innerHTML = `
        <div class="o_ai_draft_prompt_card">
            <div class="o_ai_draft_prompt_header">✏️ Draft with AI</div>
            <div class="o_ai_draft_prompt_body">
                <label>What should the message say?</label>
                <textarea class="o_ai_draft_prompt_input"
                          placeholder="e.g. Politely follow up on the pending invoice..."></textarea>
            </div>
            <div class="o_ai_draft_prompt_footer">
                <button class="btn btn-secondary" id="ai-draft-cancel">Cancel</button>
                <button class="btn btn-primary" id="ai-draft-generate">Generate Draft</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    const textarea = overlay.querySelector("textarea");
    setTimeout(() => textarea && textarea.focus(), 50);

    const close = () => overlay.remove();
    overlay.querySelector("#ai-draft-cancel").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    const generateBtn = overlay.querySelector("#ai-draft-generate");
    const doGenerate = async () => {
        const instruction = textarea.value.trim();
        if (!instruction) return;
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span class="o_ai_spinner"></span> Generating…';

        try {
            const result = await callRpc("/hudson_ai/draft_email", {
                model_name: resModel,
                record_id: resId,
                instruction,
            });
            const draft = result.draft || result.error || "";
            close();
            if (draft) {
                fillComposer(draft);
                showNotification("✦ AI draft generated!", "success");
            }
        } catch (err) {
            generateBtn.disabled = false;
            generateBtn.innerHTML = "Generate Draft";
            showNotification(`Draft failed: ${err.message || err}`, "danger");
        }
    };

    generateBtn.addEventListener("click", doGenerate);
    textarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doGenerate(); }
    });
}

function fillComposer(text) {
    // Click "Send message" to open the composer
    const sendBtn = document.querySelector(
        ".o-mail-Chatter-sendMessage, .o_ChatterTopbar_sendMessageButton"
    );
    if (sendBtn) sendBtn.click();

    setTimeout(() => {
        const composer = document.querySelector(
            ".o-mail-Composer .o-mail-Composer-input, " +
            ".o-mail-Composer [contenteditable='true'], " +
            ".o_Composer_textInput"
        );
        if (!composer) return;
        if (composer.tagName === "TEXTAREA" || composer.tagName === "INPUT") {
            composer.value = text;
            composer.dispatchEvent(new Event("input", { bubbles: true }));
        } else {
            composer.innerText = text;
            composer.dispatchEvent(new InputEvent("input", { bubbles: true }));
        }
    }, 250);
}

function showNotification(message, type = "info") {
    // Use Odoo's notification if available
    const env = window.__owl_app_env__;
    if (env && env.services && env.services.notification) {
        env.services.notification.add(message, { type });
        return;
    }
    // Fallback: visible browser alert for critical messages so it's not silent!
    alert("[Hudson AI] " + message);
}

function escapeHtml(text) {
    return (text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/\n/g, "<br>");
}

// ── Track current record for context ─────────────────────────────────────────

function trackCurrentRecord() {
    // 1. Passive Network Interceptor (Bulletproof for Odoo 19)
    // Intercept both Fetch and XHR (Odoo uses XHR for its RPC service)
    const interceptBody = (bodyStr) => {
        try {
            if (typeof bodyStr !== 'string') return;
            const threadModelMatch = bodyStr.match(/"thread_model"\s*:\s*"([a-z0-9_.]+)"/);
            const threadIdMatch = bodyStr.match(/"thread_id"\s*:\s*(\d+)/);
            if (threadModelMatch && threadIdMatch) {
                window.__lastResModel = threadModelMatch[1];
                window.__lastResId = parseInt(threadIdMatch[1]);
            } else {
                const resModelMatch = bodyStr.match(/"res_model"\s*:\s*"([a-z0-9_.]+)"/);
                const resIdMatch = bodyStr.match(/"res_id"\s*:\s*(\d+)/);
                if (resModelMatch && resIdMatch) {
                    const m = resModelMatch[1];
                    if (!m.startsWith('mail.') && !m.startsWith('ir.')) {
                        window.__lastResModel = m;
                        window.__lastResId = parseInt(resIdMatch[1]);
                    }
                }
            }
        } catch (e) {}
    };

    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
        if (args[1] && args[1].body) interceptBody(args[1].body);
        return originalFetch.apply(this, args);
    };

    const originalXHRSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function(body) {
        if (body) interceptBody(body);
        return originalXHRSend.apply(this, arguments);
    };

    // 2. URL and History changes for Odoo 16/17/18 compatibility
    let lastUrl = "";
    setInterval(() => {
        const url = window.location.href;
        if (url === lastUrl) return;
        lastUrl = url;
        
        // Hash parameters
        const hash = window.location.hash;
        const modelMatch = hash.match(/[?&]model=([^&]+)/);
        const idMatch = hash.match(/[?&]id=(\d+)/);
        if (modelMatch) window.__lastResModel = decodeURIComponent(modelMatch[1]);
        if (idMatch) window.__lastResId = parseInt(idMatch[1]);
        
        // History state
        const state = window.history.state;
        if (state) {
            if (state.model) window.__lastResModel = state.model;
            else if (state.res_model) window.__lastResModel = state.res_model;
            if (state.id) window.__lastResId = parseInt(state.id);
            else if (state.res_id) window.__lastResId = parseInt(state.res_id);
        }
    }, 500);
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    injectAIButtonsIntoChatter();
    trackCurrentRecord();
});

// Also run immediately in case DOMContentLoaded already fired
injectAIButtonsIntoChatter();
trackCurrentRecord();
