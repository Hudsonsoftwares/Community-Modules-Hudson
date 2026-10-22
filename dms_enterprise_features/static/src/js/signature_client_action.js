/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, proxy, signal, useProps, t, onMounted, onWillUnmount, onPatched } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { loadPDFJSAssets } from "@web/core/utils/pdfjs";
import { Dialog } from "@web/core/dialog/dialog";

// -----------------------------------------------------------------------------
// Send Dialog Component
// -----------------------------------------------------------------------------
export class SignatureSendDialog extends Component {
    static template = "dms_enterprise_features.SignatureSendDialog";
    static components = { Dialog };
    props = useProps({
        close: t.function().optional(),
        title: t.any().optional(),
        defaultSubject: t.any().optional(),
        rolesWithFields: t.any().optional(),
        roles: t.any().optional(),
        isSignNow: t.any().optional(),
        onConfirm: t.function().optional(),
    });

    setup() {
        this.orm = useService("orm");
        const useStateHook = proxy || (typeof owl !== "undefined" && (owl.proxy || owl.useState)) || (typeof useState === "function" ? useState : (obj => obj));
        this.state = useStateHook({
            subject: this.props.defaultSubject || "Signature Request",
            message: "",
            cc: "",
            roleUserMap: {},
            validUntil: "",
            reminders: false,
            reminderDays: 7,
            hideCertificateKey: false,
            signingOrder: false
        });
    }

    onUserChange(roleId, userId) {
        this.state.roleUserMap[roleId] = userId ? userId.trim() : false;
    }

    async onConfirm() {
        // Validate
        for (const roleId of this.props.rolesWithFields) {
            if (!this.state.roleUserMap[roleId]) {
                alert("Please assign a user for all active roles before sending.");
                return;
            }
        }

        await this.props.onConfirm({
            subject: this.state.subject,
            message: this.state.message,
            cc: this.state.cc,
            roleUserMap: this.state.roleUserMap,
            validUntil: this.state.validUntil,
            reminders: this.state.reminders,
            reminderDays: this.state.reminderDays,
            hideCertificateKey: this.state.hideCertificateKey,
            signingOrder: this.state.signingOrder
        });
        this.props.close();
    }
}

// -----------------------------------------------------------------------------
// Role Color Palette (Consistent with Modern Signature Standards)
// -----------------------------------------------------------------------------
export const ROLE_PALETTE = [
    { color: "#d1fae5", borderColor: "#10b981", textColor: "#065f46", name: "Emerald" },
    { color: "#fef3c7", borderColor: "#f59e0b", textColor: "#92400e", name: "Amber" },
    { color: "#e0e7ff", borderColor: "#6366f1", textColor: "#3730a3", name: "Indigo" },
    { color: "#fce7f3", borderColor: "#ec4899", textColor: "#9d174d", name: "Rose" },
    { color: "#e0f2fe", borderColor: "#0ea5e9", textColor: "#075985", name: "Sky" },
    { color: "#ffedd5", borderColor: "#f97316", textColor: "#9a3412", name: "Orange" },
    { color: "#f3e8ff", borderColor: "#a855f7", textColor: "#6b21a8", name: "Purple" },
    { color: "#ccfbf1", borderColor: "#14b8a6", textColor: "#115e59", name: "Teal" },
];

// -----------------------------------------------------------------------------
// Signer Settings Dialog Component
// -----------------------------------------------------------------------------
export class SignerSettingsDialog extends Component {
    static template = "dms_enterprise_features.SignerSettingsDialog";
    static components = { Dialog };
    props = useProps({
        close: t.function().optional(),
        role: t.any().optional(),
        onConfirm: t.function().optional(),
    });

    setup() {
        this.palette = ROLE_PALETTE;
        this.state = proxy({
            name: this.props.role.name || "",
            authMethod: this.props.role.authMethod || "none",
            canDelegate: this.props.role.canDelegate || false,
            color: this.props.role.color || ROLE_PALETTE[0].color,
            borderColor: this.props.role.borderColor || ROLE_PALETTE[0].borderColor,
            textColor: this.props.role.textColor || ROLE_PALETTE[0].textColor,
        });
    }

    selectPalette(theme) {
        this.state.color = theme.color;
        this.state.borderColor = theme.borderColor;
        this.state.textColor = theme.textColor;
    }

    onConfirm() {
        this.props.onConfirm({
            name: this.state.name,
            authMethod: this.state.authMethod,
            canDelegate: this.state.canDelegate,
            color: this.state.color,
            borderColor: this.state.borderColor,
            textColor: this.state.textColor,
        });
        this.props.close();
    }
}


// -----------------------------------------------------------------------------
// Main Signature Editor Component
// -----------------------------------------------------------------------------
export class DmsSignaturePdfViewer extends Component {
    static template = "dms_enterprise_features.SignatureClientAction";
    props = useProps({
        action: t.any().optional(),
        className: t.any().optional(),
    });

    docUploadInputRef = signal.ref();

    get pdfContainer() {
        return { el: document.querySelector(".o_dms_sign_viewport") };
    }

    get docUploadInput() {
        return { el: this.docUploadInputRef() };
    }

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.state = proxy({
            documents: [],
            currentDocIndex: 0,
            currentDocument: null,

            roles: [
                {
                    id: "signer1",
                    name: "Signer 1",
                    color: ROLE_PALETTE[0].color,
                    borderColor: ROLE_PALETTE[0].borderColor,
                    textColor: ROLE_PALETTE[0].textColor,
                    authMethod: "none",
                    canDelegate: false
                }
            ],
            currentRoleIndex: 0,

            tools: [
                { type: "signature", label: "Signature", icon: "fa-pencil", span: false },
                { type: "initials", label: "Initials", icon: "fa-font", span: false },
                { type: "name", label: "Name", icon: "fa-user", span: false },
                { type: "email", label: "Email", icon: "fa-envelope", span: false },
                { type: "phone", label: "Phone", icon: "fa-phone", span: false },
                { type: "company", label: "Company", icon: "fa-building", span: false },
                { type: "text", label: "Text", icon: "fa-font", span: false },
                { type: "multiline", label: "Multiline", icon: "fa-align-left", span: false },
                { type: "checkbox", label: "Checkbox", icon: "fa-check-square-o", span: false },
                { type: "radio", label: "Radio", icon: "fa-dot-circle-o", span: false },
                { type: "selection", label: "Selection", icon: "fa-caret-down", span: false },
                { type: "date", label: "Date", icon: "fa-calendar", span: false },
                { type: "strikethrough", label: "Strikethrough", icon: "fa-strikethrough", span: false },
                { type: "stamp", label: "Stamp", icon: "fa-legal", span: false }
            ],

            pages: [],
            zoomLevel: 100,

            // Drag state
            dragType: null,
            mouseX: 0,
            mouseY: 0,

            boxDragId: null,
            boxResizeId: null,
            editingBoxId: null, // For properties popover
            dragStartX: 0,
            dragStartY: 0,
            boxStartRect: null,

            needsRender: false,
            isLoading: false,
            errorMessage: false,

            allUsers: [],
            openDropdownRoleId: null,
        });

        this.onOutsidePointerDown = (e) => {
            if (this.state.openDropdownRoleId && !e.target.closest('.o_signer_menu_toggle') && !e.target.closest('.o_signer_dropdown_menu')) {
                this.state.openDropdownRoleId = null;
            }
            if (this.state.editingBoxId) {
                if (!e.target.closest('.o_dms_box_popover') && !e.target.closest('.signature-box')) {
                    this.state.editingBoxId = null;
                }
            }
        };

        this.onWindowMouseMoveBound = this.onWindowMouseMove.bind(this);
        this.onWindowMouseUpBound = this.onWindowMouseUp.bind(this);

        onMounted(async () => {
            // Mouse tracking & outside click listeners (capture phase ensures no child can block them)
            window.addEventListener('mousemove', this.onWindowMouseMoveBound);
            window.addEventListener('mouseup', this.onWindowMouseUpBound);
            window.addEventListener('pointerdown', this.onOutsidePointerDown, true);
            window.addEventListener('click', this.onOutsidePointerDown, true);

            // Load PDF.js assets properly
            try {
                await loadPDFJSAssets();
                const pdfLib = window.pdfjsLib || globalThis.pdfjsLib;
                if (pdfLib?.GlobalWorkerOptions) {
                    pdfLib.GlobalWorkerOptions.workerSrc = "/web/static/lib/pdfjs/build/pdf.worker.js";
                }
            } catch (e) {
                console.error("Failed to load PDF.js", e);
            }

            // Fetch initial data
            await this.loadInitialData();
        });

        onPatched(() => {
            if (this.state.needsRender) {
                this.state.needsRender = false;
                this.renderAllPages();
            }
        });

        onWillUnmount(() => {
            window.removeEventListener('mousemove', this.onWindowMouseMoveBound);
            window.removeEventListener('mouseup', this.onWindowMouseUpBound);
            window.removeEventListener('pointerdown', this.onOutsidePointerDown, true);
            window.removeEventListener('click', this.onOutsidePointerDown, true);
        });
    }

    onActionClick(e) {
        if (this.state.editingBoxId && !e.target.closest('.o_dms_box_popover') && !e.target.closest('.signature-box')) {
            this.state.editingBoxId = null;
        }
    }

    onViewportClick(e) {
        if (this.state.editingBoxId && !e.target.closest('.o_dms_box_popover') && !e.target.closest('.signature-box')) {
            this.state.editingBoxId = null;
        }
    }

    getAction() {
        return this.props?.action || this.env?.config?.action || {};
    }

    async onBack() {
        const action = this.getAction();
        let fileId = action.context?.default_file_id;
        if (!fileId && this.state.documents.length > 0) {
            const revId = this.state.documents[0].id;
            try {
                const records = await this.orm.read("dms.file.revision", [revId], ["file_id"]);
                if (records && records.length && records[0].file_id) {
                    fileId = records[0].file_id[0];
                }
            } catch (e) {
                console.warn("Could not fetch file_id", e);
            }
        }
        if (fileId) {
            return this.env.services.action.doAction({
                type: "ir.actions.act_window",
                res_model: "dms.file",
                res_id: fileId,
                views: [[false, "form"]],
                target: "current"
            });
        }
        return this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dms.file",
            views: [[false, "kanban"], [false, "list"]],
            target: "current"
        });
    }

    async loadInitialData() {
        // Load default documents from context
        const action = this.getAction();
        const context = action.context || this.env?.searchModel?.context || {};
        const defaultRevIds = context.default_revision_ids || context.default_revision_id;

        if (!defaultRevIds) {
            return this.onBack();
        }

        const revIds = typeof defaultRevIds === "string" ? defaultRevIds.split(',').map(Number) : [defaultRevIds];
        const records = await this.orm.read("dms.file.revision", revIds, ["id", "file_name", "content"], { context: { bin_size: false } });

        if (!records || records.length === 0) {
            return this.onBack();
        }

        this.state.documents = records.map(r => {
            let base64 = r.content;
            if (base64 && typeof base64 === 'object' && base64.content) {
                base64 = base64.content;
            }
            return {
                id: r.id,
                name: r.file_name,
                content: typeof base64 === 'string' ? base64 : false,
                items: [] // array of boxes
            };
        });

        if (this.state.documents.length > 0) {
            await this.selectDocument(0);
        }

        // Fetch all users for assignment
        const users = await this.orm.searchRead("res.users", [], ["id", "name"]);
        this.state.allUsers = users;
    }

    async selectDocument(index) {
        this.state.currentDocIndex = index;
        this.state.currentDocument = this.state.documents[index];
        this.state.editingBoxId = null;

        if (this.state.currentDocument) {
            await this.renderPDFDocument(this.state.currentDocument);
        }
    }

    selectRole(index) {
        this.state.currentRoleIndex = index;
    }

    toggleRoleDropdown(roleId) {
        this.state.openDropdownRoleId = this.state.openDropdownRoleId === roleId ? null : roleId;
    }

    editRoleAndClose(roleId) {
        this.state.openDropdownRoleId = null;
        this.editRole(roleId);
    }

    deleteRoleAndClose(roleId) {
        this.state.openDropdownRoleId = null;
        this.deleteRole(roleId);
    }

    editRole(roleId) {
        const role = this.state.roles.find(r => r.id === roleId);
        if (!role) return;

        this.dialog.add(SignerSettingsDialog, {
            role: role,
            onConfirm: (data) => {
                role.name = data.name;
                role.authMethod = data.authMethod;
                role.canDelegate = data.canDelegate;
                if (data.color) role.color = data.color;
                if (data.borderColor) role.borderColor = data.borderColor;
                if (data.textColor) role.textColor = data.textColor;
            }
        });
    }

    deleteRole(roleId) {
        // Remove the role
        this.state.roles = this.state.roles.filter(r => r.id !== roleId);

        // Remove all fields assigned to this role
        for (const doc of this.state.documents) {
            doc.items = doc.items.filter(i => i.roleId !== roleId);
        }

        // Fix currentRoleIndex if needed
        if (this.state.currentRoleIndex >= this.state.roles.length) {
            this.state.currentRoleIndex = Math.max(0, this.state.roles.length - 1);
        }
    }

    onAddRole() {
        const nextIdx = this.state.roles.length + 1;
        const theme = ROLE_PALETTE[(nextIdx - 1) % ROLE_PALETTE.length];
        this.state.roles.push({
            id: `signer${nextIdx}`,
            name: `Signer ${nextIdx}`,
            color: theme.color,
            borderColor: theme.borderColor,
            textColor: theme.textColor,
            authMethod: "none",
            canDelegate: false
        });
        this.state.currentRoleIndex = this.state.roles.length - 1;
    }

    onAddDocument() {
        this.docUploadInput.el.click();
    }

    zoomIn() {
        this.setZoom(Math.min(300, (this.state.zoomLevel || 100) + 15));
    }

    zoomOut() {
        this.setZoom(Math.max(30, (this.state.zoomLevel || 100) - 15));
    }

    setZoom(val) {
        let newZoom = Math.round(val);
        if (isNaN(newZoom) || newZoom < 30) newZoom = 30;
        if (newZoom > 300) newZoom = 300;
        if (newZoom === this.state.zoomLevel) return;

        const ratio = newZoom / (this.state.zoomLevel || 100);
        this.state.zoomLevel = newZoom;

        if (this.state.currentDocument) {
            for (const item of this.state.currentDocument.items) {
                item.x = Math.round(item.x * ratio);
                item.y = Math.round(item.y * ratio);
                item.width = Math.round(item.width * ratio);
                item.height = Math.round(item.height * ratio);
            }
        }

        if (this.pdfDoc) {
            this.state.pages = [];
            const pagesList = [];
            for (let i = 1; i <= this.pdfDoc.numPages; i++) {
                this.pdfDoc.getPage(i).then(page => {
                    const scale = this.state.zoomLevel / 100;
                    const viewport = page.getViewport({ scale });
                    pagesList.push({
                        num: i,
                        width: viewport.width,
                        height: viewport.height
                    });
                    if (pagesList.length === this.pdfDoc.numPages) {
                        pagesList.sort((a, b) => a.num - b.num);
                        this.state.pages = pagesList;
                        this.state.needsRender = true;
                    }
                });
            }
        }
    }

    onZoomChange(e) {
        let val = parseInt(e.target.value);
        this.setZoom(val);
    }

    async onDocumentUpload(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async (ev) => {
            const base64Data = ev.target.result.split(',')[1];

            // Create a temporary file record via ORM
            const fileId = await this.orm.create("dms.file", [{
                name: file.name,
                content: base64Data
            }]);

            const fileRec = await this.orm.read("dms.file", fileId, ["current_revision_id"]);
            const revId = fileRec[0].current_revision_id[0];

            this.state.documents.push({
                id: revId,
                name: file.name,
                content: base64Data,
                items: []
            });
            await this.selectDocument(this.state.documents.length - 1);
        };
        reader.readAsDataURL(file);
    }

    async renderPDFDocument(doc) {
        this.state.isLoading = true;
        this.state.errorMessage = false;
        try {
            await loadPDFJSAssets();
            const pdfLib = window.pdfjsLib || globalThis.pdfjsLib;
            if (!pdfLib) {
                throw new Error("PDF.js engine is unavailable");
            }
            if (pdfLib.GlobalWorkerOptions && !pdfLib.GlobalWorkerOptions.workerSrc) {
                pdfLib.GlobalWorkerOptions.workerSrc = "/web/static/lib/pdfjs/build/pdf.worker.js";
            }

            let loadingTask = null;
            let base64Str = doc.content;
            if (base64Str && typeof base64Str === "string" && base64Str.length > 50) {
                if (base64Str.includes(",")) {
                    base64Str = base64Str.split(",")[1];
                }
                const binaryString = window.atob(base64Str);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                loadingTask = pdfLib.getDocument({
                    data: bytes,
                    cMapUrl: '/web/static/lib/pdfjs/build/pdf.js/web/cmaps/',
                    cMapPacked: true,
                    standardFontDataUrl: '/web/static/lib/pdfjs/build/pdf.js/web/standard_fonts/',
                });
            } else if (doc.id) {
                loadingTask = pdfLib.getDocument({
                    url: `/web/content/dms.file.revision/${doc.id}/content`,
                    cMapUrl: '/web/static/lib/pdfjs/build/pdf.js/web/cmaps/',
                    cMapPacked: true,
                    standardFontDataUrl: '/web/static/lib/pdfjs/build/pdf.js/web/standard_fonts/',
                });
            } else {
                throw new Error("No PDF data found for this document.");
            }

            this.pdfDoc = await loadingTask.promise;
            const pagesList = [];
            for (let i = 1; i <= this.pdfDoc.numPages; i++) {
                const page = await this.pdfDoc.getPage(i);
                const scale = (this.state.zoomLevel || 100) / 100;
                const viewport = page.getViewport({ scale });
                pagesList.push({
                    num: i,
                    width: viewport.width,
                    height: viewport.height
                });
            }
            this.state.pages = pagesList;
            this.state.isLoading = false;
            this.state.needsRender = true;
        } catch (err) {
            console.error("PDF render error:", err);
            this.state.isLoading = false;
            this.state.errorMessage = err.message || "Failed to render PDF preview.";
            if (this.notification) {
                this.notification.add("Could not load PDF document preview: " + (err.message || "Invalid format"), { type: "danger" });
            }
        }
    }

    async renderPDFFromBase64(base64) {
        return this.renderPDFDocument({
            id: this.state.currentDocument?.id,
            content: base64
        });
    }

    async renderAllPages() {
        if (!this.pdfDoc) return;
        if (!this.renderTasks) {
            this.renderTasks = {};
        }

        const outputScale = window.devicePixelRatio || 1;

        for (const pageInfo of this.state.pages) {
            const canvas = document.getElementById('pdf-canvas-' + pageInfo.num);
            if (!canvas) continue;

            if (this.renderTasks[pageInfo.num]) {
                try {
                    this.renderTasks[pageInfo.num].cancel();
                } catch (_) {}
            }

            try {
                const page = await this.pdfDoc.getPage(pageInfo.num);
                const scale = (this.state.zoomLevel || 100) / 100;
                const viewport = page.getViewport({ scale });

                canvas.width = Math.floor(viewport.width * outputScale);
                canvas.height = Math.floor(viewport.height * outputScale);
                canvas.style.width = Math.floor(viewport.width) + "px";
                canvas.style.height = Math.floor(viewport.height) + "px";

                const context = canvas.getContext('2d');
                const transform = outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;

                const renderContext = {
                    canvasContext: context,
                    transform: transform,
                    viewport: viewport
                };

                const renderTask = page.render(renderContext);
                this.renderTasks[pageInfo.num] = renderTask;
                await renderTask.promise;
            } catch (e) {
                if (e?.name !== "RenderingCancelledException") {
                    console.error("Canvas render error:", e);
                }
            }
        }
    }

    // --- Drag & Drop UI Logic ---
    startDrag(e, type) {
        e.preventDefault();
        this.state.dragType = type;
        this.state.mouseX = e.clientX;
        this.state.mouseY = e.clientY;
    }

    onWindowMouseMove(e) {
        if (this.state.dragType) {
            this.state.mouseX = e.clientX;
            this.state.mouseY = e.clientY;
        } else if (this.state.boxDragId && this.state.currentDocument) {
            const dx = e.clientX - this.state.dragStartX;
            const dy = e.clientY - this.state.dragStartY;
            const box = this.state.currentDocument.items.find(b => b.id === this.state.boxDragId);
            if (box) {
                let newX = this.state.boxStartRect.x + dx;
                let newY = this.state.boxStartRect.y + dy;

                const viewportEl = document.querySelector(".o_dms_sign_viewport");
                if (viewportEl) {
                    const pageEl = viewportEl.querySelector(`.pdf-page[data-page-num="${box.page}"], .o_dms_pdf_page[data-page-num="${box.page}"]`);
                    if (pageEl) {
                        const rect = pageEl.getBoundingClientRect();
                        newX = Math.min(Math.max(0, newX), rect.width - box.width);
                        newY = Math.min(Math.max(0, newY), rect.height - box.height);
                    }
                }

                box.x = newX;
                box.y = newY;
            }
        } else if (this.state.boxResizeId && this.state.currentDocument) {
            const dx = e.clientX - this.state.dragStartX;
            const dy = e.clientY - this.state.dragStartY;
            const box = this.state.currentDocument.items.find(b => b.id === this.state.boxResizeId);
            if (box) {
                let newW = this.state.boxStartRect.width + dx;
                let newH = this.state.boxStartRect.height + dy;

                const viewportEl = document.querySelector(".o_dms_sign_viewport");
                if (viewportEl) {
                    const pageEl = viewportEl.querySelector(`.pdf-page[data-page-num="${box.page}"], .o_dms_pdf_page[data-page-num="${box.page}"]`);
                    if (pageEl) {
                        const rect = pageEl.getBoundingClientRect();
                        newW = Math.min(newW, rect.width - box.x);
                        newH = Math.min(newH, rect.height - box.y);
                    }
                }

                if (box.type === 'checkbox' || box.type === 'radio') {
                    const size = Math.max(22, Math.max(newW, newH));
                    box.width = size;
                    box.height = size;
                } else {
                    box.width = Math.max(20, newW);
                    box.height = Math.max(15, newH);
                }
            }
        }
    }

    onWindowMouseUp(e) {
        if (this.state.boxDragId) {
            // End drag
            if (this.state.dragStartX === e.clientX && this.state.dragStartY === e.clientY) {
                // Was just a click, open properties
                this.state.editingBoxId = this.state.boxDragId;
            }
        }

        this.state.boxDragId = null;
        this.state.boxResizeId = null;

        if (!this.state.dragType) return;

        const type = this.state.dragType;
        this.state.dragType = null;

        const viewportEl = document.querySelector(".o_dms_sign_viewport");
        if (!viewportEl) return;

        const pageEls = viewportEl.querySelectorAll('.pdf-page, .o_dms_pdf_page');
        let targetPageNum = null;
        let targetRect = null;

        for (const pageEl of pageEls) {
            const rect = pageEl.getBoundingClientRect();
            if (e.clientX >= rect.left && e.clientX <= rect.right &&
                e.clientY >= rect.top && e.clientY <= rect.bottom) {
                targetPageNum = parseInt(pageEl.getAttribute('data-page-num'), 10);
                targetRect = rect;
                break;
            }
        }

        if (targetPageNum && targetRect && this.state.currentDocument) {
            const currentRole = this.currentRole;

            let defaultW = 160;
            let defaultH = 42;
            if (type === 'checkbox' || type === 'radio') {
                defaultW = 32;
                defaultH = 32;
            } else if (type === 'signature' || type === 'stamp') {
                defaultW = 180;
                defaultH = 50;
            } else if (type === 'multiline') {
                defaultW = 200;
                defaultH = 70;
            }

            let dropX = e.clientX - targetRect.left;
            let dropY = e.clientY - targetRect.top;

            dropX = Math.min(Math.max(0, dropX), targetRect.width - defaultW);
            dropY = Math.min(Math.max(0, dropY), targetRect.height - defaultH);

            if (type === 'radio') {
                const groupId = 'RadioGroup_' + Date.now();
                for (let i = 1; i <= 2; i++) {
                    let radioX = dropX + ((i - 1) * 42);
                    radioX = Math.min(Math.max(0, radioX), targetRect.width - defaultW);

                    this.state.currentDocument.items.push({
                        id: Date.now() + i,
                        type: type,
                        page: targetPageNum,
                        roleId: currentRole.id,
                        x: radioX,
                        y: dropY,
                        width: defaultW,
                        height: defaultH,
                        mandatory: true,
                        placeholder: this.getToolLabel(type),
                        alignment: 'left',
                        readonly: false,
                        radioGroupName: groupId,
                        radioOptionValue: 'Option ' + i
                    });
                }
            } else {
                const newBox = {
                    id: Date.now(),
                    type: type,
                    page: targetPageNum,
                    roleId: currentRole.id,
                    x: dropX,
                    y: dropY,
                    width: defaultW,
                    height: defaultH,
                    mandatory: true,
                    placeholder: this.getToolLabel(type),
                    alignment: 'left',
                    readonly: false,
                    radioGroupName: '',
                    radioOptionValue: ''
                };
                this.state.currentDocument.items.push(newBox);
            }
        }
    }

    startBoxDrag(e, box) {
        // Do not drag if clicking inside properties popover or control buttons
        if (e.target.closest('.o_dms_box_popover')) return;
        if (e.target.closest('.delete-box-btn') || e.target.closest('.resize-box-handle')) return;

        this.state.boxDragId = box.id;
        this.state.dragStartX = e.clientX;
        this.state.dragStartY = e.clientY;
        this.state.boxStartRect = { x: box.x, y: box.y };
    }

    startBoxResize(e, box) {
        this.state.boxResizeId = box.id;
        this.state.dragStartX = e.clientX;
        this.state.dragStartY = e.clientY;
        this.state.boxStartRect = { width: box.width, height: box.height };
    }

    deleteBox(boxId) {
        if (this.state.currentDocument) {
            this.state.currentDocument.items = this.state.currentDocument.items.filter(b => b.id !== boxId);
        }
        if (this.state.editingBoxId === boxId) {
            this.state.editingBoxId = null;
        }
    }

    duplicateBox(boxId) {
        const box = this.state.currentDocument.items.find(b => b.id === boxId);
        if (box && this.state.currentDocument) {
            const copy = JSON.parse(JSON.stringify(box));
            copy.id = Date.now();
            copy.x += 10;
            copy.y += 10;
            this.state.currentDocument.items.push(copy);
            this.state.editingBoxId = copy.id;
        }
    }

    closePopover() {
        this.state.editingBoxId = null;
    }

    // --- Helpers ---
    getCurrentBoxes(pageNum) {
        if (!this.state.currentDocument) return [];
        return this.state.currentDocument.items.filter(i => i.page === pageNum);
    }

    getRoleBoxCount(roleId) {
        let count = 0;
        for (const doc of this.state.documents) {
            count += doc.items.filter(i => i.roleId === roleId).length;
        }
        return count;
    }

    getToolIcon(type) {
        const tool = this.state.tools.find(t => t.type === type);
        return tool ? tool.icon : "fa-pencil";
    }

    getToolLabel(type) {
        const tool = this.state.tools.find(t => t.type === type);
        return tool ? tool.label : type;
    }

    getRadioGroupCount(groupName) {
        if (!this.state.currentDocument || !groupName) return 1;
        return this.state.currentDocument.items.filter(i => i.radioGroupName === groupName).length;
    }

    updateRadioGroupCount(groupName, newCountStr) {
        let newCount = parseInt(newCountStr);
        if (isNaN(newCount) || newCount < 1) newCount = 1;
        if (!this.state.currentDocument || !groupName) return;

        const groupItems = this.state.currentDocument.items.filter(i => i.radioGroupName === groupName);
        if (groupItems.length === 0) return;

        const currentCount = groupItems.length;
        if (newCount > currentCount) {
            // Add items
            const lastItem = groupItems[currentCount - 1];
            for (let i = currentCount + 1; i <= newCount; i++) {
                this.state.currentDocument.items.push({
                    ...lastItem,
                    id: Date.now() + i,
                    x: lastItem.x + ((i - currentCount) * 30),
                    radioOptionValue: 'Option ' + i
                });
            }
        } else if (newCount < currentCount) {
            // Remove items
            const itemsToRemove = groupItems.slice(newCount).map(i => i.id);
            this.state.currentDocument.items = this.state.currentDocument.items.filter(i => !itemsToRemove.includes(i.id));

            // If the editingBoxId was removed, close popover or switch to the first item
            if (itemsToRemove.includes(this.state.editingBoxId)) {
                this.state.editingBoxId = groupItems[0].id;
            }
        }
    }

    updateRadioGroupMandatory(groupName, mandatory) {
        if (!this.state.currentDocument || !groupName) return;
        for (const item of this.state.currentDocument.items) {
            if (item.radioGroupName === groupName) {
                item.mandatory = mandatory;
            }
        }
    }

    get currentRole() {
        return this.state.roles[this.state.currentRoleIndex] || this.state.roles[0] || {
            id: "signer1",
            name: "Signer 1",
            color: ROLE_PALETTE[0].color,
            borderColor: ROLE_PALETTE[0].borderColor,
            textColor: ROLE_PALETTE[0].textColor,
        };
    }

    getRole(roleId) {
        const role = this.state.roles.find(r => r.id === roleId);
        if (role) return role;
        return this.state.roles[0] || {
            id: roleId,
            name: roleId,
            color: ROLE_PALETTE[0].color,
            borderColor: ROLE_PALETTE[0].borderColor,
            textColor: ROLE_PALETTE[0].textColor,
        };
    }

    getRoleColor(roleId) {
        return this.getRole(roleId).color;
    }

    getRoleBorderColor(roleId) {
        return this.getRole(roleId).borderColor;
    }

    getRoleTextColor(roleId) {
        return this.getRole(roleId).textColor;
    }

    openSendModal(isSignNow) {
        // Collect roles that actually have fields
        const rolesWithFields = new Set();
        for (const doc of this.state.documents) {
            for (const item of doc.items) {
                rolesWithFields.add(item.roleId);
            }
        }

        if (rolesWithFields.size === 0) {
            this.notification.add("Please add at least one signature field to the document.", { type: "warning" });
            return;
        }

        // Format payload to pass to the wizard
        const docs = this.state.documents.map(d => ({
            revision_id: d.id,
            items: d.items.map(i => {
                const pageInfo = this.state.pages.find(p => p.num === i.page) || { width: 800, height: 1100 };
                return {
                    item_type: i.type,
                    page_number: i.page,
                    pos_x: i.x / (pageInfo.width || 800),
                    pos_y: i.y / (pageInfo.height || 1100),
                    width: i.width / (pageInfo.width || 800),
                    height: i.height / (pageInfo.height || 1100),
                    role_id: i.roleId,
                    placeholder: i.placeholder,
                    alignment: i.alignment,
                    mandatory: i.mandatory,
                    readonly: i.readonly,
                    radioGroupName: i.radioGroupName,
                    radioOptionValue: i.radioOptionValue
                };
            })
        }));

        const payload = {
            documents: docs,
        };

        const defaultRoles = Array.from(rolesWithFields).map((roleId, index) => {
            const role = this.state.roles.find(r => r.id === roleId);
            return [0, 0, {
                role_id: roleId,
                role_name: role ? role.name : roleId,
                sequence: index + 1
            }];
        });

        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            name: isSignNow ? "Sign Now" : "Send Signature Request",
            res_model: "dms.signature.send.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_subject: this.state.currentDocument ? "Signature Request - " + this.state.currentDocument.name : "Signature Request",
                default_payload: JSON.stringify(payload),
                default_role_ids: defaultRoles,
                default_single_role_id: rolesWithFields.size === 1 ? Array.from(rolesWithFields)[0] : false,
                default_is_sign_now: isSignNow
            }
        });
    }
}

registry.category("actions").add("dms_signature_pdf_viewer", DmsSignaturePdfViewer);
