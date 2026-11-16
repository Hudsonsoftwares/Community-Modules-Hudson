/** @odoo-module **/

import { Component, proxy, onWillStart, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { HomeScreen } from "../home_screen/home_screen";
import { PickingListScreen } from "../picking_list_screen/picking_list_screen";
import { LineScanScreen } from "../line_scan_screen/line_scan_screen";
import { LandingScreen } from "../landing_screen/landing_screen";

export class MainComponent extends Component {
    props = useProps();

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");

        this.state = proxy({
            currentScreen: "landing", // landing | home | picking_list | line_scan | batch_scan
            pickingTypeId: null,
            pickingId: null,
            batchId: null,
            batchName: null,
        });

        onWillStart(async () => {
            const params = this.props.action.params || {};
            if (params.picking_id) {
                this.state.pickingId = params.picking_id;
                this.state.currentScreen = "line_scan";
            } else if (params.picking_type_id) {
                this.state.pickingTypeId = params.picking_type_id;
                this.state.currentScreen = "picking_list";
            } else if (params.batch_id) {
                this.state.batchId = params.batch_id;
                this.state.currentScreen = "batch_scan";
            }
        });
    }

    goToLanding() {
        this.state.currentScreen = "landing";
        this.state.pickingTypeId = null;
        this.state.pickingId = null;
        this.state.batchId = null;
        this.state.batchName = null;
    }

    goToHome() {
        this.state.currentScreen = "home";
        this.state.pickingTypeId = null;
        this.state.pickingId = null;
        this.state.batchId = null;
        this.state.batchName = null;
    }

    goToInventory() {
        this.state.pickingTypeId = "inventory";
        this.state.pickingId = "inventory";
        this.state.currentScreen = "line_scan";
    }

    goToPickingList(pickingTypeId) {
        this.state.pickingTypeId = pickingTypeId;
        this.state.currentScreen = "picking_list";
        this.state.pickingId = null;
        this.state.batchId = null;
    }

    goToLineScan(pickingId, pickingTypeId = null) {
        this.state.pickingId = pickingId;
        if (pickingTypeId) this.state.pickingTypeId = pickingTypeId;
        this.state.currentScreen = "line_scan";
    }

    /** Opened directly on a transfer/batch (no list behind it): if we came from a backend
     *  form ("Barcode" smart button), go back to that form like Odoo Online; else Barcode home. */
    backToCallerOrHome() {
        const breadcrumbs = (this.env.config && this.env.config.breadcrumbs) || [];
        if (breadcrumbs.length > 1) {
            this.actionService.restore().catch(() => this.goToHome());
        } else {
            this.goToHome();
        }
    }

    goBackFromLineScan() {
        if (this.state.pickingTypeId && this.state.pickingTypeId !== "inventory") {
            this.state.currentScreen = "picking_list";
            this.state.pickingId = null;
        } else if (!this.state.pickingTypeId) {
            this.backToCallerOrHome();
        } else {
            this.goToHome();
        }
    }

    goToBatchScan(batchId, batchName) {
        this.state.batchId = batchId;
        this.state.batchName = batchName;
        this.state.currentScreen = "batch_scan";
    }

    goBackFromBatchScan() {
        if (!this.state.pickingTypeId) {
            this.backToCallerOrHome();
            return;
        }
        this.state.currentScreen = "picking_list";
        this.state.batchId = null;
        this.state.batchName = null;
    }
}

MainComponent.components = { LandingScreen, HomeScreen, PickingListScreen, LineScanScreen };
MainComponent.template = "custom_barcode_scanner.MainComponent";
