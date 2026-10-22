/** @odoo-module **/

import { Component, useState, onWillStart, onWillDestroy, useRef, useEffect, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { View } from "@web/views/view";
import { BarcodeParser } from "@Barcode/utils/barcode_parser";
import { LotDialog } from "@Barcode/components/lot_dialog/lot_dialog";

export class LineScanScreen extends Component {
    setup() {
        this.orm = useService("orm");
        this.barcodeService = useService("barcode_reader_service");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.actionService = useService("action");
        this.videoRef = useRef("videoElement");
        this.stream = null;

        this.state = useState({
            picking: null,
            lines: [],
            showSettings: false,
            showInfo: false,
            showCamera: false,
            showAddProduct: false,
            editingLineId: null,
            showAllocation: false,
            allocationData: null,

            // Settings State
            manualBarcode: '',

            // Inventory Modal
            showConfirmInventoryModal: false,
            inventoryReason: 'Physical Inventory',

            // Lot Dialog
            showLotDialog: false,
            pendingLotProduct: null,

            // Add Product State
            addProductSearchStr: '',
            addProductSearchResults: [],
            addProductSelected: null,
            addProductQty: 1,
            addProductUom: null,
            addProductUomSearchStr: '',
            addProductUomSearchResults: [],
            addProductDestLoc: null,
            addProductDestLocSearchStr: '',
            addProductDestLocSearchResults: [],
            addProductLotName: ''
        });

        useEffect(() => {
            if (this.state.showCamera && this.videoRef.el && this.stream) {
                if (this.videoRef.el.srcObject !== this.stream) {
                    this.videoRef.el.srcObject = this.stream;
                }
                this.videoRef.el.play().catch(e => console.error("Video play failed:", e));

                // Initialize barcode reading loop
                this.scanInterval = setInterval(() => {
                    this.scanFrame();
                }, 300);
            } else {
                if (this.scanInterval) {
                    clearInterval(this.scanInterval);
                    this.scanInterval = null;
                }
            }
        }, () => [this.state.showCamera, this.stream]);

        onWillUnmount(() => {
            this.stopCamera();
        });

        onWillStart(async () => {
            if (this.props.pickingId !== 'inventory') {
                await this.loadPickingState();
            } else {
                await this.loadInventoryState();
            }
        });

        const onScan = this.onBarcodeScanned.bind(this);
        this.barcodeService.addEventListener("barcode_scanned", onScan);

        onWillDestroy(() => {
            this.barcodeService.removeEventListener("barcode_scanned", onScan);
        });
    }

    async loadPickingState() {
        const state = await this.orm.call(
            'stock.picking',
            'get_barcode_view_state',
            [[parseInt(this.props.pickingId)]]
        );
        this.state.picking = state;
        this.state.lines = state.move_line_ids;
        this.parser = new BarcodeParser(state.nomenclature);
    }

    async loadInventoryState() {
        const state = await this.orm.call(
            'stock.quant',
            'get_barcode_inventory_state',
            [[]]
        );
        this.state.picking = {
            id: 'inventory',
            name: state.name,
            location_id: state.default_location_id || null,
            location_dest_id: null,
            partner_id: null
        };
        this.state.lines = state.move_line_ids;
        this.parser = new BarcodeParser(state.nomenclature);
    }

    getProductName(displayName) {
        if (displayName && displayName.startsWith('[')) {
            return displayName.substring(displayName.indexOf(']') + 1).trim();
        }
        return displayName || '';
    }

    getProductCode(displayName) {
        if (displayName && displayName.startsWith('[')) {
            return displayName.substring(1, displayName.indexOf(']'));
        }
        return '';
    }

    async onBarcodeScanned(ev) {
        const barcode = ev.detail.barcode;
        const parsed = this.parser.parse(barcode);

        // 1. Handle Products
        if (parsed.type === 'product' || parsed.type === 'unknown') {
            const products = await this.orm.searchRead(
                'product.product',
                [['barcode', '=', barcode]],
                ['id', 'display_name', 'tracking', 'uom_id']
            );

            if (products.length > 0) {
                const product = products[0];

                if (product.tracking === 'serial' || product.tracking === 'lot') {
                    this.state.pendingLotProduct = product;
                    this.state.showLotDialog = true;
                    return;
                }

                let line = this.state.lines.find(l => l.product_id && (l.product_id.id === product.id || l.product_id[0] === product.id));

                if (line) {
                    line.quantity += 1;
                } else {
                    this.state.lines.unshift({
                        id: 'virtual_' + Math.random(),
                        product_id: { id: product.id, display_name: product.display_name, barcode: barcode, tracking: product.tracking },
                        quantity: 1,
                        quantity_product_uom: 0,
                        uom_id: product.uom_id ? { id: product.uom_id[0], display_name: product.uom_id[1] } : null,
                        location_id: this.state.picking ? this.state.picking.location_id : null,
                        location_dest_id: this.state.picking ? this.state.picking.location_dest_id : null,
                        lot_id: null
                    });
                }
                return;
            }
        }

        // 1.5 Handle Lots directly scanned
        if (parsed.type === 'lot' || parsed.type === 'unknown') {
            if (this.state.showLotDialog) {
                this.onApplyLot(barcode);
                return;
            }

            const lots = await this.orm.searchRead('stock.lot', [['name', '=', barcode]], ['product_id']);
            if (lots.length > 0) {
                const products = await this.orm.searchRead('product.product', [['id', '=', lots[0].product_id[0]]], ['id', 'display_name', 'tracking', 'uom_id']);
                if (products.length > 0) {
                    this.state.pendingLotProduct = products[0];
                    this.onApplyLot(barcode);
                    return;
                }
            }
        }

        // 2. Handle Locations
        if (parsed.type === 'location' || parsed.type === 'unknown') {
            const locations = await this.orm.searchRead(
                'stock.location',
                [['barcode', '=', barcode]],
                ['id', 'display_name']
            );

            if (locations.length > 0) {
                if (this.state.picking) {
                    this.state.picking.location_id = [locations[0].id, locations[0].display_name];
                }
                this.notification.add(`Location set to: ${locations[0].display_name}`, { type: 'success' });
                return;
            }
        }

        // 3. Handle Commands
        if (parsed.type === 'error') {
            this.notification.add(`Invalid barcode scan`, { type: 'danger' });
            return;
        }

        if (parsed.type === 'command' || barcode.startsWith('O-CMD')) {
            if (barcode === 'O-CMD.VALIDATE') {
                this.validate();
                return;
            } else if (barcode === 'O-CMD.RETURN') {
                this.createReturn();
                return;
            } else if (barcode === 'O-CMD.DISCARD' || barcode === 'O-CMD.MAIN-MENU' || barcode === 'O-CMD.CANCEL') {
                this.saveAndGoBack();
                return;
            }
            // Add more commands here if needed in the future
        }

        // If we get here, barcode is unknown
        this.notification.add(`Barcode not recognized: ${barcode} (Parsed as: ${parsed.type})`, { type: 'warning' });
    }

    addQuantity(line, qty) {
        line.quantity += qty;
    }

    removeLine(lineId) {
        this.state.lines = this.state.lines.filter(l => l.id !== lineId);
    }

    toggleSettings() {
        this.state.showSettings = !this.state.showSettings;
        if (this.state.showSettings) this.state.showAddProduct = false;
    }

    async applyManualBarcode() {
        if (!this.state.manualBarcode) return;

        const barcode = this.state.manualBarcode.trim();
        this.state.manualBarcode = '';
        this.toggleSettings(); // Close settings screen

        await this.onBarcodeScanned({ detail: { barcode: barcode } });
    }

    async applyManualBarcodeEvent(e) {
        if (e.key === 'Enter') {
            await this.applyManualBarcode();
        }
    }

    closeConfirmModal() {
        this.state.showConfirmInventoryModal = false;
    }

    async applyInventory(applyNow) {
        this.closeConfirmModal();
        try {
            const commands = [];
            for (let line of this.state.lines) {
                if (String(line.id).startsWith('virtual_')) {
                    commands.push({
                        action: 'create',
                        product_id: line.product_id.id,
                        inventory_quantity: line.quantity,
                        location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : null,
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : line.package_id.id) : null,
                    });
                } else {
                    commands.push({
                        action: 'write',
                        quant_id: line.id,
                        inventory_quantity: line.quantity,
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                    });
                }
            }

            await this.orm.call(
                'stock.quant',
                'process_barcode_inventory_sync',
                [commands, applyNow]
            );
            this.notification.add(applyNow ? "Inventory applied successfully!" : "Inventory saved for review!", { type: "success" });
            this.props.onBack();
        } catch (e) {
            console.error("Validation Error:", e);
            let errorMsg = "An error occurred while validating.";
            if (e.data) {
                if (e.data.arguments && e.data.arguments.length > 0) {
                    errorMsg = e.data.arguments[0];
                } else if (e.data.message) {
                    errorMsg = e.data.message;
                }
            } else if (e.message) {
                errorMsg = e.message;
            }
            this.notification.add(errorMsg, { type: "danger" });
        }
    }

    async saveAndGoBack() {
        try {
            const commands = [];
            for (let line of this.state.lines) {
                if (String(line.id).startsWith('virtual_')) {
                    if (this.props.pickingId === 'inventory') {
                        commands.push({
                            action: 'create',
                            product_id: line.product_id.id,
                            inventory_quantity: line.quantity,
                            location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : null,
                            lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                            lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                            package_id: line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : line.package_id.id) : null,
                        });
                    } else {
                        commands.push({
                            action: 'create',
                            product_id: line.product_id.id,
                            quantity: line.quantity,
                            location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : (this.state.picking.location_id ? this.state.picking.location_id[0] : null),
                            location_dest_id: line.location_dest_id ? (Array.isArray(line.location_dest_id) ? line.location_dest_id[0] : line.location_dest_id.id) : (this.state.picking.location_dest_id ? this.state.picking.location_dest_id[0] : null),
                            product_uom_id: line.uom_id ? (Array.isArray(line.uom_id) ? line.uom_id[0] : line.uom_id.id) : null,
                            lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                            lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                            package_id: line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : line.package_id.id) : null,
                        });
                    }
                } else {
                    if (this.props.pickingId === 'inventory') {
                        commands.push({
                            action: 'write',
                            quant_id: line.id,
                            inventory_quantity: line.quantity,
                            lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                            lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        });
                    } else {
                        commands.push({
                            action: 'write',
                            line_id: line.id,
                            quantity: line.quantity,
                            lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                            lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        });
                    }
                }
            }

            if (commands.length > 0) {
                if (this.props.pickingId === 'inventory') {
                    await this.orm.call(
                        'stock.quant',
                        'process_barcode_inventory_sync',
                        [commands, false]
                    );
                } else {
                    await this.orm.call(
                        'stock.picking',
                        'process_barcode_sync',
                        [[parseInt(this.props.pickingId)], commands]
                    );
                }
            }
        } catch (e) {
            console.error("Auto-save failed on back:", e);
        }

        if (this.props.onBack) {
            this.props.onBack();
        }
    }

    async onApplyLot(lotName) {
        if (!lotName || !this.state.pendingLotProduct) return;
        const product = this.state.pendingLotProduct;

        if (product.tracking === 'serial') {
            this.state.lines.unshift({
                id: 'virtual_' + Math.random(),
                product_id: { id: product.id, display_name: product.display_name, barcode: product.barcode, tracking: product.tracking },
                quantity: 1,
                quantity_product_uom: 0,
                uom_id: product.uom_id ? { id: product.uom_id[0], display_name: product.uom_id[1] } : null,
                location_id: this.state.picking ? this.state.picking.location_id : null,
                location_dest_id: this.state.picking ? this.state.picking.location_dest_id : null,
                lot_id: [null, lotName]
            });
        } else {
            let line = this.state.lines.find(l =>
                l.product_id && (l.product_id.id === product.id || l.product_id[0] === product.id) &&
                l.lot_id && (l.lot_id[1] === lotName || l.lot_id === lotName)
            );

            if (line) {
                line.quantity += 1;
            } else {
                this.state.lines.unshift({
                    id: 'virtual_' + Math.random(),
                    product_id: { id: product.id, display_name: product.display_name, barcode: product.barcode, tracking: product.tracking },
                    quantity: 1,
                    quantity_product_uom: 0,
                    uom_id: product.uom_id ? { id: product.uom_id[0], display_name: product.uom_id[1] } : null,
                    location_id: this.state.picking ? this.state.picking.location_id : null,
                    location_dest_id: this.state.picking ? this.state.picking.location_dest_id : null,
                    lot_id: [null, lotName]
                });
            }
        }

        this.state.showLotDialog = false;
        this.state.pendingLotProduct = null;
    }

    onCancelLot() {
        this.state.showLotDialog = false;
        this.state.pendingLotProduct = null;
    }

    async toggleInfo() {
        this.state.showInfo = !this.state.showInfo;
        if (this.state.showInfo) {
            this.state.showSettings = false;
            this.state.showAddProduct = false;
            this.state.showCamera = false;
            this.state.showAllocation = false;
        }
    }

    closeAllocation() {
        this.state.showAllocation = false;
        this.state.showInfo = true;
    }

    async openAllocation() {
        if (!this.state.picking) return;

        try {
            const data = await this.orm.call(
                'report.stock.report_reception',
                'get_report_data',
                [[this.state.picking.id]],
                { data: false }
            );

            // Group by Product
            const productsMap = {};
            const sourceIdsToFetch = new Set();
            const sourceMap = {};

            if (data.sources_to_lines) {
                for (const sourceKey in data.sources_to_lines) {
                    const lines = data.sources_to_lines[sourceKey];
                    for (const line of lines) {
                        const prodId = line.product.id;
                        if (!productsMap[prodId]) {
                            productsMap[prodId] = {
                                product: line.product,
                                totalAvailable: 0,
                                allocations: []
                            };
                        }

                        // Parse source ID
                        const match = line.source.match(/\((\d+),\)/);
                        if (match) {
                            sourceIdsToFetch.add(parseInt(match[1]));
                        }

                        productsMap[prodId].allocations.push(line);
                    }
                }
            }

            // Fetch names for the sources
            if (sourceIdsToFetch.size > 0) {
                const pickings = await this.orm.searchRead('stock.picking', [['id', 'in', Array.from(sourceIdsToFetch)]], ['name', 'partner_id']);
                for (const p of pickings) {
                    let displayName = p.name;
                    if (p.partner_id) {
                        displayName += `: ${p.partner_id[1]}`;
                    }
                    sourceMap[p.id] = displayName;
                }
            }

            // Format allocations with destination names
            for (const prodId in productsMap) {
                const prod = productsMap[prodId];
                for (const alloc of prod.allocations) {
                    const match = alloc.source.match(/\((\d+),\)/);
                    if (match && sourceMap[parseInt(match[1])]) {
                        alloc.dest_name = sourceMap[parseInt(match[1])];
                    } else {
                        alloc.dest_name = alloc.source;
                    }
                    prod.totalAvailable += alloc.quantity;
                }
            }

            this.state.processedAllocations = Object.values(productsMap);
            this.state.allocationData = data;
            this.state.showAllocation = true;
            this.state.showInfo = false;
        } catch (error) {
            console.error("Failed to fetch allocation data:", error);
            alert("Error fetching allocation data: " + (error.message || JSON.stringify(error)));
        }
    }

    async toggleAllocation(alloc) {
        if (!alloc || !alloc.move_out_id) return;

        if (alloc.is_assigned) {
            // Unassign expects (self, move_id, qty, in_ids)
            await this.orm.call(
                'report.stock.report_reception',
                'action_unassign',
                [false, alloc.move_out_id, alloc.quantity, alloc.move_ins]
            );
        } else {
            // Assign expects (self, move_ids, qtys, in_ids_lists)
            await this.orm.call(
                'report.stock.report_reception',
                'action_assign',
                [false, [alloc.move_out_id], [alloc.quantity], [alloc.move_ins]]
            );
        }
        await this.openAllocation(); // Refresh data
    }

    async assignAll() {
        if (!this.state.processedAllocations) return;

        const moveIds = [];
        const qtys = [];
        const inIds = [];
        for (const prod of this.state.processedAllocations) {
            for (const alloc of prod.allocations) {
                if (!alloc.is_assigned && alloc.move_out_id) {
                    moveIds.push(alloc.move_out_id);
                    qtys.push(alloc.quantity);
                    inIds.push(alloc.move_ins);
                }
            }
        }

        if (moveIds.length > 0) {
            await this.orm.call(
                'report.stock.report_reception',
                'action_assign',
                [false, moveIds, qtys, inIds]
            );
            await this.openAllocation(); // Refresh data
        } else {
            alert("All items are already assigned.");
        }
    }

    async printAllocationLabel(alloc) {
        if (!alloc || !alloc.move_out_id) return;

        const modelIds = [alloc.move_out_id];
        const productQtys = [Math.ceil(alloc.quantity) || 1];

        try {
            const reports = await this.orm.searchRead("ir.actions.report", [
                ["report_name", "=", "stock.report_reception_report_label"]
            ]);
            if (reports && reports.length > 0) {
                const labelReport = reports[0];
                return this.actionService.doAction({
                    ...labelReport,
                    context: { active_ids: modelIds },
                    data: { docids: modelIds, quantity: productQtys.join(",") }
                });
            } else {
                this.notification.add("Label report not found.", { type: "warning" });
            }
        } catch (error) {
            console.error("Failed to print label:", error);
            this.notification.add("Error printing label.", { type: "danger" });
        }
    }

    async printLabels() {
        const moves = await this.orm.searchRead('stock.move', [['picking_id', '=', this.state.picking.id]], ['id']);
        const moveIds = moves.map(m => m.id);

        if (moveIds.length === 0) {
            console.log("No moves to print labels for.");
            return;
        }

        const action = {
            type: 'ir.actions.report',
            report_type: 'qweb-pdf',
            report_name: 'stock.report_reception_report_label',
            data: { docids: moveIds }
        };
        this.actionService.doAction(action);
    }

    async printReport() {
        if (!this.state.picking) return;

        try {
            const reports = await this.orm.searchRead("ir.actions.report", [
                ["report_name", "=", "stock.report_picking"]
            ]);
            if (reports && reports.length > 0) {
                const reportAction = reports[0];
                return this.actionService.doAction({
                    ...reportAction,
                    context: { active_ids: [this.state.picking.id] }
                });
            } else {
                console.warn("Picking report not found.");
            }
        } catch (error) {
            console.error("Failed to print report:", error);
        }
    }

    formatDate(dateString) {
        if (!dateString) return '';
        // Assuming dateString is "YYYY-MM-DD HH:mm:ss"
        const date = new Date(dateString.replace(' ', 'T') + 'Z');
        return date.toLocaleString('en-US', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true });
    }

    getObjectKeys(obj) {
        return obj ? Object.keys(obj) : [];
    }

    toJson(obj) {
        try {
            return JSON.stringify(obj, null, 2);
        } catch (e) {
            return String(obj);
        }
    }

    formatPriority(priority) {
        return priority === '1' ? 'Urgent' : 'Normal';
    }

    formatStatus(state) {
        const statuses = {
            'draft': 'Draft',
            'waiting': 'Waiting Another Operation',
            'confirmed': 'Waiting',
            'assigned': 'Ready',
            'done': 'Done',
            'cancel': 'Cancelled'
        };
        return statuses[state] || state;
    }

    toggleAddProduct() {
        this.state.showAddProduct = !this.state.showAddProduct;
        if (this.state.showAddProduct) {
            this.state.editingLineId = null;
            this.state.showSettings = false;
            this.state.addProductSearchStr = '';
            this.state.addProductSearchResults = [];
            this.state.addProductSelected = null;
            this.state.addProductQty = 1;
            this.state.addProductLotName = '';
            this.state.addProductUom = null;
            this.state.addProductUomSearchStr = '';
            this.state.addProductUomSearchResults = [];
            this.state.addProductDestLoc = this.state.picking ? this.state.picking.location_dest_id : null;
            this.state.addProductDestLocSearchStr = this.state.addProductDestLoc ? this.state.addProductDestLoc[1] : 'WH/Input';
            this.state.addProductDestLocSearchResults = [];
        }
    }

    editLine(lineId) {
        const line = this.state.lines.find(l => l.id === lineId);
        if (!line) return;

        this.state.editingLineId = lineId;
        this.state.showAddProduct = true;
        this.state.showSettings = false;

        this.state.addProductSearchStr = line.product_id.display_name;
        this.state.addProductSearchResults = [];
        this.state.addProductSelected = {
            id: line.product_id.id,
            display_name: line.product_id.display_name,
            default_code: this.getProductCode(line.product_id.display_name),
            tracking: line.product_id.tracking || 'none'
        };

        this.state.addProductQty = line.quantity;

        let lotName = '';
        if (line.lot_id) {
            lotName = Array.isArray(line.lot_id) ? line.lot_id[1] : line.lot_id;
        }
        this.state.addProductLotName = lotName;

        if (line.product_uom_id) {
            this.state.addProductUom = [line.product_uom_id.id, line.product_uom_id.display_name];
            this.state.addProductUomSearchStr = line.product_uom_id.display_name;
        } else {
            this.state.addProductUom = null;
            this.state.addProductUomSearchStr = '';
        }

        if (line.location_dest_id) {
            this.state.addProductDestLoc = [line.location_dest_id.id, line.location_dest_id.display_name];
            this.state.addProductDestLocSearchStr = line.location_dest_id.display_name;
        } else {
            this.state.addProductDestLoc = this.state.picking ? this.state.picking.location_dest_id : null;
            this.state.addProductDestLocSearchStr = this.state.addProductDestLoc ? this.state.addProductDestLoc[1] : 'WH/Input';
        }
        this.state.addProductUomSearchResults = [];
        this.state.addProductDestLocSearchResults = [];
    }

    async onProductSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductSearchStr = val;
        this.state.addProductSelected = null;

        let domain = [];
        if (val) {
            domain = ['|', ['name', 'ilike', val], ['barcode', '=', val]];
        }

        const results = await this.orm.searchRead(
            'product.product',
            domain,
            ['id', 'display_name', 'barcode', 'default_code', 'uom_id', 'tracking'],
            { limit: 10 }
        );
        this.state.addProductSearchResults = results;
    }

    async onProductFocus() {
        if (!this.state.addProductSelected && this.state.addProductSearchResults.length === 0) {
            const results = await this.orm.searchRead(
                'product.product',
                [],
                ['id', 'display_name', 'barcode', 'default_code', 'uom_id', 'tracking'],
                { limit: 10 }
            );
            this.state.addProductSearchResults = results;
        }
    }

    async selectProduct(product) {
        this.state.addProductSelected = product;
        this.state.addProductSearchStr = product.display_name;
        this.state.addProductSearchResults = [];
        this.state.addProductUom = product.uom_id;
        this.state.addProductUomSearchStr = product.uom_id ? product.uom_id[1] : '';

        // Fetch default destination location based on putaway rules
        try {
            let domain = [['product_id', '=', product.id]];
            if (this.state.picking && this.state.picking.location_dest_id) {
                domain = ['&', ['product_id', '=', product.id], ['location_in_id', '=', this.state.picking.location_dest_id[0]]];
            }

            const rules = await this.orm.searchRead('stock.putaway.rule', domain, ['location_out_id'], { limit: 1 });

            if (rules.length > 0 && rules[0].location_out_id) {
                this.state.addProductDestLoc = rules[0].location_out_id;
                this.state.addProductDestLocSearchStr = rules[0].location_out_id[1];
            } else {
                // If no exact match, try without location_in_id
                const anyRules = await this.orm.searchRead('stock.putaway.rule', [['product_id', '=', product.id]], ['location_out_id'], { limit: 1 });
                if (anyRules.length > 0 && anyRules[0].location_out_id) {
                    this.state.addProductDestLoc = anyRules[0].location_out_id;
                    this.state.addProductDestLocSearchStr = anyRules[0].location_out_id[1];
                } else {
                    this.state.addProductDestLoc = this.state.picking ? this.state.picking.location_dest_id : null;
                    this.state.addProductDestLocSearchStr = this.state.addProductDestLoc ? this.state.addProductDestLoc[1] : 'WH/Input';
                }
            }
        } catch (e) {
            console.error("Could not fetch putaway rules:", e);
        }
    }

    async onUomSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductUomSearchStr = val;

        let domain = [];
        if (val) {
            domain = [['name', 'ilike', val]];
        }

        const results = await this.orm.searchRead(
            'uom.uom',
            domain,
            ['id', 'name'],
            { limit: 5 }
        );
        this.state.addProductUomSearchResults = results;
    }

    async onUomFocus() {
        const results = await this.orm.searchRead(
            'uom.uom',
            [],
            ['id', 'name'],
            { limit: 10 }
        );
        this.state.addProductUomSearchResults = results;
    }

    selectUom(uom) {
        this.state.addProductUom = [uom.id, uom.name];
        this.state.addProductUomSearchStr = uom.name;
        this.state.addProductUomSearchResults = [];
    }

    async onDestLocSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductDestLocSearchStr = val;

        let domain = [];
        if (val) {
            domain.push(['display_name', 'ilike', val]);
        }

        const results = await this.orm.searchRead(
            'stock.location',
            domain,
            ['id', 'display_name'],
            { limit: 10 }
        );
        this.state.addProductDestLocSearchResults = results;
    }

    async onDestLocFocus() {
        await this.onDestLocSearchInput({ target: { value: '' } });
    }

    selectDestLoc(loc) {
        this.state.addProductDestLoc = [loc.id, loc.display_name];
        this.state.addProductDestLocSearchStr = loc.display_name;
        this.state.addProductDestLocSearchResults = [];
    }

    closeDropdowns() {
        this.state.addProductSearchResults = [];
        this.state.addProductUomSearchResults = [];
        this.state.addProductDestLocSearchResults = [];
    }

    openSearchMore(type) {
        this.closeDropdowns();
        let resModel, title, callback;
        if (type === 'product') {
            resModel = 'product.product';
            title = 'Search: Product';
            callback = async (resId) => {
                const prods = await this.orm.read('product.product', [resId], ['id', 'display_name', 'barcode', 'default_code', 'uom_id', 'tracking']);
                if (prods.length > 0) this.selectProduct(prods[0]);
            };
        } else if (type === 'uom') {
            resModel = 'uom.uom';
            title = 'Search: Unit of Measure';
            callback = async (resId) => {
                const uoms = await this.orm.read('uom.uom', [resId], ['id', 'name']);
                if (uoms.length > 0) this.selectUom(uoms[0]);
            };
        } else if (type === 'dest_loc') {
            resModel = 'stock.location';
            title = 'Search: Destination Location';
            callback = async (resId) => {
                const locs = await this.orm.read('stock.location', [resId], ['id', 'display_name']);
                if (locs.length > 0) this.selectDestLoc(locs[0]);
            };
        }

        this.dialog.add(SelectCreateDialog, {
            resModel: resModel,
            title: title,
            multiSelect: false,
            onSelected: (resIds) => {
                if (resIds && resIds.length > 0) {
                    callback(resIds[0]);
                }
            },
        });
    }

    setAddProductQty(delta) {
        if (delta === 0) {
            this.state.addProductQty = 0;
        } else {
            this.state.addProductQty = Math.max(0, this.state.addProductQty + delta);
        }
    }

    onAddProductQtyInput(ev) {
        this.state.addProductQty = parseFloat(ev.target.value) || 0;
    }

    confirmAddProduct() {
        if (!this.state.addProductSelected) {
            this.notification.add("Please select a product first.", { type: "danger" });
            return;
        }

        if (this.state.addProductQty <= 0) {
            this.notification.add("Quantity must be greater than 0.", { type: "danger" });
            return;
        }

        // Add or Edit line
        if (this.state.editingLineId) {
            let existingLine = this.state.lines.find(l => l.id === this.state.editingLineId);
            if (existingLine) {
                existingLine.product_id = { id: this.state.addProductSelected.id, display_name: this.state.addProductSelected.display_name || this.state.addProductSelected.name || this.state.addProductSearchStr, tracking: this.state.addProductSelected.tracking };
                existingLine.quantity = this.state.addProductQty;
                existingLine.location_dest_id = this.state.addProductDestLoc ? { id: this.state.addProductDestLoc[0], display_name: this.state.addProductDestLoc[1] } : null;
                existingLine.product_uom_id = this.state.addProductUom ? { id: this.state.addProductUom[0], display_name: this.state.addProductUom[1] } : null;

                if (this.state.addProductLotName) {
                    existingLine.lot_id = [null, this.state.addProductLotName];
                } else {
                    existingLine.lot_id = null;
                }
            }
            this.state.editingLineId = null;
            this.notification.add("Line updated.", { type: "success" });
        } else {
            let existingLine = this.state.lines.find(l =>
                (l.product_id[0] === this.state.addProductSelected.id || l.product_id.id === this.state.addProductSelected.id) &&
                (!this.state.addProductLotName || (l.lot_id && (l.lot_id[1] === this.state.addProductLotName || l.lot_id === this.state.addProductLotName)))
            );

            if (existingLine && this.state.addProductSelected.tracking !== 'serial') {
                existingLine.quantity += this.state.addProductQty;
            } else {
                this.state.lines.unshift({
                    id: 'virtual_' + Math.random(),
                    product_id: { id: this.state.addProductSelected.id, display_name: this.state.addProductSelected.display_name || this.state.addProductSelected.name, tracking: this.state.addProductSelected.tracking },
                    quantity: this.state.addProductQty,
                    quantity_product_uom: 0,
                    location_id: this.state.picking ? this.state.picking.location_id : null,
                    location_dest_id: this.state.addProductDestLoc ? { id: this.state.addProductDestLoc[0], display_name: this.state.addProductDestLoc[1] } : null,
                    product_uom_id: this.state.addProductUom ? { id: this.state.addProductUom[0], display_name: this.state.addProductUom[1] } : null,
                    lot_id: this.state.addProductLotName ? [null, this.state.addProductLotName] : null
                });
            }
            this.notification.add("Product added.", { type: "success" });
        }

        this.toggleAddProduct();
    }

    async loadZXing() {
        if (!window.ZXing) {
            return new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = "https://unpkg.com/@zxing/library@0.21.2/umd/index.min.js";
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }
    }

    async toggleCamera() {
        if (this.state.showCamera) {
            this.closeCamera();
        } else {
            await this.openCamera();
        }
    }

    async openCamera() {
        await this.loadZXing();

        if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
            alert("Camera access requires a secure connection (HTTPS). Please access Odoo via HTTPS or use localhost.");
            return;
        }

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("Camera access is not supported by your browser or is blocked. Please ensure you are using HTTPS and have granted camera permissions.");
            return;
        }

        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "environment" }
            });
            this.state.showCamera = true;
        } catch (err) {
            console.error("Error accessing camera:", err);
            this.notification.add("Could not access the camera. Please ensure permissions are granted.", { type: "danger" });
        }
    }

    stopCamera() {
        if (this.scanInterval) {
            clearInterval(this.scanInterval);
            this.scanInterval = null;
        }
        if (this.codeReader) {
            this.codeReader.reset();
            this.codeReader = null;
        }
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
    }

    async scanFrame() {
        if (!this.state.showCamera || !this.videoRef.el || this.videoRef.el.readyState !== 4) return;

        // Native BarcodeDetector (Android Chrome)
        if (window.BarcodeDetector) {
            try {
                if (!this.detector) this.detector = new BarcodeDetector();
                const barcodes = await this.detector.detect(this.videoRef.el);
                if (barcodes.length > 0) {
                    this.handleScan(barcodes[0].rawValue);
                    return;
                }
            } catch (e) {
                // ignore
            }
        }

        // ZXing Fallback
        if (window.ZXing && !this.codeReader) {
            this.codeReader = new window.ZXing.BrowserMultiFormatReader();
        }
        if (this.codeReader) {
            try {
                if (!this.canvas) {
                    this.canvas = document.createElement('canvas');
                    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
                }
                this.canvas.width = this.videoRef.el.videoWidth;
                this.canvas.height = this.videoRef.el.videoHeight;
                this.ctx.drawImage(this.videoRef.el, 0, 0, this.canvas.width, this.canvas.height);

                const result = this.codeReader.decodeFromCanvas(this.canvas);
                if (result && result.text) {
                    this.handleScan(result.text);
                }
            } catch (e) {
                // ignore
            }
        }
    }

    handleScan(text) {
        if (!this.state.showCamera) return;
        console.log("Scanned:", text);
        this.onBarcodeScanned({ detail: { barcode: text } });
        this.closeCamera();
    }

    closeCamera() {
        this.stopCamera();
        this.state.showCamera = false;
    }

    async validate() {
        if (this.props.pickingId === 'inventory') {
            this.state.showConfirmInventoryModal = true;
            return;
        }

        try {
            const commands = [];

            // Build the sync commands based on whether it is an inventory adjustment or a transfer
            for (let line of this.state.lines) {
                if (String(line.id).startsWith('virtual_')) {
                    commands.push({
                        action: 'create',
                        product_id: line.product_id.id,
                        quantity: line.quantity,
                        location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : (this.state.picking.location_id ? this.state.picking.location_id[0] : null),
                        location_dest_id: line.location_dest_id ? (Array.isArray(line.location_dest_id) ? line.location_dest_id[0] : line.location_dest_id.id) : (this.state.picking.location_dest_id ? this.state.picking.location_dest_id[0] : null),
                        product_uom_id: line.uom_id ? (Array.isArray(line.uom_id) ? line.uom_id[0] : line.uom_id.id) : null,
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : line.package_id.id) : null,
                    });
                } else {
                    commands.push({
                        action: 'write',
                        line_id: line.id,
                        quantity: line.quantity,
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                    });
                }
            }

            await this.orm.call(
                'stock.picking',
                'process_barcode_sync',
                [[parseInt(this.props.pickingId)], commands]
            );

            // Try to validate the transfer initially
            let result = await this.orm.call(
                'stock.picking',
                'button_validate',
                [[parseInt(this.props.pickingId)]]
            );

            // If it returned the Immediate Transfer wizard, it means there are no pending quality checks
            // but the user hasn't scanned any quantities. We auto-fill the quantities and re-validate!
            if (typeof result === 'object' && result !== null && result.type === 'ir.actions.act_window' && result.res_model === 'stock.immediate.transfer') {
                await this.orm.call('stock.picking', 'action_barcode_autofill', [[parseInt(this.props.pickingId)]]);
                result = await this.orm.call(
                    'stock.picking',
                    'button_validate',
                    [[parseInt(this.props.pickingId)]]
                );
            }

            if (typeof result === 'object' && result !== null && result.type && result.type.startsWith('ir.actions')) {
                // Inject missing properties that Odoo's Python action manager normally fills in,
                // to prevent JS crashes inside _preprocessAction.
                if (result.type === 'ir.actions.act_window') {
                    if (!result.views) {
                        if (result.view_mode) {
                            result.views = result.view_mode.split(',').map(mode => [false, mode.trim()]);
                        } else {
                            result.views = [[false, 'form']];
                        }
                    }
                    if (!result.domain) result.domain = [];
                    if (!result.context) result.context = {};

                    // Inject active record context so wizards (like Quality Checks or Backorders) know which transfer to process
                    result.context.active_model = 'stock.picking';
                    result.context.active_id = parseInt(this.props.pickingId);
                    result.context.active_ids = [parseInt(this.props.pickingId)];
                }

                this.actionService.doAction(result, {
                    onClose: async () => {
                        await this.loadPickingState();
                        if (this.state.picking && this.state.picking.state === 'done') {
                            this.notification.add("Transfer validated successfully!", { type: "success" });
                            this.props.onBack();
                        }
                    }
                });
            } else {
                this.notification.add("Transfer validated successfully!", { type: "success" });
                this.props.onBack();
            }
        } catch (e) {
            console.error("Validation Error:", e);
            let errorMsg = "An error occurred while validating.";
            if (e.data) {
                if (e.data.arguments && e.data.arguments.length > 0) {
                    errorMsg = e.data.arguments[0];
                } else if (e.data.message) {
                    errorMsg = e.data.message;
                }
            } else if (e.message) {
                errorMsg = e.message;
            }
            this.notification.add(errorMsg, { type: "danger" });
        }
    }

    async createReturn() {
        if (!this.state.picking || this.state.picking.state !== 'done') {
            this.notification.add("Only done pickings can be returned.", { type: "warning" });
            return;
        }

        try {
            const newPickingId = await this.orm.call(
                'stock.picking',
                'action_barcode_create_return',
                [[parseInt(this.props.pickingId)]]
            );

            if (newPickingId) {
                this.notification.add("Return created! Scan products to return.", { type: "success" });
                this.actionService.doAction({
                    type: 'ir.actions.client',
                    tag: 'custom_barcode_client_action',
                    params: {
                        picking_id: newPickingId
                    }
                }, { clearBreadcrumbs: true });
            }
        } catch (e) {
            console.error("Return Error:", e);
            const errorMsg = e.data && e.data.message ? e.data.message : (e.message || "Error creating return.");
            this.notification.add(errorMsg, { type: "danger" });
        }
    }
}

LineScanScreen.template = "custom_barcode_scanner.LineScanScreen";
LineScanScreen.components = { View, LotDialog };
LineScanScreen.props = ["pickingId", "onBack"];
