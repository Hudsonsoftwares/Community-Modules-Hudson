/** @odoo-module **/

import { registry } from "@web/core/registry";
import { EventBus } from "@odoo/owl";

/**
 * Barcode Reader Service
 * 
 * Simulates the real Odoo barcode service.
 * Listens to keydown events to detect wedge scanners (rapid key presses ending in Enter)
 * and exposes an interface for camera fallback.
 */
export const barcodeReaderService = {
    dependencies: [],
    start(env) {
        const bus = new EventBus();
        let barcodeBuffer = "";
        let scanTimer = null;
        
        // KeyWedge detection configuration
        const KEY_WEDGE_DELAY = 50; 
        
        const onKeydown = (ev) => {
            // Ignore events from input fields unless it's Enter and we have a buffer
            if (['INPUT', 'TEXTAREA'].includes(ev.target.tagName)) {
                return;
            }

            if (ev.key === 'Enter') {
                if (barcodeBuffer) {
                    bus.trigger("barcode_scanned", { barcode: barcodeBuffer });
                    barcodeBuffer = "";
                }
                return;
            }
            
            // Build buffer
            if (ev.key.length === 1) { // Ignore modifier keys like Shift
                barcodeBuffer += ev.key;
                
                // Clear buffer if typing is too slow
                clearTimeout(scanTimer);
                scanTimer = setTimeout(() => {
                    barcodeBuffer = "";
                }, KEY_WEDGE_DELAY);
            }
        };

        document.addEventListener('keydown', onKeydown);
        
        return {
            bus,
            addEventListener: bus.addEventListener.bind(bus),
            removeEventListener: bus.removeEventListener.bind(bus),
            
            // Simulate a camera scan for manual testing or mobile fallback
            scanCameraFallback() {
                // In a full implementation, this would open a ZXing UI
                const result = prompt("Manual Barcode Entry (Camera simulation):");
                if (result) {
                    bus.trigger("barcode_scanned", { barcode: result });
                }
            }
        };
    }
};

registry.category("services").add("barcode_reader_service", barcodeReaderService);
