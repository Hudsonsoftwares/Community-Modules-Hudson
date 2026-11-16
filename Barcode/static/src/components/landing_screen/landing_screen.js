/** @odoo-module **/

import { Component, proxy, signal, onWillUnmount, onWillStart, useProps } from "@odoo/owl";
import { useLayoutEffect } from "@web/owl2/utils";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class LandingScreen extends Component {
    // props (all optional functions): onOperationsClick, onInventoryClick,
    //        onPickingClick, onPickingTypeClick, onBatchClick
    props = useProps();

    setup() {
        this.barcodeService = useService("barcode_reader_service");
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.pwa = useService("pwa");
        this.videoRef = signal.ref();
        this.state = proxy({
            showCamera: false,
            manualBarcode: "",
            canInstall: false,
            pendingInventoryCount: 0
        });
        this.stream = null;

        onWillStart(async () => {
            try {
                const count = await this.orm.searchCount('stock.quant', [['inventory_quantity_set', '=', true]]);
                this.state.pendingInventoryCount = count;
            } catch (e) {
                console.error("Failed to fetch pending inventory count", e);
            }
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
                // We draw the video frame to a canvas and decode it manually
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
                // ZXing throws if barcode is not found, ignore
            }
        }
    }

    handleScan(text) {
        if (!this.state.showCamera) return;
        console.log("Scanned:", text);
        this.state.manualBarcode = text;
        this.applyManualBarcode();
        this.stopCamera();
        this.state.showCamera = false;
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
            this.state.manualBarcode = "";
        } catch (err) {
            console.error("Error accessing camera:", err);
            alert("Could not access the camera. Please ensure permissions are granted in your browser settings.");
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

    closeCamera() {
        this.stopCamera();
        this.state.showCamera = false;
    }

    async applyManualBarcode() {
        if (this.state.manualBarcode) {
            const barcode = this.state.manualBarcode.trim();
            this.state.manualBarcode = "";
            this.closeCamera();

            try {
                // 1. Search for an Operation Type (stock.picking.type)
                // (repair operations are not handled by the Barcode app)
                let pickingTypes = await this.orm.searchRead('stock.picking.type', [['barcode', '=', barcode], ['code', '!=', 'repair_operation']], ['id'], { limit: 1 });
                if (pickingTypes.length > 0) {
                    if (this.props.onPickingTypeClick) {
                        this.props.onPickingTypeClick(pickingTypes[0].id);
                    } else if (this.props.onPickingClick) {
                        // Fallback if component hierarchy doesn't directly expose onPickingTypeClick
                        // Though typically we'd emit an event or go through main_component
                        this.actionService.doAction({
                            type: 'ir.actions.client',
                            tag: 'custom_barcode_client_action',
                        });
                        // A better way is to bubble it up, but let's try calling props if they exist
                    }
                    return;
                }

                // 2. Search for an exact picking name
                let pickings = await this.orm.searchRead('stock.picking', [['name', '=', barcode]], ['id'], { limit: 1 });
                if (pickings.length > 0) {
                    if (this.props.onPickingClick) {
                        this.props.onPickingClick(pickings[0].id);
                    }
                    return;
                }

                // 2. Search for Product
                const products = await this.orm.searchRead('product.product', ['|', ['barcode', '=', barcode], ['default_code', '=', barcode]], ['id', 'display_name'], { limit: 1 });
                if (products.length > 0) {
                    this.actionService.doAction({
                        name: products[0].display_name,
                        type: 'ir.actions.act_window',
                        res_model: 'stock.quant',
                        views: [[false, 'list'], [false, 'form']],
                        domain: [['product_id', '=', products[0].id]],
                        context: { search_default_internal_loc: 1 }
                    });
                    return;
                }

                // 3. Search for Location
                const locations = await this.orm.searchRead('stock.location', [['barcode', '=', barcode]], ['id', 'display_name'], { limit: 1 });
                if (locations.length > 0) {
                    this.actionService.doAction({
                        name: locations[0].display_name,
                        type: 'ir.actions.act_window',
                        res_model: 'stock.quant',
                        views: [[false, 'list'], [false, 'form']],
                        domain: [['location_id', 'child_of', locations[0].id]],
                        context: { search_default_internal_loc: 1 }
                    });
                    return;
                }

                // 4. Fallback: Search for partial picking name (e.g. user typed "00001" for "WH/INT/00001")
                pickings = await this.orm.searchRead('stock.picking', [['name', 'ilike', barcode]], ['id', 'name'], { limit: 1 });
                if (pickings.length > 0) {
                    if (this.props.onPickingClick) {
                        this.props.onPickingClick(pickings[0].id);
                    }
                    return;
                }

                // 5. Not found anywhere
                this.notification.add(`No picking or location or product corresponding to barcode ${barcode}`, { type: 'danger' });

            } catch (e) {
                console.error("Error searching barcode:", e);
                this.notification.add(`Error searching for barcode: ${e.message}`, { type: 'danger' });
            }
        }
    }

    async installPwa() {
        if (this.pwa && this.pwa.isAvailable && this.pwa.canPromptToInstall) {
            await this.pwa.show();
        } else {
            this.notification.add("Installation is not supported in this browser, or the app is already installed.", { type: "info" });
        }
    }

    /**
     * Leave the Barcode app for Odoo's apps home screen (like Odoo 20 Online).
     * 1. a home menu service (Enterprise web client / Enterprise-style themes) -> show its apps grid
     * 2. any addon registering the "menu" client action -> open it, dropping the breadcrumbs
     * 3. plain Community -> reload the web client on its home (/odoo)
     */
    async goToAppsHome() {
        const homeMenu = this.env.services.home_menu;
        if (homeMenu && typeof homeMenu.toggle === "function") {
            await homeMenu.toggle(true);
        } else if (registry.category("actions").contains("menu")) {
            await this.actionService.doAction("menu", { clearBreadcrumbs: true });
        } else {
            window.location.assign("/odoo");
        }
    }

    async downloadDemoDataSheet(ev) {
        if (ev) ev.preventDefault();
        try {
            const pickingTypes = await this.orm.searchRead('stock.picking.type', [], ['id']);
            const ids = pickingTypes.map(pt => pt.id);
            if (ids.length > 0) {
                this.actionService.doAction('Barcode.action_report_barcode_demo_sheet', {
                    additionalContext: {
                        active_ids: ids,
                        active_model: 'stock.picking.type',
                    }
                });
            } else {
                this.notification.add("No operation types found.", { type: "warning" });
            }
        } catch (e) {
            console.error("Error downloading demo data sheet:", e);
            this.notification.add("Could not download the demo data sheet.", { type: "danger" });
        }
    }

    async downloadOperationBarcodes(ev) {
        if (ev) ev.preventDefault();
        try {
            const pickingTypes = await this.orm.searchRead('stock.picking.type', [], ['id']);
            const ids = pickingTypes.map(pt => pt.id);
            if (ids.length > 0) {
                this.actionService.doAction('Barcode.action_report_barcode_commands', {
                    additionalContext: {
                        active_ids: ids,
                        active_model: 'stock.picking.type',
                    }
                });
            } else {
                this.notification.add("No operation types found.", { type: "warning" });
            }
        } catch (e) {
            console.error("Error downloading operation barcodes:", e);
            this.notification.add("Could not download operation barcodes.", { type: "danger" });
        }
    }
}
LandingScreen.template = "Barcode.LandingScreen";
