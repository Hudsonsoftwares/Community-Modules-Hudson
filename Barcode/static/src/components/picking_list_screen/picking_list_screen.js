/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps, useRef, useEffect, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { WithSearch } from "@web/search/with_search/with_search";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class PickingGrid extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({ pickings: [], offset: 0, limit: 50, hasMore: false });

        onWillStart(async () => {
            if (this.props.pickingTypeId === 'inventory') {
                this.props.onPickingClick('inventory'); 
            } else {
                await this.loadPickings(this.props.domain || [], false);
            }
        });

        onWillUpdateProps(async (nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain)) {
                this.state.offset = 0;
                await this.loadPickings(nextProps.domain || [], false);
            }
        });
    }

    async loadPickings(searchDomain, append = false) {
        const domain = [
            ['picking_type_id', '=', this.props.pickingTypeId],
            ...(searchDomain || [])
        ];
        
        if (!append) {
            this.state.offset = 0;
        }

        const results = await this.orm.searchRead(
            'stock.picking', 
            domain, 
            ['name', 'partner_id', 'scheduled_date', 'state'],
            { limit: this.state.limit, offset: this.state.offset }
        );
        
        if (append) {
            this.state.pickings.push(...results);
        } else {
            this.state.pickings = results;
        }
        
        this.state.hasMore = results.length === this.state.limit;
        
        if (this.props.onDataLoaded) {
            this.props.onDataLoaded(this.state.pickings.length);
        }
    }
    
    async loadMore() {
        if (!this.state.hasMore) return;
        this.state.offset += this.state.limit;
        await this.loadPickings(this.props.domain || [], true);
    }

    formatDate(dateStr) {
        if (!dateStr) return "";
        const parts = dateStr.split(" ")[0].split("-");
        if (parts.length === 3) {
            const date = new Date(parts[0], parts[1]-1, parts[2]);
            return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
        }
        return dateStr;
    }
}
PickingGrid.template = "custom_barcode_scanner.PickingGrid";
PickingGrid.props = ["domain", "pickingTypeId", "onPickingClick", "onDataLoaded"];

export class PickingListScreen extends Component {
    setup() {
        this.orm = useService("orm");
        this.barcodeService = useService("barcode_reader_service");
        this.notification = useService("notification");
        this.videoRef = useRef("videoElement");
        this.stream = null;
        
        this.state = useState({
            pickingTypeName: "",
            count: 0,
            showScanner: false,
            manualBarcode: "",
            barcodeFilter: "",
            barcodeDomain: []
        });

        // Stream is assigned directly in toggleScanner when it resolves.

        onWillUnmount(() => {
            this.stopCamera();
        });

        onWillStart(async () => {
            if (this.props.pickingTypeId !== 'inventory') {
                try {
                    const typeInfo = await this.orm.read('stock.picking.type', [this.props.pickingTypeId], ['name']);
                    if (typeInfo.length) {
                        this.state.pickingTypeName = typeInfo[0].name;
                    }
                } catch (e) {
                    console.error("Error fetching picking type name:", e);
                }
            }
        });
    }

    async createNewPicking() {
        if (this.props.pickingTypeId === 'inventory') {
            // Inventory adjustments don't create pickings
            return;
        }
        try {
            const pickingTypes = await this.orm.read('stock.picking.type', [parseInt(this.props.pickingTypeId)], ['default_location_src_id', 'default_location_dest_id']);
            if (!pickingTypes.length) return;
            
            const pt = pickingTypes[0];
            
            if (!pt.default_location_src_id || !pt.default_location_dest_id) {
                this.notification.add(
                    "Cannot create transfer: Operation Type is missing Default Source or Destination Locations.",
                    { type: "danger" }
                );
                return;
            }
            
            const values = {
                picking_type_id: pt.id,
                location_id: pt.default_location_src_id[0],
                location_dest_id: pt.default_location_dest_id[0],
            };
            
            const pickingId = await this.orm.create('stock.picking', [values]);
            
            if (this.props.onPickingClick && pickingId && pickingId.length) {
                this.props.onPickingClick(pickingId[0]);
            }
        } catch (e) {
            console.error("Error creating picking:", e);
        }
    }

    async toggleScanner() {
        this.state.showScanner = !this.state.showScanner;
        if (this.state.showScanner) {
            if (!window.ZXing) {
                // Ensure ZXing is loaded if native BarcodeDetector isn't available
                const script = document.createElement('script');
                script.src = "https://unpkg.com/@zxing/library@0.21.2/umd/index.min.js";
                document.head.appendChild(script);
            }
            try {
                this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } } });
                if (this.videoRef.el) {
                    this.videoRef.el.srcObject = this.stream;
                    this.videoRef.el.play().catch(e => console.error("Video play failed:", e));
                    
                    // Initialize barcode reading loop
                    this.scanInterval = setInterval(() => {
                        this.scanFrame();
                    }, 300);
                }
            } catch (err) {
                console.error("Error accessing camera:", err);
                this.notification.add("Could not access camera. You can still type the barcode.", { type: "warning" });
            }
        } else {
            this.stopCamera();
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
        if (!this.state.showScanner || !this.videoRef.el || this.videoRef.el.readyState !== 4) return;
        
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
        if (!this.state.showScanner) return;
        console.log("Scanned:", text);
        this.state.manualBarcode = text;
        this.applyManualBarcode();
    }

    onManualBarcodeInput(ev) {
        this.state.manualBarcode = ev.target.value;
    }

    onKeyup(ev) {
        if (ev.key === 'Enter') {
            this.applyManualBarcode();
        }
    }

    async applyManualBarcode() {
        if (this.state.manualBarcode) {
            const barcode = this.state.manualBarcode.trim();
            this.state.manualBarcode = "";
            this.toggleScanner();
            await this.processBarcode(barcode);
        }
    }

    async processBarcode(barcode) {
        try {
            // Try exact match on picking name first
            const ptId = parseInt(this.props.pickingTypeId);
            if (!isNaN(ptId)) {
                const pickings = await this.orm.searchRead('stock.picking', [['name', '=', barcode], ['picking_type_id', '=', ptId]], ['id'], {limit: 1});
                if (pickings.length > 0) {
                    this.props.onPickingClick(pickings[0].id);
                    return;
                }
            }
            
            // Try Location
            const locs = await this.orm.searchRead('stock.location', [['barcode', '=', barcode]], ['id'], {limit: 1});
            if (locs.length > 0) {
                this.state.barcodeFilter = barcode;
                this.state.barcodeDomain = ['|', ['location_id', '=', locs[0].id], ['location_dest_id', '=', locs[0].id]];
                return;
            }
            
            // Try Product
            const prods = await this.orm.searchRead('product.product', [['barcode', '=', barcode]], ['id'], {limit: 1});
            if (prods.length > 0) {
                this.state.barcodeFilter = barcode;
                this.state.barcodeDomain = [['move_ids.product_id', '=', prods[0].id]];
                return;
            }
            
            // Fallback: filter by picking name
            this.state.barcodeFilter = barcode;
            this.state.barcodeDomain = [['name', 'ilike', barcode]];
        } catch (e) {
            console.error("Error processing barcode:", e);
            // Even if backend search fails, still fallback so badge shows up
            this.state.barcodeFilter = barcode;
            this.state.barcodeDomain = [['name', 'ilike', barcode]];
        }
    }

    getGridDomain(searchDomain) {
        const domain = [...(searchDomain || [])];
        if (this.state.barcodeDomain && this.state.barcodeDomain.length > 0) {
            domain.push(...this.state.barcodeDomain);
        }
        return domain;
    }
}

PickingListScreen.template = "custom_barcode_scanner.PickingListScreen";
PickingListScreen.components = { WithSearch, SearchBar, PickingGrid };
PickingListScreen.props = ["pickingTypeId", "onPickingClick", "onBack"];
