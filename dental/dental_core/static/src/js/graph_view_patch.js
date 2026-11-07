/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { GraphRenderer } from "@web/views/graph/graph_renderer";

patch(GraphRenderer.prototype, {
    getScaleOptions() {
        const scales = super.getScaleOptions(...arguments);
        if (scales && scales.x) {
            scales.x.ticks = scales.x.ticks || {};
            // High-contrast, sharp dark color for bottom X-axis labels (Gender, Doctors, Months, etc.)
            scales.x.ticks.color = "#1e293b";
            scales.x.ticks.font = {
                size: 13,
                weight: "bold",
                family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
            };
            scales.x.grid = scales.x.grid || {};
            scales.x.grid.color = "rgba(0, 0, 0, 0.06)";
        }
        if (scales && scales.y) {
            scales.y.ticks = scales.y.ticks || {};
            // High-contrast, sharp dark color for Y-axis scale numbers
            scales.y.ticks.color = "#334155";
            scales.y.ticks.font = {
                size: 12,
                weight: "bold",
                family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
            };
            if (scales.y.title) {
                scales.y.title.color = "#0f172a";
                scales.y.title.font = {
                    size: 13,
                    weight: "bold",
                };
            }
            scales.y.grid = scales.y.grid || {};
            scales.y.grid.color = "rgba(0, 0, 0, 0.08)";
        }
        return scales;
    },

    getLegendOptions() {
        const legend = super.getLegendOptions(...arguments);
        if (legend) {
            legend.labels = legend.labels || {};
            legend.labels.color = "#1e293b";
            legend.labels.font = {
                size: 13,
                weight: "bold",
            };
        }
        return legend;
    },
});
