/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onMounted, onWillUnmount, onPatched } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { Dialog } from "@web/core/dialog/dialog";

// -----------------------------------------------------------------------------
// Send Dialog Component
// -----------------------------------------------------------------------------
export class SignatureSendDialog extends Component {
    static template = "dms_enterprise_features.SignatureSendDialog";
    static components = { Dialog };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
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
// Signer Settings Dialog Component
// -----------------------------------------------------------------------------
export class SignerSettingsDialog extends Component {
    static template = "dms_enterprise_features.SignerSettingsDialog";
    static components = { Dialog };

    setup() {
        this.state = useState({
            name: this.props.role.name || "",
            authMethod: this.props.role.authMethod || "none",
            canDelegate: this.props.role.canDelegate || false
        });
    }

    onConfirm() {
        this.props.onConfirm({
            name: this.state.name,
            authMethod: this.state.authMethod,
            canDelegate: this.state.canDelegate
        });
        this.props.close();
    }
}


// -----------------------------------------------------------------------------
// Main Signature Editor Component
// -----------------------------------------------------------------------------
export class DmsSignaturePdfViewer extends Component {
    static template = "dms_enterprise_features.SignatureClientAction";

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.pdfContainer = useRef("pdfContainer");
        this.docUploadInput = useRef("docUploadInput");

        this.state = useState({
            documents: [],
            currentDocIndex: 0,
            currentDocument: null,

            roles: [
                { id: "signer1", name: "Signer 1", color: "#e6f2eb", authMethod: "none", canDelegate: false }
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

            allUsers: []
        });

        onMounted(async () => {
            // Load PDF.js
            try {
                await loadJS("/web/static/lib/pdfjs/build/pdf.js");
                window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/web/static/lib/pdfjs/build/pdf.worker.js";
            } catch (e) {
                console.error("Failed to load PDF.js", e);
            }

            // Fetch initial data
            await this.loadInitialData();

            // Mouse tracking for drag/drop
            window.addEventListener('mousemove', this.onWindowMouseMove.bind(this));
            window.addEventListener('mouseup', this.onWindowMouseUp.bind(this));
        });

        onPatched(() => {
            if (this.state.needsRender) {
                this.state.needsRender = false;
                this.renderAllPages();
            }
        });

        onWillUnmount(() => {
            window.removeEventListener('mousemove', this.onWindowMouseMove.bind(this));
            window.removeEventListener('mouseup', this.onWindowMouseUp.bind(this));
        });
    }

    async onBack() {
        let fileId = this.props.action.context?.default_file_id;
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
        const context = this.props.action.context || {};
        const defaultRevIds = context.default_revision_ids || context.default_revision_id;

        if (!defaultRevIds) {
            return this.onBack();
        }

        const revIds = typeof defaultRevIds === "string" ? defaultRevIds.split(',').map(Number) : [defaultRevIds];
        const records = await this.orm.read("dms.file.revision", revIds, ["id", "file_name", "content"], { context: { bin_size: false } });

        if (!records || records.length === 0) {
            return this.onBack();
        }

        this.state.documents = records.map(r => ({
            id: r.id,
            name: r.file_name,
            content: r.content,
            items: [] // array of boxes
        }));

        if (this.state.documents.length > 0) {
            this.selectDocument(0);
        }

        // Fetch all users for assignment
        const users = await this.orm.searchRead("res.users", [], ["id", "name"]);
        this.state.allUsers = users;
    }

    async selectDocument(index) {
        this.state.currentDocIndex = index;
        this.state.currentDocument = this.state.documents[index];
        this.state.editingBoxId = null;

        if (this.state.currentDocument.content) {
            await this.renderPDFFromBase64(this.state.currentDocument.content);
        }
    }

    selectRole(index) {
        this.state.currentRoleIndex = index;
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
        this.state.roles.push({
            id: `signer${nextIdx}`,
            name: `Signer ${nextIdx}`,
            color: `#f${nextIdx}e6e6`
        });
    }

    onAddDocument() {
        this.docUploadInput.el.click();
    }

    onZoomChange(e) {
        let val = parseInt(e.target.value);
        if (isNaN(val) || val < 20) val = 20;
        if (val > 500) val = 500;

        const ratio = val / this.state.zoomLevel;
        this.state.zoomLevel = val;

        if (this.state.currentDocument) {
            // Scale existing items
            for (const item of this.state.currentDocument.items) {
                item.x = Math.round(item.x * ratio);
                item.y = Math.round(item.y * ratio);
                item.width = Math.round(item.width * ratio);
                item.height = Math.round(item.height * ratio);
            }
            // Trigger recalculation of page sizes
            this.state.pages = [];
            for (let i = 1; i <= this.pdfDoc.numPages; i++) {
                this.pdfDoc.getPage(i).then(page => {
                    const scale = this.state.zoomLevel / 100;
                    const viewport = page.getViewport({ scale });
                    this.state.pages.push({
                        num: i,
                        width: viewport.width,
                        height: viewport.height
                    });

                    // Once all pages are collected, queue render
                    if (this.state.pages.length === this.pdfDoc.numPages) {
                        this.state.pages.sort((a, b) => a.num - b.num);
                        this.state.needsRender = true;
                    }
                });
            }
        }
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
            this.selectDocument(this.state.documents.length - 1);
        };
        reader.readAsDataURL(file);
    }

    async renderPDFFromBase64(base64) {
        if (!window.pdfjsLib) return;
        try {
            const binaryString = window.atob(base64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }

            // Store pdfDoc directly on the instance to avoid OWL Proxy breaking PDF.js private fields
            this.pdfDoc = await window.pdfjsLib.getDocument({ data: bytes }).promise;

            this.state.pages = [];
            for (let i = 1; i <= this.pdfDoc.numPages; i++) {
                const page = await this.pdfDoc.getPage(i);
                const scale = this.state.zoomLevel / 100;
                const viewport = page.getViewport({ scale });
                this.state.pages.push({
                    num: i,
                    width: viewport.width,
                    height: viewport.height
                });
            }

            this.state.needsRender = true;
        } catch (err) {
            console.error("PDF.js render error:", err);
            if (this.notification) {
                this.notification.add("The selected document is not a valid PDF for signing.", { type: "danger" });
            }
        }
    }

    async renderAllPages() {
        if (!this.pdfDoc) return;

        const outputScale = window.devicePixelRatio || 1;

        for (const pageInfo of this.state.pages) {
            const canvas = document.getElementById('pdf-canvas-' + pageInfo.num);
            if (!canvas) continue;

            const page = await this.pdfDoc.getPage(pageInfo.num);
            const scale = this.state.zoomLevel / 100;
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
            page.render(renderContext);
        }
    }

    // --- Drag & Drop UI Logic ---
    startDrag(e, type) {
        this.state.dragType = type;
        this.state.mouseX = e.clientX;
        this.state.mouseY = e.clientY;
    }

    onWindowMouseMove(e) {
        if (this.state.dragType) {
            this.state.mouseX = e.clientX;
            this.state.mouseY = e.clientY;
        } else if (this.state.boxDragId) {
            const dx = e.clientX - this.state.dragStartX;
            const dy = e.clientY - this.state.dragStartY;
            const box = this.state.currentDocument.items.find(b => b.id === this.state.boxDragId);
            if (box) {
                let newX = this.state.boxStartRect.x + dx;
                let newY = this.state.boxStartRect.y + dy;

                if (this.pdfContainer && this.pdfContainer.el) {
                    const pageEl = this.pdfContainer.el.querySelector(`.pdf-page[data-page-num="${box.page}"]`);
                    if (pageEl) {
                        const rect = pageEl.getBoundingClientRect();
                        newX = Math.min(Math.max(0, newX), rect.width - box.width);
                        newY = Math.min(Math.max(0, newY), rect.height - box.height);
                    }
                }

                box.x = newX;
                box.y = newY;
            }
        } else if (this.state.boxResizeId) {
            const dx = e.clientX - this.state.dragStartX;
            const dy = e.clientY - this.state.dragStartY; ind(b => b.id === this.state.boxResizeId);
            if (box) {
                let newW = this.state.boxStartRect.width + dx;
                let newH = this.state.boxStartRect.height + dy;

                if (this.pdfContainer && this.pdfContainer.el) {
                    const pageEl = this.pdfContainer.el.querySelector(`.pdf-page[data-page-num="${box.page}"]`);
                    if (pageEl) {
                        const rect = pageEl.getBoundingClientRect();
                        newW = Math.min(newW, rect.width - box.x);
                        newH = Math.min(newH, rect.height - box.y);
                    }
                }

                if (box.type === 'checkbox' || box.type === 'radio') {
                    const size = Math.max(16, Math.max(newW, newH));
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

        // Check if dropped inside canvas
        if (this.pdfContainer.el) {
            const pageEls = this.pdfContainer.el.querySelectorAll('.pdf-page');
            let targetPageNum = null;
            let targetRect = null;

            for (const pageEl of pageEls) {
                const rect = pageEl.getBoundingClientRect();
                if (e.clientX >= rect.left && e.clientX <= rect.right &&
                    e.clientY >= rect.top && e.clientY <= rect.bottom) {
                    targetPageNum = parseInt(pageEl.getAttribute('data-page-num'));
                    targetRect = rect;
                    break;
                }
            }

            if (targetPageNum) {

                const currentRole = this.state.roles[this.state.currentRoleIndex];

                let defaultW = 180;
                let defaultH = 45;
                if (type === 'checkbox' || type === 'radio') {
                    defaultW = 24;
                    defaultH = 24;
                }

                let dropX = e.clientX - targetRect.left;
                let dropY = e.clientY - targetRect.top;

                dropX = Math.min(Math.max(0, dropX), targetRect.width - defaultW);
                dropY = Math.min(Math.max(0, dropY), targetRect.height - defaultH);

                if (type === 'radio') {
                    const groupId = 'RadioGroup_' + Date.now();
                    for (let i = 1; i <= 2; i++) {
                        let radioX = dropX + ((i - 1) * 30);
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
    }

    startBoxDrag(e, box) {
        // Only start drag if not clicking a control button
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

    getRoleColor(roleId) {
        const role = this.state.roles.find(r => r.id === roleId);
        return role ? role.color : "#e6f2eb";
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
            items: d.items.map(i => ({
                item_type: i.type,
                page_number: i.page,
                pos_x: i.x / (this.state.pages.find(p => p.num === i.page)?.width || 800),
                pos_y: i.y / (this.state.pages.find(p => p.num === i.page)?.height || 1100),
                width: i.width / (this.state.pages.find(p => p.num === i.page)?.width || 800),
                height: i.height / (this.state.pages.find(p => p.num === i.page)?.height || 1100),
                role_id: i.roleId,
                // assigned_user_id will be mapped by the wizard

                // Extra Properties
                placeholder: i.placeholder,
                alignment: i.alignment,
                mandatory: i.mandatory,
                readonly: i.readonly,
                radioGroupName: i.radioGroupName,
                radioOptionValue: i.radioOptionValue
            }))
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
