/** @odoo-module **/

import { loadBundle } from "@web/core/assets";

// Ensure Chart.js is loaded and globally available immediately
if (typeof window !== "undefined") {
    if (!window.Chart && typeof globalThis !== "undefined" && globalThis.Chart) {
        window.Chart = globalThis.Chart;
    }
}

// Preemptively ensure web.chartjs_lib is loaded
try {
    loadBundle("web.chartjs_lib").then(() => {
        if (typeof window !== "undefined") {
            if (!window.Chart && typeof globalThis !== "undefined" && globalThis.Chart) {
                window.Chart = globalThis.Chart;
            }
        }
    }).catch(() => {});
} catch (_) {}

