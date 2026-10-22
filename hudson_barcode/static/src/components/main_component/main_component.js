/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { HomeScreen } from "../home_screen/home_screen";
import { PickingListScreen } from "../picking_list_screen/picking_list_screen";
import { LineScanScreen } from "../line_scan_screen/line_scan_screen";
import { LandingScreen } from "../landing_screen/landing_screen";

export class MainComponent extends Component {
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        
        this.state = useState({
            currentScreen: 'landing', // 'landing', 'home', 'picking_list', 'line_scan'
            pickingTypeId: null,
            pickingId: null,
        });

        onWillStart(async () => {
            // Check if we were launched with a specific picking or model
            const params = this.props.action.params || {};
            if (params.picking_id) {
                this.state.pickingId = params.picking_id;
                this.state.currentScreen = 'line_scan';
            } else if (params.picking_type_id) {
                this.state.pickingTypeId = params.picking_type_id;
                this.state.currentScreen = 'picking_list';
            }
        });
    }

    goToLanding() {
        this.state.currentScreen = 'landing';
        this.state.pickingTypeId = null;
        this.state.pickingId = null;
    }

    goToHome() {
        this.state.currentScreen = 'home';
        this.state.pickingTypeId = null;
        this.state.pickingId = null;
    }

    goToInventory() {
        this.state.pickingTypeId = 'inventory';
        this.state.pickingId = 'inventory';
        this.state.currentScreen = 'line_scan';
    }

    goToPickingList(pickingTypeId) {
        this.state.pickingTypeId = pickingTypeId;
        this.state.currentScreen = 'picking_list';
        this.state.pickingId = null;
    }

    goToLineScan(pickingId) {
        this.state.pickingId = pickingId;
        this.state.currentScreen = 'line_scan';
    }

    goBackFromLineScan() {
        if (this.state.pickingTypeId && this.state.pickingTypeId !== 'inventory') {
            this.state.currentScreen = 'picking_list';
            this.state.pickingId = null;
        } else {
            this.goToHome();
        }
    }
}

MainComponent.components = { LandingScreen, HomeScreen, PickingListScreen, LineScanScreen };
MainComponent.template = "custom_barcode_scanner.MainComponent";
