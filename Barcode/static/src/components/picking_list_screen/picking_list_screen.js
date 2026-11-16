/** @odoo-module **/

import { Component, proxy, onWillStart, onWillUpdateProps, signal, onWillUnmount, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { download } from "@web/core/network/download";
import { WithSearch } from "@web/search/with_search/with_search";
import { SearchBar } from "@web/search/search_bar/search_bar";

/** Batches of an operation type whose transfers match the search filters (transfer filters:
 *  a batch is kept when at least one of its transfers matches). Used by the Batches grid and
 *  by the tab counter, so both always agree. */
function batchGridDomain(pickingTypeId, searchDomain) {
    const domain = [['picking_type_id', '=', pickingTypeId]];
    if (searchDomain && searchDomain.length) {
        domain.push(['picking_ids', 'any', searchDomain]);
    }
    return domain;
}

export class PickingGrid extends Component {
    // props: domain, groupBy (search panel "Group By", optional), pickingTypeId, onPickingClick, onBatchClick, showBatches, onDataLoaded
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.state = proxy({
            pickings: [], offset: 0, limit: 50, hasMore: false,
            // Group By (kanban columns, like Odoo Online): first level of the search panel groupBy
            grouped: false, groups: [],
        });
        this.groupRecordsLimit = 20;  // cards loaded per column (more with "Load more")
        this.maxGroups = 30;          // columns shown at most
        this.selectionLabels = {};    // cache: model.field -> {value: label}

        onWillStart(async () => {
            if (this.props.pickingTypeId === 'inventory') {
                this.props.onPickingClick('inventory');
            } else {
                if (!this.props.pickingTypeCode) {
                    try {
                        const pt = await this.orm.read('stock.picking.type', [this.props.pickingTypeId], ['code']);
                        if (pt.length) this.pickingTypeCode = pt[0].code;
                    } catch (e) {}
                } else {
                    this.pickingTypeCode = this.props.pickingTypeCode;
                }
                await this.loadPickings(this.props.domain || [], false, this.props.groupBy);
            }
        });

        onWillUpdateProps(async (nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain) ||
                JSON.stringify(nextProps.groupBy || []) !== JSON.stringify(this.props.groupBy || [])) {
                this.state.offset = 0;
                await this.loadPickings(nextProps.domain || [], false, nextProps.groupBy);
            }
        });
    }

    get resModel() {
        return this.pickingTypeCode === 'mrp_operation' ? 'mrp.production' : 'stock.picking';
    }

    get readFields() {
        return this.pickingTypeCode === 'mrp_operation'
            ? ['name', 'origin', 'product_id', 'product_qty', 'uom_id', 'date_start', 'state']
            : ['name', 'origin', 'partner_id', 'scheduled_date', 'state', 'batch_id'];
    }

    /** One loop in the template serves both layouts: a single hidden group when not grouped. */
    get displayGroups() {
        if (this.state.grouped) {
            return this.state.groups;
        }
        return [{ key: "__all", label: "", count: this.state.pickings.length, records: this.state.pickings }];
    }

    async loadPickings(searchDomain, append = false, groupBy = undefined) {
        this.loadedSearchDomain = searchDomain || [];
        const domain = [
            ['picking_type_id', '=', this.props.pickingTypeId],
            ...(searchDomain || [])
        ];

        if (groupBy === undefined) {
            groupBy = this.props.groupBy;
        }
        if (groupBy && groupBy.length) {
            await this.loadGroups(domain, groupBy[0]);
            return;
        }
        this.state.grouped = false;
        this.state.groups = [];

        if (!append) {
            this.state.offset = 0;
        }

        const results = await this.orm.searchRead(
            this.resModel,
            domain,
            this.readFields,
            { limit: this.state.limit, offset: this.state.offset }
        );

        if (append) {
            this.state.pickings.push(...results);
        } else {
            this.state.pickings = results;
        }

        this.state.hasMore = results.length === this.state.limit;

        if (this.props.onDataLoaded) {
            this.props.onDataLoaded(this.state.pickings.length, this.loadedSearchDomain);
        }
    }

    /** Grouped (kanban columns) loading, like Odoo Online's grouped kanban. */
    async loadGroups(domain, groupBySpec) {
        const fieldName = groupBySpec.split(":")[0];
        const [groups, labels] = await Promise.all([
            this.orm.formattedReadGroup(this.resModel, domain, [groupBySpec], ["__count"], { limit: this.maxGroups }),
            this.getSelectionLabels(fieldName),
        ]);
        const columns = await Promise.all(groups.map(async (group) => {
            const value = group[groupBySpec];
            const records = await this.orm.searchRead(
                this.resModel, group.__domain, this.readFields, { limit: this.groupRecordsLimit }
            );
            return {
                key: JSON.stringify(value),
                label: this.groupLabel(value, labels),
                count: group.__count,
                domain: group.__domain,
                records,
            };
        }));
        this.state.pickings = [];
        this.state.hasMore = false;
        this.state.groups = columns;
        this.state.grouped = true;
        if (this.props.onDataLoaded) {
            this.props.onDataLoaded(columns.reduce((total, column) => total + column.count, 0), this.loadedSearchDomain);
        }
    }

    /** Open the batch a transfer belongs to (badge on the transfer card). */
    openPickingBatch(batch) {
        if (batch && this.props.onBatchClick) {
            this.props.onBatchClick(batch[0], batch[1]);
        }
    }

    async loadMoreInGroup(group) {
        const more = await this.orm.searchRead(
            this.resModel, group.domain, this.readFields,
            { limit: this.groupRecordsLimit, offset: group.records.length }
        );
        group.records.push(...more);
    }

    /** {value: label} for selection fields (e.g. Status), so columns read "Ready" not "assigned". */
    async getSelectionLabels(fieldName) {
        const cacheKey = `${this.resModel}.${fieldName}`;
        if (!(cacheKey in this.selectionLabels)) {
            let labels = {};
            try {
                const fields = await this.orm.call(this.resModel, "fields_get", [[fieldName]], { attributes: ["type", "selection"] });
                const field = fields[fieldName];
                if (field && field.type === "selection" && Array.isArray(field.selection)) {
                    labels = Object.fromEntries(field.selection);
                }
            } catch (e) {
                // not a plain field (e.g. a property): the label comes from the group value itself
            }
            this.selectionLabels[cacheKey] = labels;
        }
        return this.selectionLabels[cacheKey];
    }

    groupLabel(value, selectionLabels) {
        if (value === false || value === null || value === undefined || value === "") {
            return "None";
        }
        if (Array.isArray(value)) {
            // many2one: [id, name] / date interval: [value, label]
            return String(value[1] ?? value[0]);
        }
        if (typeof value === "string" && value in selectionLabels) {
            return selectionLabels[value];
        }
        return String(value);
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
            const date = new Date(parts[0], parts[1] - 1, parts[2]);
            return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
        }
        return dateStr;
    }
}
PickingGrid.template = "custom_barcode_scanner.PickingGrid";

export class BatchGrid extends Component {
    // props: domain, pickingTypeId, onBatchClick, onDataLoaded
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ batches: [], loading: true });

        onWillStart(async () => {
            await this.loadBatches(this.props.domain || []);
        });

        onWillUpdateProps(async (nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain)) {
                await this.loadBatches(nextProps.domain || []);
            }
        });
    }

    async loadBatches(searchDomain) {
        this.state.loading = true;
        try {
            // The search panel / barcode filters are transfer (stock.picking) filters:
            // keep a batch when at least one of its transfers matches them.
            const domain = batchGridDomain(this.props.pickingTypeId, searchDomain);
            
            const batches = await this.orm.searchRead(
                "stock.picking.batch",
                domain,
                ["name", "state", "user_id", "scheduled_date", "picking_ids"],
                { order: "scheduled_date asc, name asc", limit: 80 }
            );

            for (const batch of batches) {
                batch.picking_count = batch.picking_ids ? batch.picking_ids.length : 0;
            }

            this.state.batches = batches;
            if (this.props.onDataLoaded) {
                this.props.onDataLoaded(batches.length, searchDomain || []);
            }
        } catch (e) {
            console.error("Failed to load batches:", e);
        }
        this.state.loading = false;
    }

    formatDate(dateStr) {
        if (!dateStr) return "";
        const parts = dateStr.split(" ")[0].split("-");
        if (parts.length === 3) {
            const d = new Date(parts[0], parts[1] - 1, parts[2]);
            return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
        }
        return dateStr;
    }

    getBatchStateLabel(state) {
        if (state === "in_progress") return "In Progress";
        if (state === "done") return "Done";
        if (state === "cancel") return "Cancelled";
        return "Draft";
    }

    getBatchStateColor(state) {
        if (state === "in_progress") return "#017e84";
        if (state === "done") return "#28a745";
        if (state === "cancel") return "#dc3545";
        return "#6c757d";
    }

    openBatch(batch) {
        this.props.onBatchClick(batch.id, batch.name);
    }
}
BatchGrid.template = "custom_barcode_scanner.BatchGrid";

export class PickingListScreen extends Component {
    // props: pickingTypeId, onPickingClick, onBatchClick, onBack, listReloadKey (optional)
    props = useProps();

    setup() {
        this.withSearchProps = {
            resModel: 'stock.picking',
            searchViewId: false,
            searchMenuTypes: ['filter', 'groupBy', 'favorite'],
            context: {
                search_default_to_do_transfers: 1,
                search_default_available: 1
            }
        };
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.barcodeService = useService("barcode_reader_service");
        this.videoRef = signal.ref();
        this.stream = null;

        this.state = proxy({
            pickingTypeName: "",
            count: 0,
            showScanner: false,
            manualBarcode: "",
            barcodeFilter: "",
            barcodeDomain: [],
            activeTab: 'transfers',
            pickingCount: 0,
            batchCount: 0,
            // Inventory > Settings > Batch, Wave & Cluster Transfers (stock.group_stock_picking_batch)
            canUseBatches: false
        });

        // Stream is assigned directly in toggleScanner when it resolves.

        onWillUnmount(() => {
            this.stopCamera();
        });

        onWillStart(async () => {
            try {
                this.state.canUseBatches = await user.hasGroup("stock.group_stock_picking_batch");
            } catch (e) {
                this.state.canUseBatches = false;
            }
            if (this.props.pickingTypeId !== 'inventory') {
                try {
                    const typeInfo = await this.orm.read('stock.picking.type', [this.props.pickingTypeId], ['name', 'code']);
                    if (typeInfo.length) {
                        this.state.pickingTypeName = typeInfo[0].name;
                        this.state.pickingTypeCode = typeInfo[0].code;
                        if (typeInfo[0].code === 'mrp_operation') {
                            this.withSearchProps.resModel = 'mrp.production';
                            this.withSearchProps.context = {
                                search_default_todo: 1
                            };
                        }
                    }

                    // Tab counters are computed from the same filters as the lists
                    // (refreshTabCounts, called each time a list is loaded).
                } catch (e) {
                    console.error("Error fetching picking type info/counts:", e);
                }
            }
        });
    }

    async createNewPicking() {
        if (this.props.pickingTypeId === 'inventory') {
            // Inventory adjustments don't create pickings
            return;
        }
        if (this.state.pickingTypeCode === 'mrp_operation') {
            // Manufacturing (Odoo Online): empty 'New' MO screen; the MO is created with the
            // first product scanned there (a transfer must not be created for this type)
            this.props.onPickingClick('new_mo');
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

    async exportData() {
        try {
            await download({
                url: '/web/export/xlsx',
                data: {
                    data: JSON.stringify({
                        model: 'stock.picking',
                        fields: [
                            {name: 'name', label: 'Reference'},
                            {name: 'state', label: 'State'},
                            {name: 'partner_id', label: 'Contact'},
                            {name: 'scheduled_date', label: 'Scheduled Date'}
                        ],
                        ids: false,
                        domain: [['picking_type_id', '=', parseInt(this.props.pickingTypeId)]],
                        context: {},
                        import_compat: false,
                    })
                }
            });
            this.notification.add("Export successful", {type: "success"});
        } catch (e) {
            console.error(e);
            this.notification.add("Export failed", {type: "danger"});
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
                if (this.videoRef()) {
                    this.videoRef().srcObject = this.stream;
                    this.videoRef().play().catch(e => console.error("Video play failed:", e));

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
        if (!this.state.showScanner || !this.videoRef() || this.videoRef().readyState !== 4) return;

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
                const pickings = await this.orm.searchRead('stock.picking', [['name', '=', barcode], ['picking_type_id', '=', ptId]], ['id'], { limit: 1 });
                if (pickings.length > 0) {
                    this.props.onPickingClick(pickings[0].id);
                    return;
                }
            }

            // Try Location
            const locs = await this.orm.searchRead('stock.location', [['barcode', '=', barcode]], ['id'], { limit: 1 });
            if (locs.length > 0) {
                this.state.barcodeFilter = barcode;
                this.state.barcodeDomain = ['|', ['location_id', '=', locs[0].id], ['location_dest_id', '=', locs[0].id]];
                return;
            }

            // Try Product
            const prods = await this.orm.searchRead('product.product', [['barcode', '=', barcode]], ['id'], { limit: 1 });
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

    /** A list (transfers or batches) was loaded with these filters: update the shown count
     *  and both tab counters with exactly the same filters, so they never disagree. */
    onGridLoaded(loadedCount, searchDomain) {
        this.state.count = loadedCount;
        this.refreshTabCounts(searchDomain);
    }

    async refreshTabCounts(searchDomain) {
        if (this.props.pickingTypeId === 'inventory') {
            return;
        }
        const requestId = (this.tabCountRequest = (this.tabCountRequest || 0) + 1);
        const filters = searchDomain || [];
        const isMrp = this.state.pickingTypeCode === 'mrp_operation';
        try {
            const [pickingCount, batchCount] = await Promise.all([
                this.orm.searchCount(isMrp ? 'mrp.production' : 'stock.picking',
                    [['picking_type_id', '=', this.props.pickingTypeId], ...filters]),
                this.state.canUseBatches && !isMrp
                    ? this.orm.searchCount('stock.picking.batch', batchGridDomain(this.props.pickingTypeId, filters))
                    : Promise.resolve(0),
            ]);
            if (requestId !== this.tabCountRequest) {
                return;  // filters changed meanwhile: a newer count is on its way
            }
            this.state.pickingCount = pickingCount;
            this.state.batchCount = batchCount;
        } catch (e) {
            console.warn("Could not compute tab counts:", e);
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
PickingListScreen.components = { WithSearch, SearchBar, PickingGrid, BatchGrid };
