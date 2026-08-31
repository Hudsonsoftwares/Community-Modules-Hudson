/** @odoo-module **/

import { SaleUpdateLineButton } from "@sale/js/sale_portal_sidebar";
import { patch } from "@web/core/utils/patch";

// Patch SaleUpdateLineButton to handle null elements gracefully
patch(SaleUpdateLineButton.prototype, {
    setup() {
        // Check if the required element exists before calling super
        const portalSidebar = document.querySelector('.o_portal_sale_sidebar');
        if (!portalSidebar) {
            // Not on a sale order portal page, skip initialization
            return;
        }
        
        // Check if the button element exists
        const buttonElement = this.el?.closest('[data-oe-type="sale_order_line"]');
        if (!buttonElement) {
            // Button element not found, skip initialization
            return;
        }
        
        // Only call super if we're in the proper context
        super.setup(...arguments);
    }
});
