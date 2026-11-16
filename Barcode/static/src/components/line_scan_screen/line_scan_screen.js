/** @odoo-module **/

import { Component, proxy, onWillStart, onWillDestroy, signal, onWillUnmount, useProps } from "@odoo/owl";
import { useLayoutEffect } from "@web/owl2/utils";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { getColor } from "@web/core/colors/colors";
import { cookie } from "@web/core/browser/cookie";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { View } from "@web/views/view";
import { BarcodeParser } from "@Barcode/utils/barcode_parser";
import { LotDialog } from "@Barcode/components/lot_dialog/lot_dialog";

export class LineScanScreen extends Component {
    // props: pickingId, pickingTypeId, batchId, batchName (all optional),
    //        onBack (Function), openPicking (Function, optional)
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.barcodeService = useService("barcode_reader_service");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.actionService = useService("action");
        this.videoRef = signal.ref();
        this.stream = null;

        this.state = proxy({
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
            countEntire: true,

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
            addProductLotName: '',

            // Location Scanning State
            activeSourceLocation: null,

            // Inventory > Settings > Packages (stock.group_tracking_lot)
            canPutInPack: false,
            // Manufacturing: Register By-Products (setting + mode)
            canRegisterByProducts: false,
            // Inventory > Settings > Consignment (stock.group_tracking_owner): Owner field
            canUseOwner: false,
            addProductOwner: null,
            addProductOwnerSearchStr: '',
            addProductOwnerSearchResults: [],
            showOwnerDropdown: false,
            byProductMode: false
        });

        useLayoutEffect(() => {
            if (this.state.showCamera && this.videoRef() && this.stream) {
                if (this.videoRef().srcObject !== this.stream) {
                    this.videoRef().srcObject = this.stream;
                }
                this.videoRef().play().catch(e => console.error("Video play failed:", e));

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
            try {
                this.state.canPutInPack = await user.hasGroup("stock.group_tracking_lot");
            } catch (e) {
                this.state.canPutInPack = false;
            }
            try {
                this.state.canUseOwner = await user.hasGroup("stock.group_tracking_owner");
            } catch (e) {
                this.state.canUseOwner = false;
            }
            try {
                // Manufacturing > Settings > By-Products (mrp.group_mrp_byproducts)
                this.state.canRegisterByProducts = await user.hasGroup("mrp.group_mrp_byproducts");
            } catch (e) {
                this.state.canRegisterByProducts = false;
            }
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
        // ── BATCH MODE ──────────────────────────────────────────────
        if (this.props.batchId) {
            const batchState = await this.orm.call(
                'stock.picking.batch',
                'get_barcode_view_state',
                [[parseInt(this.props.batchId)]]
            );
            // Represent the batch as the "picking" so the header renders
            this.state.picking = {
                id: null,
                name: batchState.name,
                batch_id: batchState.id,
                batch_name: batchState.name,
                state: batchState.state,
                pickings: batchState.pickings,
                location_id: batchState.pickings.length ? batchState.pickings[0].location_id : null,
                location_dest_id: batchState.pickings.length ? batchState.pickings[0].location_dest_id : null,
                partner_id: null,
            };

            // Map each move line — preserve picking_id
            const isBatchReload = Boolean(this.state.lines && this.state.lines.length);
            const newLines = batchState.move_lines.map(line => {
                const existing = this.state.lines ? this.state.lines.find(l => l.id === line.id) : null;
                // same rule as single transfers: a line that appears on reload already packed
                // holds what was just scanned and packed -> keep its quantity
                const keepPacked = !existing && isBatchReload && line.result_package_id && line.quantity > 0;
                return {
                    ...line,
                    quantity: existing ? existing.quantity : (keepPacked ? line.quantity : 0),
                    picked: existing ? existing.picked : false,
                    // Preserve picking reference
                    picking_id: line.picking_id,
                };
            });
            this.state.lines = newLines;

            // One colour per transfer of the batch (Odoo Online style), in batch order,
            // from Odoo's own palette (dark variant when the dark theme is active).
            const colorScheme = cookie.get("color_scheme") === "dark" ? "dark" : "light";
            this.pickingColors = {};
            (batchState.pickings || []).forEach((picking, index) => {
                this.pickingColors[picking.id] = getColor(index, colorScheme, "sm");
            });

            // Same parser as single transfers, from the company's barcode nomenclature
            this.parser = new BarcodeParser(batchState.nomenclature || []);
            return;
        }

        // ── NEW MANUFACTURING ORDER (nothing created until a product is scanned) ──
        if (this.isNewMO) {
            const newState = await this.orm.call('mrp.production', 'barcode_get_new_production_state', [parseInt(this.props.pickingTypeId) || false]);
            this.state.picking = {
                id: null,
                name: 'New',
                state: 'draft',
                location_id: false,
                location_dest_id: newState.location_dest_id || false,
                partner_id: false,
            };
            this.state.lines = [];
            this.parser = new BarcodeParser(newState.nomenclature || []);
            return;
        }

        // ── NORMAL PICKING MODE ─────────────────────────────────────
        let model = 'stock.picking';
        if (this.props.pickingTypeId && this.props.pickingTypeId !== 'inventory') {
            try {
                const pt = await this.orm.read('stock.picking.type', [parseInt(this.props.pickingTypeId)], ['code']);
                if (pt.length && pt[0].code === 'mrp_operation') {
                    model = 'mrp.production';
                }
            } catch (e) {
                console.warn(e);
            }
        }

        const state = await this.orm.call(
            model,
            'get_barcode_view_state',
            [[parseInt(this.props.pickingId)]]
        );
        this.state.picking = state;

        // Reload during the session (e.g. after Put in Pack) vs. first opening of the transfer
        const isReload = Boolean(this.state.lines && this.state.lines.length);
        for (let line of state.move_line_ids) {
            let existingLine = this.state.lines ? this.state.lines.find(l => l.id === line.id) : null;
            // Force reset to 0 to require barcode scanning unless it's already recorded in existing state
            if (!existingLine && isReload && line.result_package_id && line.quantity > 0) {
                // A line that appeared on reload already packed holds what was just scanned and
                // packed in this session (Put in Pack splits/creates lines): keep its quantity.
            } else if (!existingLine) {
                line.quantity = 0;
                line.picked = false;
            } else {
                line.quantity = existingLine.quantity;
                line.picked = existingLine.picked;
            }
        }

        if (isReload && model === 'mrp.production') {
            // MO: components / by-products added on screen are saved once, on Produce; a reload
            // (e.g. after Put in Pack) must keep them, like Odoo Online
            const serverIds = new Set(state.move_line_ids.map((l) => String(l.id)));
            const pending = this.state.lines.filter((l) => String(l.id).startsWith('virtual_') && !serverIds.has(String(l.id)));
            state.move_line_ids.push(...pending);
        }
        this.state.lines = state.move_line_ids;
        this.parser = new BarcodeParser(state.nomenclature);
    }

    async loadInventoryState(locationId = null) {
        let domain = null;
        if (locationId) {
            if (this.state.countEntire) {
                domain = [['location_id', 'child_of', locationId]];
            } else {
                domain = [['location_id', '=', locationId], ['inventory_quantity_set', '=', true]];
            }
        }
        const state = await this.orm.call(
            'stock.quant',
            'get_barcode_inventory_state',
            [domain ? domain : []]
        );
        this.state.picking = {
            id: 'inventory',
            name: state.name,
            // default_location_id already comes as [id, name] (wrapping it again sent a list as the location)
            location_id: locationId
                ? [locationId, (this.state.picking && this.state.picking.location_id && this.state.picking.location_id[0] === locationId ? this.state.picking.location_id[1] : "")]
                : (state.default_location_id || null),
            location_dest_id: null,
            partner_id: null
        };
        this.state.lines = state.move_line_ids;
        this.parser = new BarcodeParser(state.nomenclature);
    }

    /** 'New' manufacturing order (Odoo Online): no MO yet, the first product sets what to produce. */
    get isNewMO() {
        return this.props.pickingId === 'new_mo';
    }

    get isMO() {
        return this.isNewMO || (this.state.lines && this.state.lines.some(l => l.is_finished_product !== undefined));
    }

    /** New MO: create it for this product (with its BoM) and open it. */
    async createProductionFor(product, qty = 1) {
        if (this.creatingProduction) {
            return;
        }
        this.creatingProduction = true;
        try {
            const productionId = await this.orm.call('mrp.production', 'barcode_create_production',
                [parseInt(this.props.pickingTypeId), product.id, qty]);
            this.notification.add(`Manufacturing order created for ${product.display_name || product.name}.`, { type: 'success' });
            if (this.props.openPicking) {
                this.props.openPicking(productionId);
            }
        } catch (e) {
            const msg = e.data && e.data.message ? e.data.message : (e.message || 'Could not create the manufacturing order.');
            this.notification.add(msg, { type: 'danger' });
        } finally {
            this.creatingProduction = false;
        }
    }

    get producingLines() {
        return (this.state.lines || []).filter(l => l.is_finished_product);
    }

    get componentLines() {
        return (this.state.lines || []).filter(l => !l.is_finished_product && !l.is_byproduct);
    }

    get byproductLines() {
        return (this.state.lines || []).filter(l => l.is_byproduct);
    }

    /** Lines listed under the header: components, or by-products in Register By-Products mode. */
    get displayedLines() {
        if (!this.isMO) {
            return this.state.lines;
        }
        return this.state.byProductMode ? this.byproductLines : this.componentLines;
    }

    /** 'Register By-Products' button: MO still to produce + By-Products setting enabled. */
    get showByProductButton() {
        return Boolean(this.isMO && !this.isNewMO && this.state.canRegisterByProducts && !this.state.byProductMode
            && this.state.picking && !['done', 'cancel'].includes(this.state.picking.state));
    }

    toggleByProductMode() {
        this.state.byProductMode = !this.state.byProductMode;
        this.state.showAddProduct = false;
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

        if (barcode === 'O-CMD.PUT-IN-PACK') {
            await this.putInPack();
            return;
        }

        const parsed = this.parser.parse(barcode);

        // 1. Handle Location Barcodes
        if (parsed.type === 'location') {
            const locations = await this.orm.searchRead('stock.location', [['barcode', '=', barcode]], ['id', 'display_name', 'barcode']);
            if (locations.length > 0) {
                this.state.activeSourceLocation = locations[0];
                this.notification.add(`Source Location set to: ${locations[0].display_name}`, { type: "success" });
                return;
            }
        }

        // 2. Handle Products
        if (parsed.type === 'product' || parsed.type === 'unknown') {
            const products = await this.orm.searchRead(
                'product.product',
                [['barcode', '=', barcode]],
                ['id', 'display_name', 'tracking', 'uom_id']
            );

            if (products.length > 0) {
                const product = products[0];

                if (this.isNewMO) {
                    await this.createProductionFor(product, 1);
                    return;
                }

                if (product.tracking === 'serial' || product.tracking === 'lot') {
                    this.state.pendingLotProduct = product;
                    this.state.showLotDialog = true;
                    return;
                }

                if (this.isMO && this.state.byProductMode) {
                    this.registerByProduct(product, barcode, 1);
                    return;
                }

                let line = null;
                // If activeSourceLocation is set, try to find a line for this exact product and location
                if (this.state.activeSourceLocation) {
                    line = this.state.lines.find(l =>
                        l.product_id && (l.product_id.id === product.id || l.product_id[0] === product.id) &&
                        l.location_id && (l.location_id.id === this.state.activeSourceLocation.id || l.location_id[0] === this.state.activeSourceLocation.id)
                    );
                }

                // If no exact match found (or no active location set), find any line for this product that still needs quantity
                if (!line) {
                    line = this.state.lines.find(l =>
                        l.product_id && (l.product_id.id === product.id || l.product_id[0] === product.id) &&
                        (l.quantity < l.product_uom_qty || !l.product_uom_qty)
                    );
                }

                // If we found a line but it has a different location than activeSourceLocation, and we need to pick from activeSourceLocation
                if (line && this.state.activeSourceLocation &&
                    !(line.location_id && (line.location_id.id === this.state.activeSourceLocation.id || line.location_id[0] === this.state.activeSourceLocation.id))) {

                    // Create a virtual split line for this new location
                    const newLine = {
                        id: 'virtual_' + Math.random(),
                        product_id: line.product_id,
                        quantity: 1,
                        product_uom_qty: 0, // Demand remains on the original line, or is split conceptually
                        uom_id: line.uom_id,
                        location_id: { id: this.state.activeSourceLocation.id, display_name: this.state.activeSourceLocation.display_name, barcode: this.state.activeSourceLocation.barcode },
                        location_dest_id: line.location_dest_id,
                        move_id: line.move_id,
                        picked: true,
                        dummy: true
                    };
                    this.state.lines.unshift(newLine);
                    this.syncWithBackend();
                    return;
                }

                if (line) {
                    this.incrementQuantity(line, 1);
                } else {
                    // Create a new virtual line if no line at all exists for this product
                    this.state.lines.unshift({
                        id: 'virtual_' + Math.random(),
                        product_id: { id: product.id, display_name: product.display_name, barcode: barcode, tracking: product.tracking },
                        quantity: 1,
                        product_uom_qty: 0,
                        uom_id: product.uom_id ? { id: product.uom_id[0], display_name: product.uom_id[1] } : null,
                        location_id: this.state.activeSourceLocation ? { id: this.state.activeSourceLocation.id, display_name: this.state.activeSourceLocation.display_name } : (this.state.picking && this.state.picking.location_id ? { id: this.state.picking.location_id[0], display_name: this.state.picking.location_id[1] } : null),
                        location_dest_id: this.state.picking && this.state.picking.location_dest_id ? { id: this.state.picking.location_dest_id[0], display_name: this.state.picking.location_dest_id[1] } : null,
                        dummy: true,
                        picked: true
                    });
                    this.syncWithBackend();
                }
                return;
            }
        }

        // 1.25 Handle Packages
        if (parsed.type === 'package' || parsed.type === 'unknown') {
            const packages = await this.orm.searchRead('stock.package', [['name', '=', barcode]], ['id', 'name']);
            if (packages.length > 0) {
                const pkg = packages[0];
                let found = false;
                for (let line of this.state.lines) {
                    const isSourcePackage = line.package_id && (line.package_id.id === pkg.id || line.package_id[0] === pkg.id);
                    const isDestPackage = line.result_package_id && (line.result_package_id.id === pkg.id || line.result_package_id[0] === pkg.id);
                    if (isSourcePackage || isDestPackage) {
                        line.quantity = line.product_uom_qty > 0 ? line.product_uom_qty : (line.quantity > 0 ? line.quantity : 1);
                        line.picked = true;
                        found = true;
                    }
                }
                if (found) {
                    this.notification.add(`Package ${pkg.name} scanned successfully!`, { type: "success" });
                    this.syncWithBackend();
                } else {
                    this.notification.add(`Package ${pkg.name} found, but no items in this transfer belong to it.`, { type: "warning" });
                }
                return;
            }
        }

        // 1.5 Handle Lots directly scanned
        if (['lot', 'unknown', 'product'].includes(parsed.type)) {
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
        if (['location', 'unknown', 'product'].includes(parsed.type)) {
            const locations = await this.orm.searchRead(
                'stock.location',
                ['|', ['barcode', '=', barcode], ['complete_name', 'ilike', barcode]],
                ['id', 'display_name']
            );

            if (locations.length > 0) {
                if (this.state.picking) {
                    this.state.picking.location_id = [locations[0].id, locations[0].display_name];
                }
                this.notification.add(`Location set to: ${locations[0].display_name}`, { type: 'success' });

                if (this.props.pickingId === 'inventory') {
                    await this.loadInventoryState(locations[0].id);
                }
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

    /** Colour of the transfer a batch line belongs to (false outside batches / no transfer). */
    pickingColor(line) {
        if (!this.props.batchId || !line.picking_id || !this.pickingColors) {
            return false;
        }
        const pickingId = typeof line.picking_id === 'object' ? (line.picking_id.id || line.picking_id[0]) : line.picking_id;
        return this.pickingColors[pickingId] || false;
    }

    getLineUomName(line) {
        let uom = line.uom_id || line.product_uom_id;
        if (uom) {
            return uom.display_name || uom.name || (Array.isArray(uom) ? uom[1] : 'Units');
        }
        return 'Units';
    }

    incrementQuantity(line, qtyToAdd) {
        if (!line.quantity) line.quantity = 0;

        if (this.props.pickingId === 'inventory' && !line.inventory_quantity_set) {
            line.quantity = 0;
            line.inventory_quantity_set = true;
        }

        let oldQty = line.quantity;
        let newQty = oldQty + qtyToAdd;
        if (newQty < 0) newQty = 0;

        if (line.is_byproduct) {
            // registered by hand: kept as is when producing more (Odoo: picked moves are never recomputed)
            line.picked = true;
        }
        if (this.props.pickingId !== 'inventory' && !line.is_byproduct && line.product_uom_qty > 0 && newQty > line.product_uom_qty) {
            newQty = line.product_uom_qty;
            if (newQty !== oldQty) {
                this.notification.add(`Maximum quantity reached for ${line.product_id ? (line.product_id.display_name || line.product_id.name || 'product') : 'product'}.`, { type: "warning" });
            }
        }

        line.quantity = newQty;
        if (this.props.pickingId === 'inventory') {
            line.inventory_quantity_set = true;
        }

        // Auto-consume components (and produce by-products) when incrementing the finished product in an MO
        if (this.isMO && line.is_finished_product && line.product_uom_qty > 0) {
            let ratio = newQty / line.product_uom_qty;
            for (let comp of [...this.componentLines, ...this.byproductLines.filter((l) => !l.picked)]) {
                if (comp.product_uom_qty > 0) {
                    let expectedQty = comp.product_uom_qty * ratio;
                    comp.quantity = parseFloat(expectedQty.toFixed(4));
                }
            }
        }
    }

    /** Register By-Products mode: add qty to the product's by-product line (new line if none). */
    registerByProduct(product, barcode, qty) {
        const productId = product.id;
        const line = this.byproductLines.find((l) => l.product_id && (l.product_id.id === productId || l.product_id[0] === productId));
        if (line) {
            line.quantity = parseFloat(((line.quantity || 0) + qty).toFixed(4));
            line.picked = true;
            return line;
        }
        return this.newByProductLine(product, barcode, qty);
    }

    newByProductLine(product, barcode, qty) {
        const productId = product.id;
        const uom = Array.isArray(product.uom_id) ? { id: product.uom_id[0], display_name: product.uom_id[1] } : (product.uom_id || null);
        const newLine = {
            id: 'virtual_' + Math.random(),
            product_id: { id: productId, display_name: product.display_name, barcode: barcode || product.barcode, tracking: product.tracking },
            quantity: qty,
            product_uom_qty: 0,
            uom_id: uom,
            // by-products come from the production location, like the finished product
            location_id: (this.producingLines[0] && this.producingLines[0].location_id) || null,
            location_dest_id: this.state.picking && this.state.picking.location_dest_id ? { id: this.state.picking.location_dest_id[0], display_name: this.state.picking.location_dest_id[1] } : null,
            is_finished_product: false,
            is_byproduct: true,
            dummy: true,
            picked: true,
        };
        this.state.lines.push(newLine);
        return newLine;
    }

    addQuantity(line, qty) {
        this.incrementQuantity(line, qty);
    }

    removeLine(lineId) {
        this.state.lines = this.state.lines.filter(l => l.id !== lineId);
    }

    toggleSettings() {
        if (this.isNewMO) {
            this.notification.add("Scan or add the product to produce first.", { type: "warning" });
            return;
        }
        this.state.showSettings = !this.state.showSettings;
        if (this.state.showSettings) this.state.showAddProduct = false;
    }

    async toggleCountEntire() {
        this.state.countEntire = !this.state.countEntire;
        if (this.props.pickingId === 'inventory' && this.state.picking && this.state.picking.location_id) {
            await this.loadInventoryState(this.state.picking.location_id[0]);
            this.notification.add(`Refreshed inventory for location.`, { type: 'success' });
        }
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
                        is_byproduct: line.is_byproduct || undefined,
                        move_id: line.is_byproduct ? (line.move_id || false) : undefined,
                        picked: line.is_byproduct ? Boolean(line.picked) : undefined,
                        product_id: line.product_id.id,
                        inventory_quantity: line.quantity,
                        location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : null,
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    });
                } else if (line.inventory_quantity_set) {
                    commands.push({
                        action: 'write',
                        quant_id: line.id,
                        inventory_quantity: line.quantity,
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    });
                }
            }

            await this.orm.call(
                'stock.quant',
                'process_barcode_inventory_sync',
                [commands, applyNow]
            );
            this.notification.add(applyNow ? "Inventory applied successfully!" : "Inventory saved for review!", { type: "success" });
            this.props.onBack(true);
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

    async openQualityChecksBackend() {
        if (!this.state.picking) return;
        if (this.state.picking.quality_check_todo) {
            // checks to do: same flow as the QUALITY CHECKS button (saves the scanned
            // quantities, then the check wizard), so nothing scanned is lost
            this.state.showSettings = false;
            return this.openQualityChecks();
        }

        const pickingId = parseInt(this.props.pickingId);
        // open the checks in a pop-up: the scan screen (and its quantities) stays as it is
        const onClose = () => this.refreshPickingHeader();

        // First try the native Odoo quality check picking action
        try {
            let action = await this.orm.call(
                this.isMO ? 'mrp.production' : 'stock.picking',
                this.isMO ? 'action_open_quality_check_mrp' : 'action_open_quality_check_picking',
                [[pickingId]]
            );
            if (action) {
                // Force form view, not list view - like Odoo Online
                action.views = [[false, 'form']];
                action.view_mode = 'form';
                action.target = 'new';
                this.actionService.doAction(action, { onClose });
                return;
            }
        } catch (e) {
            console.warn("Standard quality action not found, using fallback", e);
        }

        // Fallback: Find existing quality checks for this picking, open form directly
        const domain = this.isMO
            ? [['production_id', '=', pickingId]]
            : [['picking_id', '=', pickingId]];
        const context = this.isMO
            ? { default_production_id: pickingId }
            : { default_picking_id: pickingId };

        // Try to find an existing quality check record to open
        const existingChecks = await this.orm.searchRead(
            'quality.check',
            domain,
            ['id'],
            { limit: 1 }
        );

        const actionDef = {
            type: 'ir.actions.act_window',
            name: 'Quality Check',
            res_model: 'quality.check',
            view_mode: 'form',
            views: [[false, 'form']],
            context: context,
            target: 'new',
        };

        if (existingChecks.length > 0) {
            // Open the first existing check directly in form view
            actionDef.res_id = existingChecks[0].id;
        }
        // else: opens a new empty form (user can fill it in)

        this.actionService.doAction(actionDef, { onClose });
    }

    /** After the quality checks of a transfer are done (passed or failed), like Odoo Online:
     *  lines not counted yet get their full quantity (0 / 500 -> 500 / 500) so the transfer can
     *  be validated; quantities entered by hand (e.g. 300 / 500) are kept. */
    fillQuantitiesAfterQualityChecks() {
        const picking = this.state.picking;
        if (!picking || picking.quality_check_todo || this.isMO || this.props.batchId || this.props.pickingId === 'inventory') {
            return;
        }
        if (['done', 'cancel'].includes(picking.state)) {
            return;
        }
        for (const line of this.state.lines || []) {
            if (!line.quantity && line.product_uom_qty > 0) {
                line.quantity = line.product_uom_qty;
                line.picked = true;
            }
        }
    }

    /** Refresh the transfer's header data (e.g. quality checks still to do) without touching
     *  the scanned lines. */
    async refreshPickingHeader() {
        if (!this.state.picking || this.props.batchId || this.isNewMO || this.props.pickingId === 'inventory') {
            return;
        }
        try {
            const model = this.isMO ? 'mrp.production' : 'stock.picking';
            const state = await this.orm.call(model, 'get_barcode_view_state', [[parseInt(this.props.pickingId)]]);
            const { move_line_ids, nomenclature, ...header } = state;
            Object.assign(this.state.picking, header);
        } catch (e) {
            console.warn("Could not refresh the transfer", e);
        }
    }

    async openQualityChecks() {
        if (!this.state.picking) return;

        try {
            // First sync current scanned quantities to backend
            const commands = [];
            for (let line of this.state.lines) {
                if (String(line.id).startsWith('virtual_')) {
                    commands.push({
                        action: 'create',
                        is_byproduct: line.is_byproduct || undefined,
                        move_id: line.is_byproduct ? (line.move_id || false) : undefined,
                        picked: line.is_byproduct ? Boolean(line.picked) : undefined,
                        product_id: line.product_id.id,
                        quantity: line.quantity,
                        location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : (this.state.picking.location_id ? this.state.picking.location_id[0] : null),
                        location_dest_id: line.location_dest_id ? (Array.isArray(line.location_dest_id) ? line.location_dest_id[0] : line.location_dest_id.id) : (this.state.picking.location_dest_id ? this.state.picking.location_dest_id[0] : null),
                        product_uom_id: this.lineUomId(line),
                        owner_id: this.lineOwnerId(line),
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    });
                } else {
                    commands.push({
                        action: 'write',
                        line_id: line.id,
                        quantity: line.quantity,
                        is_byproduct: line.is_byproduct || undefined,
                        picked: line.is_byproduct ? Boolean(line.picked) : undefined,
                        product_uom_id: this.lineUomId(line),
                        owner_id: this.lineOwnerId(line),
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    });
                }
            }

            let model = this.isMO ? 'mrp.production' : 'stock.picking';
            await this.orm.call(
                model,
                'process_barcode_sync',
                [[parseInt(this.props.pickingId)], commands]
            );

            let action = await this.orm.call(
                this.isMO ? 'mrp.production' : 'stock.picking',
                'action_open_quality_check_wizard',
                [[parseInt(this.props.pickingId)]]
            );
            if (action) {
                if (action.type === 'ir.actions.act_window') {
                    if (!action.views) {
                        if (action.view_mode) {
                            action.views = action.view_mode.split(',').map(mode => [false, mode.trim()]);
                        } else {
                            action.views = [[false, 'form']];
                        }
                    }
                    if (!action.domain) action.domain = [];
                    if (!action.context) action.context = {};
                    action.context.active_model = this.isMO ? 'mrp.production' : 'stock.picking';
                    action.context.active_id = parseInt(this.props.pickingId);
                    action.context.active_ids = [parseInt(this.props.pickingId)];
                }

                this.actionService.doAction(action, {
                    onClose: async () => {
                        await this.loadPickingState(); // Refresh after quality checks
                        this.fillQuantitiesAfterQualityChecks();
                    }
                });
            } else {
                this.notification.add("No quality checks available.", { type: "warning" });
            }
        } catch (e) {
            console.error("Quality Check Error:", e);
            let errorMsg = "Could not open Quality Checks wizard.";
            if (e.data && e.data.message) {
                errorMsg = e.data.message;
            } else if (e.message) {
                errorMsg = e.message;
            }
            this.notification.add(errorMsg, { type: "danger" });
        }
    }

    async saveAndGoBack() {
        if (this.props.pickingId === 'inventory') {
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
                            package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                            result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                            destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                        });
                    } else {
                        commands.push({
                            action: 'write',
                            quant_id: line.id,
                            inventory_quantity: line.quantity,
                            lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                            lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                            package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                            result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                            destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                        });
                    }
                }

                if (commands.length > 0) {
                    await this.orm.call(
                        'stock.quant',
                        'process_barcode_inventory_sync',
                        [commands, false]
                    );
                }
            } catch (e) {
                console.error("Auto-save failed on back:", e);
            }
        }

        if (this.props.onBack) {
            this.props.onBack();
        }
    }

    async onApplyLot(lotName) {
        if (!lotName || !this.state.pendingLotProduct) return;
        const product = this.state.pendingLotProduct;

        // Register By-Products mode: the lot / serial goes on a by-product line
        if (this.isMO && this.state.byProductMode) {
            const sameProduct = (l) => l.product_id && (l.product_id.id === product.id || l.product_id[0] === product.id);
            const lotOf = (l) => (Array.isArray(l.lot_id) ? l.lot_id[1] : (l.lot_id && (l.lot_id.name || l.lot_id))) || l.lot_name || null;
            let line = product.tracking === 'serial' ? null : this.byproductLines.find((l) => sameProduct(l) && lotOf(l) === lotName);
            if (!line) {
                // an empty by-product line (no lot, nothing registered yet) takes the lot
                line = this.byproductLines.find((l) => sameProduct(l) && !lotOf(l) && !(l.quantity > 0));
                if (line) {
                    line.lot_id = [null, lotName];
                }
            }
            if (line) {
                line.quantity = parseFloat(((line.quantity || 0) + 1).toFixed(4));
                line.picked = true;
            } else {
                const newLine = this.newByProductLine(product, product.barcode, 1);
                newLine.lot_id = [null, lotName];
            }
            this.state.showLotDialog = false;
            this.state.pendingLotProduct = null;
            return;
        }

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
                this.incrementQuantity(line, 1);
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
            // Odoo 20 replaced `report.stock.report_reception` with
            // `stock.allocation.report`, which returns `product_lines`, each with
            // the incoming move ids (`move_ids`) and the outgoing `needs`.
            // Map it back to the structure this screen renders.
            const data = await this.orm.call(
                'stock.allocation.report',
                'get_report_data',
                [{ context: { active_model: 'stock.picking', active_ids: [this.state.picking.id] } }]
            );

            // Group by Product (only products that have allocation needs)
            const productsMap = {};
            for (const productLine of data.product_lines || []) {
                if (!productLine.needs || !productLine.needs.length) {
                    continue;
                }
                const prod = {
                    product: { id: productLine.id, display_name: productLine.display_name },
                    totalAvailable: 0,
                    allocations: [],
                };
                for (const need of productLine.needs) {
                    // Destination name: "<picking>: <partner>", like the old report.
                    let destName = need.picking ? need.picking.display_name : (need.source ? need.source.display_name : '');
                    if (need.picking && need.partner) {
                        destName += `: ${need.partner.display_name}`;
                    }
                    prod.allocations.push({
                        index: need.id,
                        quantity: need.quantity,
                        is_assigned: need.is_reserved,
                        move_out_id: need.id,
                        move_ins: productLine.move_ids,
                        dest_name: destName,
                    });
                    prod.totalAvailable += need.quantity;
                }
                productsMap[productLine.id] = prod;
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
            // Odoo 20: action_unassign(src_move_ids, out_move_ids, quantity)
            await this.orm.call(
                'stock.allocation.report',
                'action_unassign',
                [alloc.move_ins, [alloc.move_out_id], alloc.quantity]
            );
        } else {
            // Odoo 20: action_assign(src_move_ids, out_move_ids, quantity)
            await this.orm.call(
                'stock.allocation.report',
                'action_assign',
                [alloc.move_ins, [alloc.move_out_id], alloc.quantity]
            );
        }
        await this.openAllocation(); // Refresh data
    }

    async assignAll() {
        if (!this.state.processedAllocations) return;

        // Odoo 20: action_assign_all([[src_move_ids, [[out_move_ids, quantity], ...]], ...])
        const allocationList = [];
        for (const prod of this.state.processedAllocations) {
            const toAssign = [];
            let srcMoveIds = null;
            for (const alloc of prod.allocations) {
                if (!alloc.is_assigned && alloc.move_out_id) {
                    toAssign.push([[alloc.move_out_id], alloc.quantity]);
                    srcMoveIds = alloc.move_ins;
                }
            }
            if (toAssign.length) {
                allocationList.push([srcMoveIds, toAssign]);
            }
        }

        if (allocationList.length > 0) {
            await this.orm.call(
                'stock.allocation.report',
                'action_assign_all',
                [allocationList]
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
            this.state.addProductOwner = null;
            this.state.addProductOwnerSearchStr = '';
            this.state.addProductOwnerSearchResults = [];
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
            this.state.addProductSourcePackage = null;
            this.state.addProductSourcePackageSearchStr = '';
            this.state.addProductSourcePackageSearchResults = [];
            this.state.addProductDestPackage = null;
            this.state.addProductDestPackageSearchStr = '';
            this.state.addProductDestPackageSearchResults = [];
            this.state.addProductDestContainerPackage = null;
            this.state.addProductDestContainerPackageSearchStr = '';
            this.state.addProductDestContainerPackageSearchResults = [];
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

        let uom = line.uom_id || line.product_uom_id;
        if (uom) {
            let uomId = uom.id || (Array.isArray(uom) ? uom[0] : null);
            let uomName = uom.display_name || uom.name || (Array.isArray(uom) ? uom[1] : '');
            this.state.addProductUom = uomId ? [uomId, uomName] : null;
            this.state.addProductUomSearchStr = uomName;
        } else {
            this.state.addProductUom = null;
            this.state.addProductUomSearchStr = '';
        }

        if (line.location_dest_id) {
            this.state.addProductDestLoc = [line.location_dest_id.id, line.location_dest_id.display_name];
            this.state.addProductDestLocSearchStr = line.location_dest_id.display_name;
        } else {
            this.state.addProductDestLoc = null;
            this.state.addProductDestLocSearchStr = '';
        }

        const owner = line.owner_id;
        this.state.addProductOwner = owner ? (Array.isArray(owner) ? owner : [owner.id, owner.display_name || owner.name]) : null;
        this.state.addProductOwnerSearchStr = this.state.addProductOwner ? this.state.addProductOwner[1] : '';
        this.state.addProductOwnerSearchResults = [];
        this.state.addProductSourcePackage = line.source_package || (line.package_id ? (Array.isArray(line.package_id) ? line.package_id : [line.package_id.id, line.package_id.name]) : null);
        this.state.addProductSourcePackageSearchStr = this.state.addProductSourcePackage ? (Array.isArray(this.state.addProductSourcePackage) ? this.state.addProductSourcePackage[1] : this.state.addProductSourcePackage) : '';
        this.state.addProductSourcePackageSearchResults = [];

        this.state.addProductDestPackage = line.dest_package || (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id : [line.result_package_id.id, line.result_package_id.name]) : null);
        this.state.addProductDestPackageSearchStr = this.state.addProductDestPackage ? (Array.isArray(this.state.addProductDestPackage) ? this.state.addProductDestPackage[1] : this.state.addProductDestPackage) : '';
        this.state.addProductDestPackageSearchResults = [];

        this.state.addProductDestContainerPackage = line.dest_container_package || (line.destination_container_package ? (Array.isArray(line.destination_container_package) ? line.destination_container_package : [line.destination_container_package.id, line.destination_container_package.name]) : null);
        this.state.addProductDestContainerPackageSearchStr = this.state.addProductDestContainerPackage ? (Array.isArray(this.state.addProductDestContainerPackage) ? this.state.addProductDestContainerPackage[1] : this.state.addProductDestContainerPackage) : '';
        this.state.addProductDestContainerPackageSearchResults = [];

        this.state.addProductUomSearchResults = [];
        this.state.addProductDestLocSearchResults = [];
    }

    openProductPage() {
        if (this.state.addProductSelected) {
            this.actionService.doAction({
                type: 'ir.actions.act_window',
                res_model: 'product.product',
                res_id: this.state.addProductSelected.id,
                views: [[false, 'form']],
                target: 'new',
            });
        }
    }

    async printReport(actionXmlId) {
        if (!this.state.picking || !this.state.picking.id || this.state.picking.id === 'inventory') {
            this.notification.add("Cannot print from the current view.", { type: "danger" });
            return;
        }
        await this.actionService.doAction(actionXmlId, {
            additionalContext: {
                active_ids: [this.state.picking.id],
                active_id: this.state.picking.id,
                active_model: 'stock.picking',
            },
        });
    }

    async printBarcodes() {
        if (!this.state.picking || !this.state.picking.id || this.state.picking.id === 'inventory') {
            this.notification.add("Cannot print from the current view.", { type: "danger" });
            return;
        }

        try {
            const action = await this.orm.call(
                'stock.picking',
                'action_open_label_layout',
                [[this.state.picking.id]]
            );
            if (action) {
                await this.actionService.doAction(action);
            }
        } catch (e) {
            console.error(e);
            this.notification.add("Failed to generate product barcodes.", { type: "danger" });
        }
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

    async onDestLocSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductDestLocSearchStr = val;
        this.state.showDestLocDropdown = true;

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
        this.state.showDestLocDropdown = true;
        await this.onDestLocSearchInput({ target: { value: this.state.addProductDestLocSearchStr || '' } });
    }

    /** Unit id of a line: `uom_id` (server/scanned lines) or `product_uom_id` (lines from the edit panel). */
    lineUomId(line) {
        const uom = line.uom_id || line.product_uom_id;
        return uom ? (Array.isArray(uom) ? uom[0] : uom.id) : null;
    }

    /** Units allowed for the selected product (Odoo 20: the move line's allowed_uom_ids). */
    async getAllowedUoms() {
        const productId = this.state.addProductSelected && this.state.addProductSelected.id;
        if (!productId) {
            return [];
        }
        this.allowedUomsCache = this.allowedUomsCache || {};
        if (!this.allowedUomsCache[productId]) {
            this.allowedUomsCache[productId] = await this.orm.call('stock.move.line', 'barcode_get_allowed_uoms', [productId]);
        }
        return this.allowedUomsCache[productId];
    }

    async onUomSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductUomSearchStr = val;
        this.state.showUomDropdown = true;
        const term = (val || '').trim().toLowerCase();
        const allowed = await this.getAllowedUoms();
        this.state.addProductUomSearchResults = allowed.filter((uom) => !term || uom.name.toLowerCase().includes(term));
    }

    async onUomFocus() {
        // show every allowed unit on focus, like a many2one dropdown
        this.state.showUomDropdown = true;
        this.state.addProductUomSearchResults = await this.getAllowedUoms();
    }

    selectUom(uom) {
        this.state.addProductUom = [uom.id, uom.name];
        this.state.addProductUomSearchStr = uom.name;
        this.state.addProductUomSearchResults = [];
        this.state.showUomDropdown = false;
    }

    selectDestLoc(loc) {
        this.state.addProductDestLoc = [loc.id, loc.display_name];
        this.state.addProductDestLocSearchStr = loc.display_name;
        this.state.addProductDestLocSearchResults = [];
        this.state.showDestLocDropdown = false;
    }

    async onSourcePackageSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductSourcePackageSearchStr = val;
        this.state.addProductSourcePackage = val; // Also save as text in case it's a new package
        this.state.showSourcePackageDropdown = true;
        let domain = val ? [['name', 'ilike', val]] : [];
        const results = await this.orm.searchRead('stock.package', domain, ['id', 'name'], { limit: 10 });
        this.state.addProductSourcePackageSearchResults = results;
    }

    async onSourcePackageFocus() {
        this.state.showSourcePackageDropdown = true;
        await this.onSourcePackageSearchInput({ target: { value: this.state.addProductSourcePackageSearchStr || '' } });
    }

    async onOwnerSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductOwnerSearchStr = val;
        if (!val) {
            this.state.addProductOwner = null;
        }
        this.state.showOwnerDropdown = true;
        const domain = val ? [['display_name', 'ilike', val]] : [];
        this.state.addProductOwnerSearchResults = await this.orm.searchRead('res.partner', domain, ['id', 'display_name'], { limit: 8 });
    }

    async onOwnerFocus() {
        await this.onOwnerSearchInput({ target: { value: this.state.addProductOwnerSearchStr || '' } });
    }

    selectOwner(partner) {
        this.state.addProductOwner = [partner.id, partner.display_name];
        this.state.addProductOwnerSearchStr = partner.display_name;
        this.state.addProductOwnerSearchResults = [];
        this.state.showOwnerDropdown = false;
    }

    /** Owner of a line as an id (or undefined: nothing to send). */
    lineOwnerId(line) {
        const owner = line.owner_id;
        if (!owner) {
            return undefined;
        }
        return Array.isArray(owner) ? owner[0] : owner.id;
    }

    selectSourcePackage(pkg) {
        this.state.addProductSourcePackage = [pkg.id, pkg.name];
        this.state.addProductSourcePackageSearchStr = pkg.name;
        this.state.addProductSourcePackageSearchResults = [];
        this.state.showSourcePackageDropdown = false;
    }

    async onDestPackageSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductDestPackageSearchStr = val;
        this.state.addProductDestPackage = val;
        this.state.showDestPackageDropdown = true;
        let domain = val ? [['name', 'ilike', val]] : [];
        const results = await this.orm.searchRead('stock.package', domain, ['id', 'name'], { limit: 10 });
        this.state.addProductDestPackageSearchResults = results;
    }

    async onDestPackageFocus() {
        this.state.showDestPackageDropdown = true;
        await this.onDestPackageSearchInput({ target: { value: this.state.addProductDestPackageSearchStr || '' } });
    }

    selectDestPackage(pkg) {
        this.state.addProductDestPackage = [pkg.id, pkg.name];
        this.state.addProductDestPackageSearchStr = pkg.name;
        this.state.addProductDestPackageSearchResults = [];
        this.state.showDestPackageDropdown = false;
    }

    async onDestContainerSearchInput(ev) {
        const val = ev.target.value;
        this.state.addProductDestContainerPackageSearchStr = val;
        this.state.addProductDestContainerPackage = val;
        this.state.showDestContainerDropdown = true;
        let domain = val ? [['name', 'ilike', val]] : [];
        const results = await this.orm.searchRead('stock.package', domain, ['id', 'name'], { limit: 10 });
        this.state.addProductDestContainerPackageSearchResults = results;
    }

    async onDestContainerFocus() {
        this.state.showDestContainerDropdown = true;
        await this.onDestContainerSearchInput({ target: { value: this.state.addProductDestContainerPackageSearchStr || '' } });
    }

    selectDestContainer(pkg) {
        this.state.addProductDestContainerPackage = [pkg.id, pkg.name];
        this.state.addProductDestContainerPackageSearchStr = pkg.name;
        this.state.addProductDestContainerPackageSearchResults = [];
        this.state.showDestContainerDropdown = false;
    }

    closeDropdowns() {
        this.state.addProductSearchResults = [];
        this.state.addProductOwnerSearchResults = [];
        this.state.showOwnerDropdown = false;
        this.state.addProductUomSearchResults = [];
        this.state.showUomDropdown = false;
        this.state.addProductDestLocSearchResults = [];
        this.state.showDestLocDropdown = false;
        this.state.addProductSourcePackageSearchResults = [];
        this.state.showSourcePackageDropdown = false;
        this.state.addProductDestPackageSearchResults = [];
        this.state.showDestPackageDropdown = false;
        this.state.addProductDestContainerPackageSearchResults = [];
        this.state.showDestContainerDropdown = false;
    }

    async openSearchMore(type) {
        this.closeDropdowns();
        let resModel, title, callback, domain = [];
        if (type === 'product') {
            resModel = 'product.product';
            title = 'Search: Product';
            callback = async (resId) => {
                const prods = await this.orm.read('product.product', [resId], ['id', 'display_name', 'barcode', 'default_code', 'uom_id', 'tracking']);
                if (prods.length > 0) this.selectProduct(prods[0]);
            };
        } else if (type === 'owner') {
            resModel = 'res.partner';
            title = 'Search: Owner';
            callback = async (resId) => {
                const partners = await this.orm.read('res.partner', [resId], ['id', 'display_name']);
                if (partners.length > 0) this.selectOwner(partners[0]);
            };
        } else if (type === 'uom') {
            resModel = 'uom.uom';
            title = 'Search: Unit of Measure';
            domain = [['id', 'in', (await this.getAllowedUoms()).map((uom) => uom.id)]];
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
        } else if (type === 'source_package') {
            resModel = 'stock.package';
            title = 'Search: Source Package';
            callback = async (resId) => {
                const pkgs = await this.orm.read('stock.package', [resId], ['id', 'name']);
                if (pkgs.length > 0) this.selectSourcePackage(pkgs[0]);
            };
        } else if (type === 'dest_package') {
            resModel = 'stock.package';
            title = 'Search: Destination Package';
            callback = async (resId) => {
                const pkgs = await this.orm.read('stock.package', [resId], ['id', 'name']);
                if (pkgs.length > 0) this.selectDestPackage(pkgs[0]);
            };
        } else if (type === 'dest_container') {
            resModel = 'stock.package';
            title = 'Search: Destination Container Package';
            callback = async (resId) => {
                const pkgs = await this.orm.read('stock.package', [resId], ['id', 'name']);
                if (pkgs.length > 0) this.selectDestContainer(pkgs[0]);
            };
        }

        this.dialog.add(SelectCreateDialog, {
            resModel: resModel,
            title: title,
            domain: domain,
            multiSelect: false,
            onSelected: (resIds) => {
                if (resIds && resIds.length > 0) {
                    callback(resIds[0]);
                }
            },
        });
    }

    get dynamicAddButtonValue() {
        if (this.state.editingLineId) {
            const line = this.state.lines.find(l => l.id === this.state.editingLineId);
            if (line && line.product_uom_qty > 0) {
                const remaining = line.product_uom_qty - this.state.addProductQty;
                if (remaining > 0) {
                    return remaining;
                }
            }
        }
        return 1;
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
        if (this.isNewMO) {
            const selected = this.state.addProductSelected;
            this.state.showAddProduct = false;
            this.createProductionFor({
                id: selected.id,
                display_name: selected.display_name || selected.name || this.state.addProductSearchStr,
            }, this.state.addProductQty > 0 ? this.state.addProductQty : 1);
            return;
        }

        if (this.isInventoryForm ? this.state.addProductQty < 0 : this.state.addProductQty <= 0) {
            this.notification.add(this.isInventoryForm ? "The counted quantity cannot be negative." : "Quantity must be greater than 0.", { type: "danger" });
            return;
        }

        // Add or Edit line
        if (this.state.editingLineId) {
            let existingLine = this.state.lines.find(l => l.id === this.state.editingLineId);
            if (existingLine) {
                existingLine.product_id = { id: this.state.addProductSelected.id, display_name: this.state.addProductSelected.display_name || this.state.addProductSelected.name || this.state.addProductSearchStr, tracking: this.state.addProductSelected.tracking };

                let newQty = this.state.addProductQty;
                if (existingLine.is_byproduct) {
                    existingLine.picked = true;  // edited by hand: kept when producing more
                }
                if (this.props.pickingId !== 'inventory' && !existingLine.is_byproduct && existingLine.product_uom_qty > 0 && newQty > existingLine.product_uom_qty) {
                    newQty = existingLine.product_uom_qty;
                    this.notification.add("Maximum quantity reached.", { type: "warning" });
                }
                existingLine.quantity = newQty;
                if (this.props.pickingId === 'inventory') {
                    existingLine.inventory_quantity_set = true;
                }

                // Auto-consume components (and produce by-products) if we are editing the finished product in an MO
                if (this.isMO && existingLine.is_finished_product && existingLine.product_uom_qty > 0) {
                    let ratio = newQty / existingLine.product_uom_qty;
                    for (let comp of [...this.componentLines, ...this.byproductLines.filter((l) => !l.picked)]) {
                        if (comp.product_uom_qty > 0) {
                            let expectedQty = comp.product_uom_qty * ratio;
                            comp.quantity = parseFloat(expectedQty.toFixed(4));
                        }
                    }
                }

                existingLine.location_dest_id = this.state.addProductDestLoc ? { id: this.state.addProductDestLoc[0], display_name: this.state.addProductDestLoc[1] } : null;
                if (this.addFormFields.owner) {
                    existingLine.owner_id = this.state.addProductOwner;
                }
                existingLine.source_package = this.state.addProductSourcePackage;
                existingLine.dest_package = this.state.addProductDestPackage;
                existingLine.dest_container_package = this.state.addProductDestContainerPackage;

                let updatedUom = this.state.addProductUom ? { id: this.state.addProductUom[0], display_name: this.state.addProductUom[1] } : null;
                existingLine.product_uom_id = updatedUom;
                existingLine.uom_id = updatedUom;

                if (this.state.addProductLotName) {
                    existingLine.lot_id = [null, this.state.addProductLotName];
                } else {
                    existingLine.lot_id = null;
                }
            }
            this.state.editingLineId = null;
            this.notification.add("Line updated.", { type: "success" });
        } else if (this.isMO && this.state.byProductMode) {
            const selected = this.state.addProductSelected;
            const line = this.registerByProduct({
                id: selected.id,
                display_name: selected.display_name || selected.name || this.state.addProductSearchStr,
                tracking: selected.tracking,
                uom_id: selected.uom_id,
            }, null, this.state.addProductQty);
            if (this.state.addProductUom) {
                line.uom_id = { id: this.state.addProductUom[0], display_name: this.state.addProductUom[1] };
                line.product_uom_id = line.uom_id;
            }
            if (this.state.addProductLotName) {
                line.lot_id = [null, this.state.addProductLotName];
            }
            this.notification.add("By-product registered.", { type: "success" });
        } else {
            let existingLine = this.state.lines.find(l =>
                (l.product_id[0] === this.state.addProductSelected.id || l.product_id.id === this.state.addProductSelected.id) &&
                (!this.state.addProductLotName || (l.lot_id && (l.lot_id[1] === this.state.addProductLotName || l.lot_id === this.state.addProductLotName)))
            );

            if (existingLine && this.state.addProductSelected.tracking !== 'serial') {
                this.incrementQuantity(existingLine, this.state.addProductQty);
                if (this.props.pickingId !== 'inventory' && existingLine.product_uom_qty > 0 && existingLine.quantity > existingLine.product_uom_qty) {
                    existingLine.quantity = existingLine.product_uom_qty;
                    this.notification.add("Maximum quantity reached.", { type: "warning" });
                }
                if (this.props.pickingId === 'inventory') {
                    existingLine.inventory_quantity_set = true;
                }
                this.notification.add("Quantity updated.", { type: "success" });
            } else {
                this.state.lines.unshift({
                    id: 'virtual_' + Math.random(),
                    product_id: { id: this.state.addProductSelected.id, display_name: this.state.addProductSelected.display_name || this.state.addProductSelected.name, tracking: this.state.addProductSelected.tracking },
                    quantity: this.state.addProductQty,
                    inventory_quantity_set: this.props.pickingId === 'inventory' ? true : undefined,
                    quantity_product_uom: 0,
                    location_id: this.state.picking ? this.state.picking.location_id : null,
                    location_dest_id: this.state.addProductDestLoc ? { id: this.state.addProductDestLoc[0], display_name: this.state.addProductDestLoc[1] } : null,
                    product_uom_id: this.state.addProductUom ? { id: this.state.addProductUom[0], display_name: this.state.addProductUom[1] } : null,
                    lot_id: this.state.addProductLotName ? [null, this.state.addProductLotName] : null,
                    source_package: this.state.addProductSourcePackage,
                    dest_package: this.state.addProductDestPackage,
                    dest_container_package: this.state.addProductDestContainerPackage,
                    owner_id: this.addFormFields.owner ? this.state.addProductOwner : null
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
        if (!this.state.showCamera || !this.videoRef() || this.videoRef().readyState !== 4) return;

        // Native BarcodeDetector (Android Chrome)
        if (window.BarcodeDetector) {
            try {
                if (!this.detector) this.detector = new BarcodeDetector();
                const barcodes = await this.detector.detect(this.videoRef());
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
                this.canvas.width = this.videoRef().videoWidth;
                this.canvas.height = this.videoRef().videoHeight;
                this.ctx.drawImage(this.videoRef(), 0, 0, this.canvas.width, this.canvas.height);

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

    async syncWithBackend() {
        if (!this.state.picking || this.props.pickingId === 'inventory' || this.isNewMO) return;
        try {
            const commands = [];
            for (let line of this.state.lines) {
                const pickingId = line.picking_id ? (typeof line.picking_id === 'object' ? line.picking_id.id : line.picking_id) : null;
                if (String(line.id).startsWith('virtual_')) {
                    if (this.isMO) {
                        // MO: new lines are created once, on Produce (creating them here too would
                        // count them twice: extra consumption + consumption warning)
                        continue;
                    }
                    const cmd = {
                        action: 'create',
                        product_id: line.product_id.id,
                        quantity: line.quantity,
                        location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : (this.state.picking.location_id ? this.state.picking.location_id[0] : null),
                        location_dest_id: line.location_dest_id ? (Array.isArray(line.location_dest_id) ? line.location_dest_id[0] : line.location_dest_id.id) : (this.state.picking.location_dest_id ? this.state.picking.location_dest_id[0] : null),
                        product_uom_id: this.lineUomId(line),
                        owner_id: this.lineOwnerId(line),
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    };
                    if (line.is_byproduct) {
                        cmd.is_byproduct = true;
                        cmd.move_id = line.move_id || false;
                        cmd.picked = Boolean(line.picked);
                    }
                    if (this.props.batchId && pickingId) cmd.picking_id = pickingId;
                    commands.push(cmd);
                } else {
                    const cmd = {
                        action: 'write',
                        line_id: line.id,
                        quantity: line.quantity,
                        is_byproduct: line.is_byproduct || undefined,
                        picked: line.is_byproduct ? Boolean(line.picked) : undefined,
                        product_uom_id: this.lineUomId(line),
                        owner_id: this.lineOwnerId(line),
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    };
                    if (this.props.batchId && pickingId) cmd.picking_id = pickingId;
                    commands.push(cmd);
                }
            }

            if (this.props.batchId) {
                // Batch mode: route to batch process_barcode_sync which dispatches per picking
                await this.orm.call('stock.picking.batch', 'process_barcode_sync', [[parseInt(this.props.batchId)], commands]);
            } else {
                // a manufacturing order syncs on the MO (not on a transfer with the same id)
                const syncModel = this.isMO ? 'mrp.production' : 'stock.picking';
                await this.orm.call(syncModel, 'process_barcode_sync', [[parseInt(this.props.pickingId)], commands]);
            }
        } catch (e) {
            console.warn("Auto-sync failed", e);
        }
    }

    /** Add Product / Add Component form: which optional fields apply (Odoo Online). */
    get addFormFields() {
        if (this.isInventoryForm) {
            // Count Inventory (Odoo Online): product + counted quantity (+ lot, + package when
            // Packages is on); nothing is moved, so no destination, packing or unit fields
            return { destLocation: false, sourcePackage: this.state.canPutInPack, destPackages: false, owner: false, uom: false };
        }
        if (this.isNewMO || (this.isMO && this.state.byProductMode)) {
            // product to produce / by-product: product, quantity, unit (+ lot) only
            return { destLocation: false, sourcePackage: false, destPackages: false, owner: false, uom: true };
        }
        if (this.isMO) {
            // component: consumed from a location (and package, owner), never packed
            return { destLocation: false, sourcePackage: this.state.canPutInPack, destPackages: false, owner: this.state.canUseOwner, uom: true };
        }
        return { destLocation: true, sourcePackage: true, destPackages: true, owner: false, uom: true };
    }

    /** Add Product form opened from Count Inventory. */
    get isInventoryForm() {
        return this.props.pickingId === 'inventory';
    }

    async putInPack() {
        if (!this.state.picking || this.props.pickingId === 'inventory' || this.isNewMO) return;
        if (!this.state.canPutInPack) {
            this.notification.add("Packages are disabled. Enable them in Inventory > Configuration > Settings > Packages.", { type: "warning" });
            return;
        }

        try {
            await this.syncWithBackend();
            // batch screen: pack on the batch (all its transfers), MO: its finished product,
            // otherwise on the transfer
            const packModel = this.props.batchId ? 'stock.picking.batch' : (this.isMO ? 'mrp.production' : 'stock.picking');
            const packId = parseInt(this.props.batchId ? this.props.batchId : this.props.pickingId);
            const result = await this.orm.call(packModel, 'action_put_in_pack', [[packId]]);
            if (result && typeof result === 'object' && !Array.isArray(result) && result.type) {
                // Odoo asks for more (package type / destination wizard, label printing):
                // open it and refresh once it is closed.
                await this.actionService.doAction(result, {
                    onClose: async () => {
                        await this.loadPickingState();
                    },
                });
                return;
            }
            await this.loadPickingState();
            const packed = this.state.lines.some((line) => line.result_package_id);
            if (this.isMO && result === false) {
                this.notification.add("The finished product is already in a package.", { type: "warning" });
            } else if (packed) {
                this.notification.add("Products put in pack successfully!", { type: "success" });
            } else if (this.isMO) {
                this.notification.add("The finished product is already in a package.", { type: "warning" });
            } else {
                this.notification.add("Nothing to put in pack: scan the products first.", { type: "warning" });
            }
        } catch (e) {
            console.error("Put In Pack Error:", e);
            let errorMsg = "An error occurred while putting in pack.";
            if (e.data && e.data.message) {
                errorMsg = e.data.message;
            }
            this.notification.add(errorMsg, { type: "danger" });
        }
    }

    async validate() {
        if (this.isNewMO) {
            this.notification.add("Scan or add the product to produce first.", { type: "warning" });
            return;
        }
        if (this.props.pickingId === 'inventory') {
            this.state.showConfirmInventoryModal = true;
            return;
        }

        // ─── BATCH VALIDATE ──────────────────────────────────────────
        if (this.props.batchId) {
            try {
                // First sync all quantities
                await this.syncWithBackend();

                // Validate via standard Odoo batch action_done
                let result = await this.orm.call(
                    'stock.picking.batch',
                    'action_done',
                    [[parseInt(this.props.batchId)]]
                );

                if (typeof result === 'object' && result !== null && result.type && result.type.startsWith('ir.actions')) {
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

                        // Inject active record context
                        result.context.active_model = 'stock.picking.batch';
                        result.context.active_id = parseInt(this.props.batchId);
                        result.context.active_ids = [parseInt(this.props.batchId)];
                    }

                    this.actionService.doAction(result, {
                        onClose: async () => {
                            await this.loadPickingState();
                            if (this.state.picking && this.state.picking.state === 'done') {
                                this.notification.add("Batch validated successfully!", { type: "success" });
                                this.props.onBack(true);
                            }
                        }
                    });
                } else {
                    this.notification.add("Batch validated successfully!", { type: 'success' });
                    await this.loadPickingState();
                    if (this.state.picking && this.state.picking.state === 'done') {
                        this.props.onBack(true);
                    }
                }
            } catch (e) {
                console.error('Batch Validate Error:', e);
                let errorMsg = 'An error occurred while validating the batch.';
                if (e.data && e.data.message) {
                    errorMsg = e.data.message;
                } else if (e.message) {
                    errorMsg = e.message;
                }
                this.notification.add(errorMsg, { type: 'danger' });
            }
            return;
        }
        try {
            const commands = [];

            // Build the sync commands based on whether it is an inventory adjustment or a transfer
            for (let line of this.state.lines) {
                if (String(line.id).startsWith('virtual_')) {
                    commands.push({
                        action: 'create',
                        is_byproduct: line.is_byproduct || undefined,
                        move_id: line.is_byproduct ? (line.move_id || false) : undefined,
                        picked: line.is_byproduct ? Boolean(line.picked) : undefined,
                        product_id: line.product_id.id,
                        quantity: line.quantity,
                        location_id: line.location_id ? (Array.isArray(line.location_id) ? line.location_id[0] : line.location_id.id) : (this.state.picking.location_id ? this.state.picking.location_id[0] : null),
                        location_dest_id: line.location_dest_id ? (Array.isArray(line.location_dest_id) ? line.location_dest_id[0] : line.location_dest_id.id) : (this.state.picking.location_dest_id ? this.state.picking.location_dest_id[0] : null),
                        product_uom_id: this.lineUomId(line),
                        owner_id: this.lineOwnerId(line),
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    });
                } else {
                    commands.push({
                        action: 'write',
                        line_id: line.id,
                        quantity: line.quantity,
                        is_byproduct: line.is_byproduct || undefined,
                        picked: line.is_byproduct ? Boolean(line.picked) : undefined,
                        product_uom_id: this.lineUomId(line),
                        owner_id: this.lineOwnerId(line),
                        lot_id: line.lot_id ? (Array.isArray(line.lot_id) ? line.lot_id[0] : line.lot_id.id) : null,
                        lot_name: line.lot_id && Array.isArray(line.lot_id) && !line.lot_id[0] ? line.lot_id[1] : null,
                        package_id: line.source_package ? (Array.isArray(line.source_package) ? line.source_package[0] : (typeof line.source_package === 'object' ? line.source_package.id : line.source_package)) : (line.package_id ? (Array.isArray(line.package_id) ? line.package_id[0] : (typeof line.package_id === 'object' ? line.package_id.id : line.package_id)) : null),
                        result_package_id: line.dest_package ? (Array.isArray(line.dest_package) ? line.dest_package[0] : (typeof line.dest_package === 'object' ? line.dest_package.id : line.dest_package)) : (line.result_package_id ? (Array.isArray(line.result_package_id) ? line.result_package_id[0] : (typeof line.result_package_id === 'object' ? line.result_package_id.id : line.result_package_id)) : null),
                        destination_container_package: line.dest_container_package ? (Array.isArray(line.dest_container_package) ? line.dest_container_package[0] : (typeof line.dest_container_package === 'object' ? line.dest_container_package.id : line.dest_container_package)) : null,
                    });
                }
            }

            let model = this.isMO ? 'mrp.production' : 'stock.picking';
            // MO: Odoo's Produce, keeping the Put-in-Pack package of the finished product
            let validateMethod = this.isMO ? 'barcode_mark_done' : 'button_validate';
            let successMsg = this.isMO ? "Order produced successfully!" : "Transfer validated successfully!";

            let oldBackordersCount = this.state.picking && this.state.picking.backorders ? this.state.picking.backorders.length : 0;

            await this.orm.call(
                model,
                'process_barcode_sync',
                [[parseInt(this.props.pickingId)], commands]
            );

            // Try to validate the transfer initially
            let result = await this.orm.call(
                model,
                validateMethod,
                [[parseInt(this.props.pickingId)]]
            );

            // If it returned the Immediate Transfer wizard (only for stock.picking), autofill and re-validate
            if (!this.isMO && typeof result === 'object' && result !== null && result.type === 'ir.actions.act_window' && result.res_model === 'stock.immediate.transfer') {
                await this.orm.call(model, 'action_barcode_autofill', [[parseInt(this.props.pickingId)]]);
                result = await this.orm.call(
                    model,
                    validateMethod,
                    [[parseInt(this.props.pickingId)]]
                );
            }

            if (typeof result === 'object' && result !== null && result.type && result.type.startsWith('ir.actions')) {
                // Intercept backorder wizard
                if (result.res_model === 'stock.backorder.confirmation') {
                    this.state.showBackorderModal = true;
                    this.state.backorderContext = result.context || {};
                    return; // Stop here, the modal will handle the rest
                }

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
                    result.context.active_model = model;
                    result.context.active_id = parseInt(this.props.pickingId);
                    result.context.active_ids = [parseInt(this.props.pickingId)];
                }

                if (result.type === 'ir.actions.report') {
                    this.actionService.doAction(result); // Do not await report downloads
                    this.notification.add(successMsg, { type: "success" });
                    this.props.onBack(true);
                } else if (result.type === 'ir.actions.act_window' && result.target === 'new') {
                    this.actionService.doAction(result, {
                        onClose: async () => {
                            await this.loadPickingState();
                            if (result.res_model === 'quality.check.wizard') {
                                this.fillQuantitiesAfterQualityChecks();
                            }
                            if (this.state.picking && (this.state.picking.state === 'done' || this.state.picking.state === 'to_close')) {
                                this.notification.add(successMsg, { type: "success" });
                                this.props.onBack(true);
                            }
                        }
                    });
                } else {
                    await this.actionService.doAction(result);
                    await this.loadPickingState();
                    if (this.state.picking && (this.state.picking.state === 'done' || this.state.picking.state === 'to_close')) {
                        let newBackordersCount = this.state.picking.backorders ? this.state.picking.backorders.length : 0;
                        if (newBackordersCount > oldBackordersCount) {
                            let newBo = this.state.picking.backorders[newBackordersCount - 1];
                            this.notification.add(`Transfer validated! Backorder ${newBo.name} created.`, {
                                type: "success",
                                buttons: [{
                                    name: `Open ${newBo.name}`,
                                    primary: true,
                                    onClick: () => {
                                        if (this.props.openPicking) {
                                            this.props.openPicking(newBo.id);
                                        }
                                    }
                                }]
                            });
                        }
                        this.notification.add(successMsg, { type: "success" });
                        this.props.onBack(true);
                    }
                }
            } else {
                this.notification.add(successMsg, { type: "success" });
                this.props.onBack(true);
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
        if (this.props.batchId) {
            return this.createBatchReturn();
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

    /** Return Products on a done batch: returns of its transfers (grouped in a new batch). */
    async createBatchReturn() {
        try {
            const result = await this.orm.call(
                'stock.picking.batch',
                'action_barcode_create_return',
                [[parseInt(this.props.batchId)]]
            );
            if (result && result.batch_id) {
                this.notification.add(`Return batch ${result.name} created! Scan products to return.`, { type: "success" });
                this.actionService.doAction({
                    type: 'ir.actions.client',
                    tag: 'custom_barcode_client_action',
                    params: { batch_id: result.batch_id },
                }, { clearBreadcrumbs: true });
            } else if (result && result.picking_id) {
                this.notification.add("Return created! Scan products to return.", { type: "success" });
                this.actionService.doAction({
                    type: 'ir.actions.client',
                    tag: 'custom_barcode_client_action',
                    params: { picking_id: result.picking_id },
                }, { clearBreadcrumbs: true });
            } else if (result && result.picking_ids) {
                // returns of different operation types cannot share a batch: show them
                this.notification.add("Returns created.", { type: "success" });
                this.actionService.doAction({
                    type: 'ir.actions.act_window',
                    name: 'Returns',
                    res_model: 'stock.picking',
                    views: [[false, 'list'], [false, 'form']],
                    domain: [['id', 'in', result.picking_ids]],
                    target: 'current',
                });
            }
        } catch (e) {
            console.error("Return Error:", e);
            const errorMsg = e.data && e.data.message ? e.data.message : (e.message || "Error creating return.");
            this.notification.add(errorMsg, { type: "danger" });
        }
    }

    async openMoveRecord(line) {
        if (!line || !line.move_id) return;

        await this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'stock.move',
            res_id: line.move_id,
            views: [[false, 'form']],
            target: 'new',
            name: 'Open: Stock Moves'
        });
    }

    closeBackorderModal() {
        this.state.showBackorderModal = false;
    }

    async createBackorder() {
        try {
            this.state.showBackorderModal = false;
            let result = await this.orm.call(
                'stock.picking',
                'barcode_confirm_backorder',
                [[parseInt(this.props.pickingId)]]
            );
            
            if (result && result.success) {
                if (result.backorder) {
                    this.notification.add(`Transfer validated! Backorder ${result.backorder.name} created.`, {
                        type: "success",
                        buttons: [{
                            name: `Open ${result.backorder.name}`,
                            primary: true,
                            onClick: () => {
                                if (this.props.openPicking) {
                                    this.props.openPicking(result.backorder.id);
                                }
                            }
                        }]
                    });
                } else {
                    this.notification.add("Transfer validated successfully!", { type: "success" });
                }
                this.props.onBack(true);
            }
        } catch (e) {
            console.error("Backorder Error:", e);
            let msg = (e.data && (e.data.arguments?.[0] || e.data.message)) || e.message || "Failed to create backorder.";
            this.notification.add(msg, { type: "danger" });
        }
    }

    async noBackorder() {
        try {
            this.state.showBackorderModal = false;
            let result = await this.orm.call(
                'stock.picking',
                'barcode_cancel_backorder',
                [[parseInt(this.props.pickingId)]]
            );
            this.notification.add("Transfer validated successfully! (No Backorder)", { type: "success" });
            this.props.onBack(true);
        } catch (e) {
            console.error("No Backorder Error:", e);
            let msg = (e.data && (e.data.arguments?.[0] || e.data.message)) || e.message || "Failed to validate without backorder.";
            this.notification.add(msg, { type: "danger" });
        }
    }
}

LineScanScreen.template = "custom_barcode_scanner.LineScanScreen";
LineScanScreen.components = { View, LotDialog };
