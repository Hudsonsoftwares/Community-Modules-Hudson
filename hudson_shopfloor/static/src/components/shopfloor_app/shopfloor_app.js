/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ShopFloorApp extends Component {
    static template = "hudson_shopfloor.ShopFloorApp";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            workcenters: [],
            selectedWorkcenter: null,
            mos: [],
            activeWoId: null,
            currentTime: new Date(),

            // Employee Operator
            employees: [],
            activeEmployee: null,
            showPinModal: false,
            pendingEmployee: null,
            pinError: false,
            pinInput: "",

            // Options modal
            showOptionsModal: false,
            optionsMoId: null,
            optionsWoId: null,

            // Register Quantity / Lot modal
            showRegisterQtyModal: false,
            registerQtyMoId: null,
            registerQtyWoId: null,
            registerQtyValue: 1,
            registerLotName: "",
            registerProducts: [],
            registerSelectedMoveId: null,

            // ── Product Catalog (Add Component) ──────────────────────────────
            showCatalogModal: false,
            catalogMoId: null,
            catalogSearch: "",
            catalogCategories: [],        // [{id, name, parent_id}]
            catalogSelectedCat: null,     // null → All
            catalogTags: [],              // [{id, name}]
            catalogSelectedTag: null,
            catalogProducts: [],          // current page of products
            catalogPage: 1,
            catalogTotalCount: 0,
            catalogCart: {},              // { productId: { qty, name, uom, uomId } }
            catalogLoading: false,

            // ── Add Work Order ────────────────────────────────────────────────
            showAddWorkOrderModal: false,
            addWorkOrderMoId: null,
            addWorkOrderInsertAfterId: null,   // workorder id to insert after
            addWorkOrderTitle: "",
            addWorkOrderWorkcenterId: null,
            addWorkOrderDurationMin: 0,        // stored in minutes internally
            addWorkOrderDateStart: "",
            addWorkOrderEmployeeId: null,
            addWorkOrderOperations: [],        // workorders of current MO
            addWorkOrderWorkcentersList: [],
            addWorkOrderEmployeesList: [],

            // Log Note modal
            showLogNoteModal: false,
            logNoteMoId: null,
            logNoteText: "",
        });

        onWillStart(async () => {
            await this.loadEmployees();
            await this.loadWorkcenters();
        });

        this.timerInterval = setInterval(() => {
            this.state.currentTime = new Date();
        }, 1000);

        onWillDestroy(() => {
            clearInterval(this.timerInterval);
        });
    }

    // =========================================================
    // Core data loading
    // =========================================================

    async loadEmployees() {
        this.state.employees = await this.orm.searchRead(
            "hr.employee", [["user_id", "!=", false]], ["name", "user_id"]
        );
    }

    async loadWorkcenters() {
        const workcenters = await this.orm.searchRead("mrp.workcenter", [], ["name", "code"]);
        const counts = await this.orm.call("mrp.workorder", "read_group", [
            [["state", "in", ["ready", "progress", "pending"]]],
            ["workcenter_id"],
            ["workcenter_id"],
        ]);
        const countMap = {};
        let totalCount = 0;
        for (let c of counts) {
            countMap[c.workcenter_id[0]] = c.workcenter_id_count;
            totalCount += c.workcenter_id_count;
        }
        this.state.workcenters = [
            { id: "overview", name: "Overview", count: totalCount },
            ...workcenters.map(wc => ({ ...wc, count: countMap[wc.id] || 0 })),
        ];
        if (this.state.workcenters.length > 0) {
            await this.selectWorkcenter(this.state.workcenters[0].id);
        }
    }

    async selectWorkcenter(workcenterId) {
        this.state.selectedWorkcenter = workcenterId;
        this.state.activeWoId = null;
        await this.loadMOs(workcenterId);
    }

    async loadMOs(workcenterId) {
        let domain = [["state", "in", ["ready", "progress", "pending"]]];
        if (workcenterId !== "overview") domain.push(["workcenter_id", "=", workcenterId]);

        const activeWos = await this.orm.searchRead("mrp.workorder", domain, ["production_id"]);
        if (activeWos.length === 0) { this.state.mos = []; return; }

        const productionIds = [...new Set(activeWos.map(wo => wo.production_id[0]))];
        let moDomain = [["id", "in", productionIds]];
        if (this.state.activeEmployee) {
            moDomain.push(["user_id", "=", this.state.activeEmployee.user_id[0]]);
        }
        const validMos = await this.orm.searchRead("mrp.production", moDomain, ["id"]);
        const validMoIds = validMos.map(m => m.id);
        if (validMoIds.length === 0) { this.state.mos = []; return; }

        const allWos = await this.orm.searchRead(
            "mrp.workorder",
            [["production_id", "in", validMoIds]],
            ["name", "production_id", "product_id", "qty_producing", "qty_production",
             "state", "workcenter_id", "date_start", "duration"]
        );

        const grouped = {};
        for (let wo of allWos) {
            const moId = wo.production_id[0];
            if (!grouped[moId]) {
                grouped[moId] = {
                    id: moId,
                    name: wo.production_id[1],
                    product_id: wo.product_id,
                    qty_producing: wo.qty_producing,
                    qty_production: wo.qty_production,
                    workorders: [],
                };
            }
            grouped[moId].workorders.push(wo);
        }
        Object.values(grouped).forEach(mo => mo.workorders.sort((a, b) => a.id - b.id));
        this.state.mos = Object.values(grouped);
    }

    // =========================================================
    // Employee PIN
    // =========================================================

    clickEmployee(emp) {
        if (this.state.activeEmployee && this.state.activeEmployee.id === emp.id) return;
        this.state.pendingEmployee = emp;
        this.state.pinInput = "";
        this.state.pinError = false;
        this.state.showPinModal = true;
    }

    closePinModal() {
        this.state.showPinModal = false;
        this.state.pendingEmployee = null;
        this.state.pinInput = "";
        this.state.pinError = false;
    }

    addPinDigit(digit) {
        this.state.pinInput += digit.toString();
        this.state.pinError = false;
    }

    clearPin() {
        this.state.pinInput = "";
        this.state.pinError = false;
    }

    async submitPin() {
        try {
            const isValid = await this.orm.call(
                "hr.employee", "check_shopfloor_pin",
                [this.state.pendingEmployee.id, this.state.pinInput]
            );
            if (isValid) {
                this.state.activeEmployee = this.state.pendingEmployee;
                this.closePinModal();
                await this.loadMOs(this.state.selectedWorkcenter);
            } else {
                this.state.pinError = true;
                this.state.pinInput = "";
            }
        } catch (e) {
            this.state.pinError = true;
        }
    }

    async logoutEmployee() {
        this.state.activeEmployee = null;
        await this.loadMOs(this.state.selectedWorkcenter);
    }

    // =========================================================
    // Workorder Actions
    // =========================================================

    closeOperation() { this.state.activeWoId = null; }

    get activeWo() {
        if (!this.state.activeWoId) return null;
        for (let mo of this.state.mos) {
            const wo = mo.workorders.find(w => w.id === this.state.activeWoId);
            if (wo) return wo;
        }
        return null;
    }

    formatDuration(dateStartStr, initialDurationMin) {
        if (!dateStartStr) return "0m 0s";
        const initialMs = initialDurationMin * 60 * 1000;
        const dateStart = new Date(dateStartStr.replace(" ", "T") + "Z");
        const totalMs = initialMs + Math.max(0, this.state.currentTime - dateStart);
        const totalSecs = Math.floor(totalMs / 1000);
        return `${Math.floor(totalSecs / 60)}m ${totalSecs % 60}s`;
    }

    async actionStartWorkorder(workorderId) {
        await this.orm.call("mrp.workorder", "button_start", [[workorderId]]);
        await this.loadMOs(this.state.selectedWorkcenter);
        this.state.activeWoId = workorderId;
    }

    async actionCloseProduction(workorderId) {
        await this.orm.call("mrp.workorder", "button_finish", [[workorderId]]);
        this.state.activeWoId = null;
        await this.loadMOs(this.state.selectedWorkcenter);
    }

    async actionScrap(woId) {
        this.closeOptionsModal();
        const action = await this.orm.call("mrp.workorder", "button_scrap", [[woId]]);
        if (action) this.action.doAction(action);
    }

    // =========================================================
    // Options Modal
    // =========================================================

    openOptionsModal(moId, woId) {
        this.state.optionsMoId = moId;
        this.state.optionsWoId = woId;
        this.state.showOptionsModal = true;
    }

    closeOptionsModal() {
        this.state.showOptionsModal = false;
        this.state.optionsMoId = null;
        this.state.optionsWoId = null;
    }

    // =========================================================
    // Register Quantity / Lot
    // =========================================================

    async openRegisterQtyModal(moId, woId) {
        this.closeOptionsModal();
        this.state.registerQtyMoId = moId;
        this.state.registerQtyWoId = woId;
        this.state.registerQtyValue = 1;
        this.state.registerLotName = "";
        this.state.registerSelectedMoveId = null;
        try {
            const moves = await this.orm.searchRead(
                "stock.move",
                [["raw_material_production_id", "=", moId], ["state", "not in", ["done", "cancel"]]],
                ["id", "product_id", "product_uom_qty", "quantity_done"]
            );
            this.state.registerProducts = moves;
            if (moves.length > 0) {
                this.state.registerSelectedMoveId = moves[0].id;
                this.state.registerQtyValue = moves[0].product_uom_qty || 1;
            }
        } catch (e) {
            this.state.registerProducts = [];
        }
        this.state.showRegisterQtyModal = true;
    }

    closeRegisterQtyModal() {
        this.state.showRegisterQtyModal = false;
        this.state.registerQtyMoId = null;
        this.state.registerQtyWoId = null;
        this.state.registerProducts = [];
    }

    async submitRegisterQty() {
        try {
            const moId = this.state.registerQtyMoId;
            const qty = parseFloat(this.state.registerQtyValue) || 0;
            const lotName = this.state.registerLotName.trim();
            const moveId = this.state.registerSelectedMoveId;

            if (moveId && qty > 0) {
                await this.orm.write("stock.move", [moveId], { quantity_done: qty });
            }
            await this.orm.write("mrp.production", [moId], { qty_producing: qty });

            if (lotName) {
                const moData = await this.orm.read("mrp.production", [moId], ["product_id", "company_id"]);
                const productId = moData[0].product_id[0];
                const companyId = moData[0].company_id ? moData[0].company_id[0] : false;
                const existing = await this.orm.searchRead(
                    "stock.lot", [["name", "=", lotName], ["product_id", "=", productId]], ["id"]
                );
                const lotId = existing.length > 0
                    ? existing[0].id
                    : await this.orm.create("stock.lot", [{ name: lotName, product_id: productId, company_id: companyId }]);
                await this.orm.write("mrp.production", [moId], { lot_producing_id: lotId });
            }
            this.notification.add("Quantity registered successfully", { type: "success" });
            this.closeRegisterQtyModal();
            await this.loadMOs(this.state.selectedWorkcenter);
        } catch (e) {
            this.notification.add("Failed to register quantity: " + (e.message || e), { type: "danger" });
        }
    }

    onRegisterMoveChange(ev) {
        const moveId = parseInt(ev.target.value);
        this.state.registerSelectedMoveId = moveId;
        const move = this.state.registerProducts.find(m => m.id === moveId);
        if (move) this.state.registerQtyValue = move.product_uom_qty || 1;
    }

    // =========================================================
    // Product Catalog (Add Component)
    // =========================================================

    async openCatalogModal(moId) {
        this.closeOptionsModal();
        this.state.catalogMoId = moId;
        this.state.catalogSearch = "";
        this.state.catalogSelectedCat = null;
        this.state.catalogSelectedTag = null;
        this.state.catalogPage = 1;
        this.state.catalogCart = {};
        this.state.catalogLoading = true;
        this.state.showCatalogModal = true;

        // Load categories and tags in parallel
        const [cats, tags] = await Promise.all([
            this.orm.searchRead("product.category", [], ["id", "name", "parent_id"], { order: "complete_name asc" }),
            this.orm.searchRead("product.tag", [], ["id", "name"], { limit: 50 }).catch(() => []),
        ]);
        this.state.catalogCategories = cats;
        this.state.catalogTags = tags;

        await this._loadCatalogPage();
        this.state.catalogLoading = false;
    }

    closeCatalogModal() {
        this.state.showCatalogModal = false;
        this.state.catalogMoId = null;
        this.state.catalogCart = {};
        this.state.catalogProducts = [];
    }

    _buildCatalogDomain() {
        const domain = [["type", "in", ["product", "consu"]]];
        if (this.state.catalogSelectedCat) {
            domain.push(["categ_id", "child_of", this.state.catalogSelectedCat]);
        }
        if (this.state.catalogSelectedTag) {
            domain.push(["tag_ids", "in", [this.state.catalogSelectedTag]]);
        }
        const q = this.state.catalogSearch.trim();
        if (q) {
            domain.push(["|",
                ["name", "ilike", q],
                ["default_code", "ilike", q],
            ]);
        }
        return domain;
    }

    async _loadCatalogPage() {
        const domain = this._buildCatalogDomain();
        const offset = (this.state.catalogPage - 1) * 40;

        const [count, products] = await Promise.all([
            this.orm.call("product.product", "search_count", [domain]),
            this.orm.searchRead(
                "product.product", domain,
                ["id", "name", "display_name", "default_code", "qty_available", "virtual_available", "uom_id", "categ_id"],
                { limit: 40, offset, order: "name asc" }
            ),
        ]);
        this.state.catalogTotalCount = count;
        this.state.catalogProducts = products;
    }

    async catalogSelectCategory(catId) {
        this.state.catalogSelectedCat = catId;
        this.state.catalogSelectedTag = null;
        this.state.catalogPage = 1;
        this.state.catalogLoading = true;
        await this._loadCatalogPage();
        this.state.catalogLoading = false;
    }

    async catalogSelectTag(tagId) {
        this.state.catalogSelectedTag = tagId;
        this.state.catalogSelectedCat = null;
        this.state.catalogPage = 1;
        this.state.catalogLoading = true;
        await this._loadCatalogPage();
        this.state.catalogLoading = false;
    }

    async onCatalogSearchInput(ev) {
        this.state.catalogSearch = ev.target.value;
        this.state.catalogPage = 1;
        this.state.catalogLoading = true;
        await this._loadCatalogPage();
        this.state.catalogLoading = false;
    }

    async catalogPrevPage() {
        if (this.state.catalogPage > 1) {
            this.state.catalogPage -= 1;
            this.state.catalogLoading = true;
            await this._loadCatalogPage();
            this.state.catalogLoading = false;
        }
    }

    async catalogNextPage() {
        if (this.state.catalogPage * 40 < this.state.catalogTotalCount) {
            this.state.catalogPage += 1;
            this.state.catalogLoading = true;
            await this._loadCatalogPage();
            this.state.catalogLoading = false;
        }
    }

    get catalogPageStart() {
        return (this.state.catalogPage - 1) * 40 + 1;
    }

    get catalogPageEnd() {
        return Math.min(this.state.catalogPage * 40, this.state.catalogTotalCount);
    }

    catalogIsInCart(productId) {
        return !!this.state.catalogCart[productId];
    }

    catalogGetQty(productId) {
        return this.state.catalogCart[productId] ? this.state.catalogCart[productId].qty : 0;
    }

    catalogGetUom(productId) {
        return this.state.catalogCart[productId] ? this.state.catalogCart[productId].uom : "Units";
    }

    catalogAddToCart(product) {
        if (this.state.catalogCart[product.id]) {
            this.state.catalogCart[product.id].qty += 1;
        } else {
            this.state.catalogCart[product.id] = {
                qty: 1,
                name: product.display_name || product.name,
                uom: product.uom_id ? product.uom_id[1] : "Units",
                uomId: product.uom_id ? product.uom_id[0] : 1,
                productId: product.id,
            };
        }
    }

    catalogIncreaseQty(productId) {
        if (this.state.catalogCart[productId]) this.state.catalogCart[productId].qty += 1;
    }

    catalogDecreaseQty(productId) {
        if (!this.state.catalogCart[productId]) return;
        if (this.state.catalogCart[productId].qty > 1) {
            this.state.catalogCart[productId].qty -= 1;
        } else {
            // Remove from cart by reassigning the object without this key
            const newCart = {};
            for (const [k, v] of Object.entries(this.state.catalogCart)) {
                if (parseInt(k) !== productId) newCart[k] = v;
            }
            this.state.catalogCart = newCart;
        }
    }

    catalogRemoveFromCart(productId) {
        const newCart = {};
        for (const [k, v] of Object.entries(this.state.catalogCart)) {
            if (parseInt(k) !== productId) newCart[k] = v;
        }
        this.state.catalogCart = newCart;
    }

    catalogSetQty(productId, ev) {
        const val = parseFloat(ev.target.value) || 1;
        if (this.state.catalogCart[productId]) {
            this.state.catalogCart[productId].qty = Math.max(1, val);
        }
    }

    async submitCatalog() {
        const items = Object.values(this.state.catalogCart);
        if (items.length === 0) {
            this.notification.add("No products selected", { type: "warning" });
            return;
        }
        try {
            const moId = this.state.catalogMoId;
            const moData = await this.orm.read("mrp.production", [moId], [
                "location_src_id", "location_dest_id", "company_id",
            ]);
            const mo = moData[0];

            for (const item of items) {
                await this.orm.create("stock.move", [{
                    name: item.name,
                    product_id: item.productId,
                    product_uom_qty: item.qty,
                    quantity_done: item.qty,
                    product_uom: item.uomId,
                    raw_material_production_id: moId,
                    location_id: mo.location_src_id[0],
                    location_dest_id: mo.location_dest_id[0],
                    company_id: mo.company_id[0],
                    state: "confirmed",
                }]);
            }

            this.notification.add(
                `${items.length} component(s) added. They will be reflected in the cost report.`,
                { type: "success" }
            );
            this.closeCatalogModal();
            await this.loadMOs(this.state.selectedWorkcenter);
        } catch (e) {
            console.error(e);
            this.notification.add("Failed to add components: " + (e.message || e), { type: "danger" });
        }
    }

    // =========================================================
    // Add Work Order
    // =========================================================

    async openAddWorkOrderModal(moId) {
        this.closeOptionsModal();
        const mo = this.state.mos.find(m => m.id === moId);

        this.state.addWorkOrderMoId = moId;
        this.state.addWorkOrderTitle = "";
        this.state.addWorkOrderWorkcenterId = null;
        this.state.addWorkOrderDurationMin = 0;
        this.state.addWorkOrderDateStart = "";
        this.state.addWorkOrderEmployeeId = null;
        this.state.addWorkOrderOperations = mo ? mo.workorders : [];
        // Default: insert after the last workorder
        this.state.addWorkOrderInsertAfterId = (mo && mo.workorders.length > 0)
            ? mo.workorders[mo.workorders.length - 1].id
            : null;

        const wcs = this.state.workcenters.filter(wc => wc.id !== "overview");
        this.state.addWorkOrderWorkcentersList = wcs.length > 0 ? wcs
            : await this.orm.searchRead("mrp.workcenter", [], ["id", "name"]);

        this.state.addWorkOrderEmployeesList = await this.orm.searchRead(
            "hr.employee", [], ["id", "name"], { limit: 100 }
        );

        this.state.showAddWorkOrderModal = true;
    }

    closeAddWorkOrderModal() {
        this.state.showAddWorkOrderModal = false;
        this.state.addWorkOrderMoId = null;
    }

    get addWorkOrderDurationDisplay() {
        const total = parseInt(this.state.addWorkOrderDurationMin) || 0;
        const h = Math.floor(total / 60);
        const m = total % 60;
        return `${h}h ${m}m`;
    }

    onAddWorkOrderWcChange(ev) {
        this.state.addWorkOrderWorkcenterId = parseInt(ev.target.value) || null;
    }

    onAddWorkOrderEmpChange(ev) {
        this.state.addWorkOrderEmployeeId = parseInt(ev.target.value) || null;
    }

    onAddWorkOrderInsertAfterChange(ev) {
        this.state.addWorkOrderInsertAfterId = parseInt(ev.target.value) || null;
    }

    async submitAddWorkOrder() {
        if (!this.state.addWorkOrderTitle.trim()) {
            this.notification.add("Please enter a title", { type: "warning" });
            return;
        }
        if (!this.state.addWorkOrderWorkcenterId) {
            this.notification.add("Please select a work center", { type: "warning" });
            return;
        }
        try {
            const moId = this.state.addWorkOrderMoId;
            const moData = await this.orm.read("mrp.production", [moId],
                ["product_id", "company_id", "qty_production"]);
            const mo = moData[0];

            const vals = {
                name: this.state.addWorkOrderTitle.trim(),
                production_id: moId,
                workcenter_id: this.state.addWorkOrderWorkcenterId,
                product_id: mo.product_id[0],
                qty_production: mo.qty_production,
                company_id: mo.company_id[0],
                state: "ready",
                duration_expected: parseInt(this.state.addWorkOrderDurationMin) || 0,
            };
            if (this.state.addWorkOrderDateStart) {
                vals.date_start = this.state.addWorkOrderDateStart;
            }
            if (this.state.addWorkOrderEmployeeId) {
                vals.employee_id = this.state.addWorkOrderEmployeeId;
            }
            await this.orm.create("mrp.workorder", [vals]);

            this.notification.add("Work order added successfully", { type: "success" });
            this.closeAddWorkOrderModal();
            await this.loadMOs(this.state.selectedWorkcenter);
        } catch (e) {
            console.error(e);
            this.notification.add("Failed to add work order: " + (e.message || e), { type: "danger" });
        }
    }

    // =========================================================
    // Log Note
    // =========================================================

    openLogNoteModal(moId) {
        this.closeOptionsModal();
        this.state.logNoteMoId = moId;
        this.state.logNoteText = "";
        this.state.showLogNoteModal = true;
    }

    closeLogNoteModal() {
        this.state.showLogNoteModal = false;
        this.state.logNoteMoId = null;
        this.state.logNoteText = "";
    }

    async submitLogNote() {
        if (!this.state.logNoteText.trim()) {
            this.notification.add("Please enter a note", { type: "warning" });
            return;
        }
        try {
            await this.orm.call("mrp.production", "message_post", [[this.state.logNoteMoId]], {
                body: this.state.logNoteText.trim(),
                message_type: "comment",
                subtype_xmlid: "mail.mt_note",
            });
            this.notification.add("Note logged successfully", { type: "success" });
            this.closeLogNoteModal();
        } catch (e) {
            this.notification.add("Failed to log note: " + (e.message || e), { type: "danger" });
        }
    }
}

registry.category("actions").add("hudson_shopfloor.shopfloor_app", ShopFloorApp);
