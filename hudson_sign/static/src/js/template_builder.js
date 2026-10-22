/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, proxy, onMounted, onWillUnmount, onPatched, useProps } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

export class HudsonSignTemplateBuilder extends Component {
    static template = "hudson_sign.TemplateBuilder";
    props = useProps({
        ...standardActionServiceProps,
    });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");

        this.pdfContainer = {
            _el: null,
            get el() {
                return this._el || document.querySelector(".o_hudson_sign_template_builder .bg-view");
            },
            set(element) {
                this._el = element;
            }
        };

        const action = this.props?.action || (this.__owl__ && this.__owl__.props && this.__owl__.props.action) || {};
        const context = action.context || (this.props && this.props.context) || {};
        let templateId = context.active_id || action.res_id || action.params?.active_id || this.props?.resId || this.props?.active_id;
        if (Array.isArray(templateId)) {
            templateId = templateId[0];
        }
        if (typeof templateId === "string" && !isNaN(parseInt(templateId, 10))) {
            templateId = parseInt(templateId, 10);
        }

        this.needsRender = false;
        this._renderTasks = {};

        this.state = proxy({
            templateId: templateId,
            template: null,
            pdfContent: null,

            allTags: [],
            templateTags: [],

            roles: [],
            currentRoleIndex: 0,

            tools: [],

            pages: [],
            zoomLevel: 100,

            // Drag state
            dragType: null,   // type string when dragging from sidebar
            mouseX: 0,
            mouseY: 0,

            boxDragId: null,
            boxResizeId: null,
            editingBoxId: null,
            dragStartX: 0,
            dragStartY: 0,
            boxStartRect: null,

            items: [],  // all placed fields
            allUsers: []
        });

        this._onMouseMove = this._handleMouseMove.bind(this);
        this._onMouseUp = this._handleMouseUp.bind(this);

        onMounted(async () => {
            try {
                const pdfjsLib = await import("/web/static/lib/pdfjs/build/pdf.js");
                window.pdfjsLib = pdfjsLib;
                if (pdfjsLib.GlobalWorkerOptions) {
                    pdfjsLib.GlobalWorkerOptions.workerSrc = "/web/static/lib/pdfjs/build/pdf.worker.js";
                }
            } catch (e) {
                console.error("Failed to load PDF.js", e);
            }

            await this.loadData();

            window.addEventListener('mousemove', this._onMouseMove);
            window.addEventListener('mouseup', this._onMouseUp);
        });

        onWillUnmount(() => {
            window.removeEventListener('mousemove', this._onMouseMove);
            window.removeEventListener('mouseup', this._onMouseUp);
        });

        onPatched(() => {
            if (this.needsRender) {
                this.needsRender = false;
                this._renderAllPages();
            }
        });
    }

    // ---- Data Loading ----

    async loadData() {
        if (!this.state.templateId) {
            const latest = await this.orm.searchRead("hudson.sign.template", [], ["id"], { limit: 1, order: "id desc" });
            if (latest.length) {
                this.state.templateId = latest[0].id;
            } else {
                return;
            }
        }
        const templates = await this.orm.read("hudson.sign.template", [this.state.templateId], ["name", "attachment_id", "tag_ids"]);
        if (!templates.length) return;
        this.state.template = templates[0];

        const allTags = await this.orm.searchRead("hudson.sign.template.tag", [], ["name", "color"]);
        this.state.allTags = allTags;
        this.state.templateTags = allTags.filter(t => templates[0].tag_ids.includes(t.id));

        const roles = await this.orm.searchRead("hudson.sign.template.role", [["template_id", "=", this.state.templateId]], ["name", "color"]);
        if (!roles.length) {
            const roleId = await this.orm.create("hudson.sign.template.role", [{
                name: "Signer 1",
                template_id: this.state.templateId,
                color: "#e6f2eb"
            }]);
            this.state.roles = [{ id: roleId[0], name: "Signer 1", color: "#e6f2eb" }];
        } else {
            this.state.roles = roles;
        }

        const tools = await this.orm.searchRead("hudson.sign.item.type", [], ["name", "item_type"]);
        this.state.tools = tools.map(t => ({
            id: t.id,
            type: t.item_type,
            label: t.name,
            icon: this._getIconForType(t.item_type)
        }));

        // Load items stored in DB (pos_x, pos_y, width, height are absolute px)
        const items = await this.orm.searchRead("hudson.sign.template.item",
            [["template_id", "=", this.state.templateId]],
            ["type_id", "role_id", "page_number", "pos_x", "pos_y", "width", "height", "mandatory"]);
        this.state.items = items.map(i => ({
            id: i.id,
            typeId: i.type_id[0],
            type: i.type_id[1] || '',   // text name as fallback
            roleId: i.role_id ? i.role_id[0] : this.state.roles[0].id,
            page: i.page_number,
            x: i.pos_x,
            y: i.pos_y,
            width: i.width,
            height: i.height,
            mandatory: i.mandatory
        }));

        // Fix type field from tools map
        for (const item of this.state.items) {
            const tool = this.state.tools.find(t => t.id === item.typeId);
            if (tool) item.type = tool.type;
        }

        const attachmentId = this.state.template.attachment_id[0];
        let pdfBytes = null;

        // 1. Try reading attachment raw via ORM (in Odoo 20, raw returns { filename, content, size })
        try {
            const attachments = await this.orm.read("ir.attachment", [attachmentId], ["raw"]);
            if (attachments.length && attachments[0].raw) {
                const rawVal = attachments[0].raw;
                let b64 = null;
                if (typeof rawVal === "object" && rawVal !== null && rawVal.content) {
                    b64 = rawVal.content;
                } else if (typeof rawVal === "string") {
                    b64 = rawVal;
                }
                if (b64) {
                    const binaryString = window.atob(b64);
                    pdfBytes = new Uint8Array(binaryString.length);
                    for (let i = 0; i < binaryString.length; i++) {
                        pdfBytes[i] = binaryString.charCodeAt(i);
                    }
                }
            }
        } catch (e) {
            console.warn("Could not read raw from ir.attachment via ORM:", e);
        }

        // 2. Fallback: fetch binary directly from /web/content/<id>
        if (!pdfBytes || pdfBytes.length === 0) {
            try {
                const response = await fetch(`/web/content/${attachmentId}`);
                if (response.ok) {
                    const arrayBuffer = await response.arrayBuffer();
                    if (arrayBuffer.byteLength > 0) {
                        pdfBytes = new Uint8Array(arrayBuffer);
                    }
                }
            } catch (e) {
                console.error("Failed to fetch PDF from /web/content:", e);
            }
        }

        if (pdfBytes && pdfBytes.length > 0) {
            this.state.pdfContent = true;
            await this._renderPDF(pdfBytes);
        } else {
            this.notification.add("Could not load PDF content for this template.", { type: "danger" });
        }

        const users = await this.orm.searchRead("res.users", [], ["id", "name"]);
        this.state.allUsers = users;
    }

    async _renderPDF(bytes) {
        if (!window.pdfjsLib) {
            console.error("PDF.js library is not available");
            return;
        }
        try {
            // Store on instance to avoid OWL Proxy issues with PDF.js internals
            this.pdfDoc = await window.pdfjsLib.getDocument({ data: bytes }).promise;

            const newPages = [];
            for (let i = 1; i <= this.pdfDoc.numPages; i++) {
                const page = await this.pdfDoc.getPage(i);
                const scale = this.state.zoomLevel / 100;
                const viewport = page.getViewport({ scale });
                newPages.push({
                    num: i,
                    width: Math.floor(viewport.width),
                    height: Math.floor(viewport.height)
                });
            }

            this.state.pages = newPages;
            this.needsRender = true;

            // Wait for DOM to update with new canvas elements
            await new Promise(resolve => requestAnimationFrame(resolve));
            await new Promise(resolve => setTimeout(resolve, 60));
            await this._renderAllPages();
        } catch (err) {
            console.error("PDF.js render error:", err);
        }
    }

    async _renderAllPages() {
        if (!this.pdfDoc || !this.state.pages.length) return;

        this._renderTasks = this._renderTasks || {};
        const outputScale = window.devicePixelRatio || 1;

        for (const pageInfo of this.state.pages) {
            const canvas = document.getElementById('pdf-canvas-' + pageInfo.num);
            if (!canvas) continue;

            // Cancel any ongoing render task on this page
            if (this._renderTasks[pageInfo.num]) {
                try {
                    await this._renderTasks[pageInfo.num].cancel();
                } catch {}
            }

            const page = await this.pdfDoc.getPage(pageInfo.num);
            const scale = this.state.zoomLevel / 100;
            const viewport = page.getViewport({ scale });
            const context = canvas.getContext('2d');

            canvas.width = Math.floor(viewport.width * outputScale);
            canvas.height = Math.floor(viewport.height * outputScale);
            canvas.style.width = Math.floor(viewport.width) + "px";
            canvas.style.height = Math.floor(viewport.height) + "px";
            pageInfo.width = Math.floor(viewport.width);
            pageInfo.height = Math.floor(viewport.height);

            const transform = outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;

            const renderContext = {
                canvasContext: context,
                transform: transform,
                viewport: viewport
            };

            const renderTask = page.render(renderContext);
            this._renderTasks[pageInfo.num] = renderTask;
            try {
                await renderTask.promise;
            } catch (err) {
                if (err?.name !== "RenderingCancelledException") {
                    console.error("Page render error:", err);
                }
            } finally {
                delete this._renderTasks[pageInfo.num];
            }
        }

        // Convert ratio-based item coordinates into pixels
        for (const item of this.state.items) {
            const page = this.state.pages.find(p => p.num === item.page);
            if (page && item.width <= 1.0) {
                item.x = item.x * page.width;
                item.y = item.y * page.height;
                item.width = item.width * page.width;
                item.height = item.height * page.height;
            }
        }
    }

    // ---- Helpers ----

    _getIconForType(type) {
        const iconMap = {
            'signature': 'fa-pencil',
            'initials': 'fa-font',
            'text': 'fa-font',
            'name': 'fa-user',
            'email': 'fa-envelope',
            'phone': 'fa-phone',
            'company': 'fa-building',
            'date': 'fa-calendar',
            'checkbox': 'fa-check-square-o',
            'radio': 'fa-dot-circle-o',
            'selection': 'fa-caret-down',
            'strikethrough': 'fa-strikethrough',
            'multiline': 'fa-align-left',
            'stamp': 'fa-legal'
        };
        return iconMap[type] || 'fa-pencil';
    }

    getToolIcon(typeId) {
        const tool = this.state.tools.find(t => t.id === typeId);
        return tool ? tool.icon : 'fa-pencil';
    }

    getToolLabel(typeId) {
        const tool = this.state.tools.find(t => t.id === typeId);
        return tool ? tool.label : 'Field';
    }

    getToolIconByType(type) {
        const tool = this.state.tools.find(t => t.type === type);
        return tool ? tool.icon : 'fa-pencil';
    }

    getToolLabelByType(type) {
        const tool = this.state.tools.find(t => t.type === type);
        return tool ? tool.label : type;
    }

    getItemsForPage(pageNum) {
        return this.state.items.filter(i => i.page === pageNum);
    }

    getRoleItemCount(roleId) {
        return this.state.items.filter(i => i.roleId === roleId).length;
    }

    get currentRoleId() {
        return (this.state.roles[this.state.currentRoleIndex] || this.state.roles[0] || {}).id;
    }

    getRoleColor(roleId) {
        const role = this.state.roles.find(r => r.id === roleId);
        return role ? role.color : '#e6f2eb';
    }

    get availableTags() {
        return this.state.allTags.filter(t => !this.state.templateTags.find(tt => tt.id === t.id));
    }

    // ---- Role Management ----

    selectRole(index) {
        this.state.currentRoleIndex = index;
    }

    async addRole() {
        const count = this.state.roles.length + 1;
        const colors = ["#e6f2eb", "#f2e6e6", "#e6eaf2", "#f2eee6", "#eee6f2"];
        const color = colors[(count - 1) % colors.length];
        const roleId = await this.orm.create("hudson.sign.template.role", [{
            name: `Signer ${count}`,
            template_id: this.state.templateId,
            color: color
        }]);
        this.state.roles.push({ id: roleId[0], name: `Signer ${count}`, color: color });
        this.state.currentRoleIndex = this.state.roles.length - 1;
    }

    // ---- Tag Management ----

    async addTag(ev) {
        const tagId = parseInt(ev.target.value);
        if (!tagId) return;
        await this.orm.write("hudson.sign.template", [this.state.templateId], { tag_ids: [[4, tagId]] });
        const tag = this.state.allTags.find(t => t.id === tagId);
        if (tag && !this.state.templateTags.find(t => t.id === tagId)) {
            this.state.templateTags.push(tag);
        }
        ev.target.value = "";
    }

    async removeTag(tagId) {
        await this.orm.write("hudson.sign.template", [this.state.templateId], { tag_ids: [[3, tagId]] });
        this.state.templateTags = this.state.templateTags.filter(t => t.id !== tagId);
    }

    // ---- Zoom ----

    async onZoomChange(e) {
        let val = parseInt(e.target.value);
        if (isNaN(val) || val < 20) val = 20;
        if (val > 500) val = 500;

        const ratio = val / this.state.zoomLevel;
        this.state.zoomLevel = val;

        // Scale all item positions/sizes proportionally
        for (const item of this.state.items) {
            item.x = Math.round(item.x * ratio);
            item.y = Math.round(item.y * ratio);
            item.width = Math.round(item.width * ratio);
            item.height = Math.round(item.height * ratio);
        }

        if (this.pdfDoc) {
            const newPages = [];
            for (let i = 1; i <= this.pdfDoc.numPages; i++) {
                const page = await this.pdfDoc.getPage(i);
                const scale = this.state.zoomLevel / 100;
                const viewport = page.getViewport({ scale });
                newPages.push({
                    num: i,
                    width: Math.floor(viewport.width),
                    height: Math.floor(viewport.height)
                });
            }
            this.state.pages = newPages;
            this.needsRender = true;
            await new Promise(resolve => requestAnimationFrame(resolve));
            await new Promise(resolve => setTimeout(resolve, 60));
            await this._renderAllPages();
        }
    }

    // ---- Drag Tool from Sidebar ----

    startDragTool(e, tool) {
        this.state.dragType = tool.type;
        this._dragToolId = tool.id;
        this.state.mouseX = e.clientX;
        this.state.mouseY = e.clientY;
    }

    // ---- Box Drag ----

    startBoxDrag(e, item) {
        if (e.target.closest('.delete-box-btn') || e.target.closest('.resize-box-handle')) return;
        this.state.boxDragId = item.id;
        this.state.dragStartX = e.clientX;
        this.state.dragStartY = e.clientY;
        this.state.boxStartRect = { x: item.x, y: item.y };
        e.stopPropagation();
        e.preventDefault();
    }

    // ---- Box Resize ----

    startBoxResize(e, item) {
        this.state.boxResizeId = item.id;
        this.state.dragStartX = e.clientX;
        this.state.dragStartY = e.clientY;
        this.state.boxStartRect = { width: item.width, height: item.height };
        e.stopPropagation();
        e.preventDefault();
    }

    // ---- Mouse Handlers ----

    _handleMouseMove(e) {
        if (this.state.dragType) {
            this.state.mouseX = e.clientX;
            this.state.mouseY = e.clientY;
            return;
        }

        if (this.state.boxDragId !== null) {
            const dx = e.clientX - this.state.dragStartX;
            const dy = e.clientY - this.state.dragStartY;
            const item = this.state.items.find(i => i.id === this.state.boxDragId);
            if (!item) return;

            let newX = this.state.boxStartRect.x + dx;
            let newY = this.state.boxStartRect.y + dy;

            if (this.pdfContainer && this.pdfContainer.el) {
                const pageEl = this.pdfContainer.el.querySelector(`.pdf-page[data-page-num="${item.page}"]`);
                if (pageEl) {
                    const rect = pageEl.getBoundingClientRect();
                    newX = Math.min(Math.max(0, newX), rect.width - item.width);
                    newY = Math.min(Math.max(0, newY), rect.height - item.height);
                }
            }

            item.x = newX;
            item.y = newY;
        } else if (this.state.boxResizeId !== null) {
            const dx = e.clientX - this.state.dragStartX;
            const dy = e.clientY - this.state.dragStartY;
            const item = this.state.items.find(i => i.id === this.state.boxResizeId);
            if (!item) return;

            let newW = this.state.boxStartRect.width + dx;
            let newH = this.state.boxStartRect.height + dy;

            if (this.pdfContainer && this.pdfContainer.el) {
                const pageEl = this.pdfContainer.el.querySelector(`.pdf-page[data-page-num="${item.page}"]`);
                if (pageEl) {
                    const rect = pageEl.getBoundingClientRect();
                    newW = Math.min(newW, rect.width - item.x);
                    newH = Math.min(newH, rect.height - item.y);
                }
            }

            if (item.type === 'checkbox' || item.type === 'radio') {
                const size = Math.max(16, Math.max(newW, newH));
                item.width = size;
                item.height = size;
            } else {
                item.width = Math.max(20, newW);
                item.height = Math.max(15, newH);
            }
        }
    }

    async _handleMouseUp(e) {
        // Handle box drag end - save to backend
        if (this.state.boxDragId !== null) {
            const itemId = this.state.boxDragId;
            this.state.boxDragId = null;
            const item = this.state.items.find(i => i.id === itemId);
            if (item) {
                const page = this.state.pages.find(p => p.num === item.page) || { width: 800, height: 1100 };
                await this.orm.write("hudson.sign.template.item", [item.id], {
                    pos_x: item.x / page.width,
                    pos_y: item.y / page.height,
                    width: item.width / page.width,
                    height: item.height / page.height
                });
            }
            return;
        }

        // Handle resize end - save to backend
        if (this.state.boxResizeId !== null) {
            const itemId = this.state.boxResizeId;
            this.state.boxResizeId = null;
            const item = this.state.items.find(i => i.id === itemId);
            if (item) {
                const page = this.state.pages.find(p => p.num === item.page) || { width: 800, height: 1100 };
                await this.orm.write("hudson.sign.template.item", [item.id], {
                    pos_x: item.x / page.width,
                    pos_y: item.y / page.height,
                    width: item.width / page.width,
                    height: item.height / page.height
                });
            }
            return;
        }

        // Handle new tool drop
        if (this.state.dragType) {
            const type = this.state.dragType;
            const toolId = this._dragToolId;
            this.state.dragType = null;
            this._dragToolId = null;

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
                    const currentRoleId = this.currentRoleId;

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

                    const itemId = await this.orm.create("hudson.sign.template.item", [{
                        template_id: this.state.templateId,
                        type_id: toolId,
                        role_id: currentRoleId,
                        page_number: targetPageNum,
                        pos_x: dropX / targetRect.width,
                        pos_y: dropY / targetRect.height,
                        width: defaultW / targetRect.width,
                        height: defaultH / targetRect.height,
                        mandatory: true
                    }]);

                    this.state.items.push({
                        id: itemId[0],
                        typeId: toolId,
                        type: type,
                        roleId: currentRoleId,
                        page: targetPageNum,
                        x: dropX,
                        y: dropY,
                        width: defaultW,
                        height: defaultH,
                        mandatory: true
                    });
                }
            }
        }
    }

    // ---- Remove Item ----

    async removeItem(e, item) {
        e.stopPropagation();
        this.state.boxDragId = null;
        this.state.boxResizeId = null;
        this.state.items = this.state.items.filter(i => i.id !== item.id);
        try {
            await this.orm.unlink("hudson.sign.template.item", [item.id]);
        } catch (err) {
            console.error("Failed to delete item", err);
        }
    }

    // ---- Navigation ----

    goBack() {
        this.action.doAction('hudson_sign.action_hudson_sign_template', { clearBreadcrumbs: true });
    }

    // ---- Send / Sign Now ----

    actionSend() {
        this.openSendModal(false);
    }

    actionSignNow() {
        this.openSendModal(true);
    }

    openSendModal(isSignNow) {
        const rolesWithFields = new Set(this.state.items.map(i => i.roleId));

        if (rolesWithFields.size === 0) {
            this.notification.add("Please add at least one signature field to the template.", { type: "warning" });
            return;
        }

        const defaultRoles = Array.from(rolesWithFields).map((roleId, index) => {
            const role = this.state.roles.find(r => r.id === roleId);
            return [0, 0, {
                role_id: roleId,
                role_name: role ? role.name : roleId,
                sequence: index + 1
            }];
        });

        // For templates, we pass the templateId instead of the massive documents/items payload
        // The wizard needs to call the template's create_requests_from_ui
        // We can pass the template ID via context!
        
        const payload = { template_id: this.state.templateId };

        this.action.doAction({
            type: "ir.actions.act_window",
            name: isSignNow ? "Sign Now" : "New Signature Request",
            res_model: "dms.signature.send.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_subject: this.state.template ? "Signature Request - " + this.state.template.name : "Signature Request",
                default_payload: JSON.stringify(payload),
                default_role_ids: defaultRoles,
                default_single_role_id: rolesWithFields.size === 1 ? Array.from(rolesWithFields)[0] : false,
                default_is_sign_now: isSignNow,
                is_from_template: true
            }
        });
    }
}

registry.category("actions").add("hudson_sign.template_builder", HudsonSignTemplateBuilder);
