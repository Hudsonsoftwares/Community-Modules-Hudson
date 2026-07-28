/** @odoo-module **/

/**
 * Hudson AI Assistant — Pure DOM Navbar Integration & Chat Panel
 * 
 * Bypasses the OWL component registry to ensure maximum compatibility across
 * Odoo versions (16, 17, 18, 19). It injects the systray button via MutationObserver
 * and manages the chat UI independently.
 */

const AI_QUICK_ACTIONS = [
    { label: "📊 Sales Summary", prompt: "Give me a summary of sales orders this month. Show total amounts and top customers." },
    { label: "👥 Top Employees", prompt: "Who are the most active employees? Check timesheets or tasks." },
    { label: "📦 Low Stock", prompt: "Show me products with low stock levels (below reorder point)." },
    { label: "💼 Create Lead", prompt: "Help me create a new CRM lead. Ask me for the details." }
];

let conversationHistory = [];
let isPanelOpen = false;
let isWaitingForReply = false;
let chatPanelContainer = null;

// ─── JSON RPC Helper ─────────────────────────────────────────────────────────

async function callChatRpc(route, params) {
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

// ─── UI Builders ─────────────────────────────────────────────────────────────

function createSystrayButton() {
    const btn = document.createElement("div");
    btn.className = "o_hudson_ai_systray";
    btn.innerHTML = `
        <button class="o_hudson_ai_systray_btn" title="Hudson AI Assistant">
            <span class="ai-icon">✦</span>
            <span>Ask AI</span>
        </button>
    `;
    btn.addEventListener("click", toggleChatPanel);
    return btn;
}

function buildChatPanelDOM() {
    const panel = document.createElement("div");
    panel.className = "o_hudson_ai_panel";
    panel.style.display = "none";
    
    // Header
    const header = document.createElement("div");
    header.className = "o_ai_panel_header";
    header.innerHTML = `
        <div class="o_ai_panel_header_icon">✦</div>
        <div class="o_ai_panel_header_info">
            <div class="o_ai_panel_header_title">Hudson AI</div>
            <div class="o_ai_panel_header_subtitle">Enterprise Assistant</div>
        </div>
        <div class="o_ai_panel_header_actions">
            <button class="o_ai_panel_header_btn" id="ai-btn-clear" title="Clear conversation"><i class="fa fa-trash-o"></i></button>
            <button class="o_ai_panel_header_btn" id="ai-btn-close" title="Close"><i class="fa fa-times"></i></button>
        </div>
    `;

    // Quick Actions
    const chips = document.createElement("div");
    chips.className = "o_ai_chips";
    AI_QUICK_ACTIONS.forEach(action => {
        const chip = document.createElement("button");
        chip.className = "o_ai_chip";
        chip.innerText = action.label;
        chip.addEventListener("click", () => sendMessage(action.prompt));
        chips.appendChild(chip);
    });

    // Messages Area
    const messagesArea = document.createElement("div");
    messagesArea.className = "o_ai_panel_messages";
    messagesArea.id = "ai-messages-area";
    
    // Welcome Screen
    const welcome = document.createElement("div");
    welcome.className = "o_ai_welcome";
    welcome.id = "ai-welcome-screen";
    welcome.innerHTML = `
        <div class="o_ai_welcome_icon">✦</div>
        <h3>Hello! I'm Hudson AI</h3>
        <p>Ask me anything — I can search your database, create records, generate reports, and more. Try the quick actions above or type your own request.</p>
    `;
    messagesArea.appendChild(welcome);

    // Input Area
    const inputArea = document.createElement("div");
    inputArea.className = "o_ai_panel_input";
    
    const textarea = document.createElement("textarea");
    textarea.className = "o_ai_input_box";
    textarea.id = "ai-input-box";
    textarea.placeholder = "Ask anything — create a lead, check stock, find employees...";
    textarea.rows = 1;

    const actionsDiv = document.createElement("div");
    actionsDiv.className = "o_ai_input_actions";
    
    const micBtn = document.createElement("button");
    micBtn.className = "o_ai_btn_icon o_ai_btn_mic";
    micBtn.id = "ai-btn-mic";
    micBtn.title = "Speak";
    micBtn.innerHTML = `<i class="fa fa-microphone"></i>`;

    const sendBtn = document.createElement("button");
    sendBtn.className = "o_ai_btn_icon o_ai_btn_send";
    sendBtn.id = "ai-btn-send";
    sendBtn.title = "Send";
    sendBtn.innerHTML = `<i class="fa fa-paper-plane"></i>`;

    actionsDiv.appendChild(micBtn);
    actionsDiv.appendChild(sendBtn);
    inputArea.appendChild(textarea);
    inputArea.appendChild(actionsDiv);

    // Assembly
    panel.appendChild(header);
    panel.appendChild(chips);
    panel.appendChild(messagesArea);
    panel.appendChild(inputArea);

    document.body.appendChild(panel);
    return panel;
}

// ─── Chat Logic ──────────────────────────────────────────────────────────────

function toggleChatPanel() {
    if (!chatPanelContainer) {
        chatPanelContainer = buildChatPanelDOM();
        bindPanelEvents();
    }
    
    isPanelOpen = !isPanelOpen;
    chatPanelContainer.style.display = isPanelOpen ? "flex" : "none";
    
    if (isPanelOpen) {
        const input = document.getElementById("ai-input-box");
        if (input) input.focus();
    }
}

function bindPanelEvents() {
    document.getElementById("ai-btn-close").addEventListener("click", toggleChatPanel);
    document.getElementById("ai-btn-clear").addEventListener("click", clearConversation);
    
    const sendBtn = document.getElementById("ai-btn-send");
    const micBtn = document.getElementById("ai-btn-mic");
    const input = document.getElementById("ai-input-box");
    
    sendBtn.addEventListener("click", () => sendMessage(input.value));
    
    if (micBtn) {
        micBtn.addEventListener("click", () => toggleSpeechRecognition(micBtn, input));
        // Check if supported
        if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
            micBtn.style.display = "none";
        }
    }

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage(input.value);
        }
    });
}

let recognition = null;
let isRecording = false;

function toggleSpeechRecognition(btn, inputEl) {
    if (isRecording) {
        if (recognition) recognition.stop();
        return;
    }
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    
    recognition.onstart = () => {
        isRecording = true;
        btn.classList.add("recording");
        inputEl.placeholder = "Listening...";
    };
    
    recognition.onresult = (event) => {
        let finalTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
            }
        }
        if (finalTranscript) {
            const currentVal = inputEl.value;
            inputEl.value = currentVal ? currentVal + " " + finalTranscript : finalTranscript;
        }
    };
    
    recognition.onerror = (e) => {
        console.error("Speech recognition error", e);
        stopRecordingUI(btn, inputEl);
    };
    
    recognition.onend = () => stopRecordingUI(btn, inputEl);
    
    recognition.start();
}

function stopRecordingUI(btn, inputEl) {
    isRecording = false;
    btn.classList.remove("recording");
    inputEl.placeholder = "Ask anything — create a lead, check stock, find employees...";
}

function clearConversation() {
    conversationHistory = [];
    const area = document.getElementById("ai-messages-area");
    if (area) {
        area.innerHTML = `
            <div class="o_ai_welcome" id="ai-welcome-screen">
                <div class="o_ai_welcome_icon">✦</div>
                <h3>Conversation Cleared</h3>
                <p>How can I help you next?</p>
            </div>
        `;
    }
}

function escapeHtml(text) {
    return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/\n/g, "<br>");
}

function appendMessageDOM(role, content) {
    const area = document.getElementById("ai-messages-area");
    const welcome = document.getElementById("ai-welcome-screen");
    if (welcome) welcome.style.display = "none";

    const row = document.createElement("div");
    row.className = `o_ai_msg_row ${role}`;
    
    let avatarHTML = "";
    if (role === "assistant") {
        avatarHTML = `<div class="o_ai_msg_avatar">✦</div>`;
    }

    // Convert markdown bold to strong tags for better display
    let formattedContent = escapeHtml(content);
    formattedContent = formattedContent.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    row.innerHTML = `
        ${avatarHTML}
        <div class="o_ai_msg_bubble">${formattedContent}</div>
    `;
    
    area.appendChild(row);
    area.scrollTop = area.scrollHeight;
}

function showTypingIndicator() {
    const area = document.getElementById("ai-messages-area");
    const typingRow = document.createElement("div");
    typingRow.className = "o_ai_typing";
    typingRow.id = "ai-typing-indicator";
    typingRow.innerHTML = `
        <div class="o_ai_msg_avatar">✦</div>
        <div class="o_ai_typing_dots">
            <div class="o_ai_typing_dot"></div>
            <div class="o_ai_typing_dot"></div>
            <div class="o_ai_typing_dot"></div>
        </div>
    `;
    area.appendChild(typingRow);
    area.scrollTop = area.scrollHeight;
}

function hideTypingIndicator() {
    const typing = document.getElementById("ai-typing-indicator");
    if (typing) typing.remove();
}

async function sendMessage(text) {
    text = text.trim();
    if (!text || isWaitingForReply) return;

    // Clear input
    const input = document.getElementById("ai-input-box");
    if (input) input.value = "";

    // Show user message
    appendMessageDOM("user", text);
    conversationHistory.push({ role: "user", content: text });

    // UI state
    isWaitingForReply = true;
    const sendBtn = document.getElementById("ai-btn-send");
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.innerHTML = `<span class="o_ai_spinner"></span>`;
    }
    showTypingIndicator();

    try {
        const result = await callChatRpc("/hudson_ai/chat", {
            user_message: text,
            conversation_history: conversationHistory.slice(0, -1) // Exclude the message we just pushed, backend handles it
        });

        hideTypingIndicator();
        
        if (result.error) {
            appendMessageDOM("assistant", `Error: ${result.error}`);
            // Don't push error to history so user can retry
        } else {
            const reply = result.reply || "No response received.";
            appendMessageDOM("assistant", reply);
            conversationHistory.push({ role: "assistant", content: reply });
        }
    } catch (err) {
        hideTypingIndicator();
        appendMessageDOM("assistant", `Failed to send message: ${err.message}`);
    } finally {
        isWaitingForReply = false;
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = `<i class="fa fa-paper-plane"></i>`;
        }
    }
}

// ─── Injection ───────────────────────────────────────────────────────────────

function injectNavbarButton() {
    const observer = new MutationObserver(() => {
        // Look for the navbar right-side menu container (systray)
        const systray = document.querySelector(".o_menu_systray, .o_navbar_apps_menu, .o-mail-Systray");
        if (!systray || systray.dataset.hudsonAiInjected) return;
        
        systray.dataset.hudsonAiInjected = "1";
        
        const btn = createSystrayButton();
        // Prepend it so it appears before the user profile / debug icons
        systray.insertBefore(btn, systray.firstChild);
    });
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }
}

document.addEventListener("DOMContentLoaded", injectNavbarButton);
injectNavbarButton();
