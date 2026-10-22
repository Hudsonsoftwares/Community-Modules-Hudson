/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { WithSearch } from "@web/search/with_search/with_search";
import { SearchBar } from "@web/search/search_bar/search_bar";

export class HomeGrid extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({ operationTypes: [] });

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
            searchDomain || [], 
            ['name', 'code', 'count_picking_ready']
        );
        this.state.operationTypes = types;
        if (this.props.onDataLoaded) {
            this.props.onDataLoaded(types.length + (!searchDomain || searchDomain.length === 0 ? 1 : 0)); // +1 for Inventory Adjustments if no domain
        }
    }
}
HomeGrid.template = "custom_barcode_scanner.HomeGrid";
HomeGrid.props = ["domain", "onTypeClick", "onDataLoaded"];

export class HomeScreen extends Component {
    setup() {
        this.barcodeService = useService("barcode_reader_service");
        this.onGlobalScanBound = this.onGlobalScan.bind(this);
        this.barcodeService.addEventListener("barcode_scanned", this.onGlobalScanBound);
        this.state = useState({ count: 0 });

        onWillDestroy(() => {
            this.barcodeService.removeEventListener("barcode_scanned", this.onGlobalScanBound);
        });
    }

    async onGlobalScan(ev) {
        const barcode = ev.detail.barcode;
        console.log("Global scan from home:", barcode);
    }
}

HomeScreen.template = "custom_barcode_scanner.HomeScreen";
HomeScreen.components = { WithSearch, SearchBar, HomeGrid };
HomeScreen.props = ["onTypeClick", "onBack"];
