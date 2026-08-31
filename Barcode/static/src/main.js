/** @odoo-module **/

import { registry } from "@web/core/registry";
import { MainComponent } from "./components/main_component/main_component";

registry.category("actions").add("custom_barcode_client_action", MainComponent);
