/** @odoo-module **/

import { Component, proxy, onWillStart, onWillUpdateProps, onWillDestroy, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { download } from "@web/core/network/download";
import { WithSearch } from "@web/search/with_search/with_search";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class HomeGrid extends Component {
    // props: domain (Array, optional), groupBy (Array, optional),
    //        onTypeClick (Function, optional), onDataLoaded (Function, optional)
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ operationTypes: [] });

        onWillStart(async () => {
            await this.loadOperationTypes(this.props.domain || []);
        });

        onWillUpdateProps(async (nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain)) {
                await this.loadOperationTypes(nextProps.domain || []);
            }
        });
    }

    async loadOperationTypes(searchDomain) {
        const types = await this.orm.searchRead(
            'stock.picking.type',
            // Repair operations are not handled by the Barcode app (as in Odoo Online)
            [['code', '!=', 'repair_operation'], ...(searchDomain || [])],
            ['name', 'code', 'count_picking_ready', 'count_mo_confirmed', 'warehouse_id']
        );
        this.state.operationTypes = types;
        if (this.props.onDataLoaded) {
            this.props.onDataLoaded(types.length + (!searchDomain || searchDomain.length === 0 ? 1 : 0)); // +1 for Inventory Adjustments if no domain
        }
    }

    get groupedOperations() {
        let groups = [];
        let groupByField = this.props.groupBy && this.props.groupBy.length > 0 ? this.props.groupBy[0] : null;

        if (!groupByField) {
            groups.push({
                title: "Operations",
                items: [...this.state.operationTypes]
            });
            if (!this.props.domain || this.props.domain.length === 0) {
                groups[0].items.push({
                    id: 'inventory',
                    name: 'Inventory Adjustments',
                    is_inventory: true
                });
            }
            return groups;
        }

        let map = new Map();
        for (let type of this.state.operationTypes) {
            let key = "Undefined";
            let val = type[groupByField];
            if (val) {
                if (Array.isArray(val)) {
                    key = val[1];
                } else if (groupByField === 'code') {
                    key = val === 'incoming' ? 'Receipt' :
                          val === 'outgoing' ? 'Delivery' :
                          val === 'internal' ? 'Internal Transfer' :
                          val === 'mrp_operation' ? 'Manufacturing' : val;
                } else {
                    key = val.toString();
                }
            }
            if (!map.has(key)) map.set(key, []);
            map.get(key).push(type);
        }

        if (!this.props.domain || this.props.domain.length === 0) {
            let invKey = groupByField === 'code' ? 'Inventory' : 'Undefined';
            if (!map.has(invKey)) map.set(invKey, []);
            map.get(invKey).push({
                id: 'inventory',
                name: 'Inventory Adjustments',
                is_inventory: true
            });
        }

        for (let [title, items] of map.entries()) {
            groups.push({ title, items });
        }
        
        // Sort groups alphabetically by title
        groups.sort((a, b) => a.title.localeCompare(b.title));
        return groups;
    }
}
HomeGrid.template = "custom_barcode_scanner.HomeGrid";

export class HomeScreen extends Component {
    // props: onTypeClick, onBack
    props = useProps();

    setup() {
        this.barcodeService = useService("barcode_reader_service");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.onGlobalScanBound = this.onGlobalScan.bind(this);
        this.barcodeService.addEventListener("barcode_scanned", this.onGlobalScanBound);
        this.state = proxy({ count: 0 });

        onWillDestroy(() => {
            this.barcodeService.removeEventListener("barcode_scanned", this.onGlobalScanBound);
        });
    }

    async onGlobalScan(ev) {
        const barcode = ev.detail.barcode;
        console.log("Global scan from home:", barcode);
    }

    async exportData() {
        try {
            const allFields = await this.orm.call('stock.picking.type', 'fields_get', [], {attributes: ['type']});
            
            const desiredFields = [
                {name: 'color', label: 'Color'},
                {name: 'code', label: 'Type of Operation'},
                {name: 'is_barcode_picking_type', label: 'Is Barcode Picking Type'},
                {name: 'name', label: 'Operation Type'},
                {name: 'count_mo_confirmed', label: 'Count Mo Confirmed'},
                {name: 'count_picking_ready', label: 'Count Picking Ready'}
            ];
            
            const validFields = desiredFields.filter(f => allFields[f.name]);

            await download({
                url: '/web/export/xlsx',
                data: {
                    data: JSON.stringify({
                        model: 'stock.picking.type',
                        fields: validFields,
                        ids: false,
                        domain: [],
                        context: {},
                        import_compat: false,
                    })
                }
            });
            this.notification.add("Export successful", {type: "success"});
        } catch (e) {
            console.error(e);
            this.notification.add("Export failed: " + (e.message || "Unknown error"), {type: "danger"});
        }
    }
}

HomeScreen.template = "custom_barcode_scanner.HomeScreen";
HomeScreen.components = { WithSearch, SearchBar, HomeGrid };
