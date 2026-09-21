/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Hudson Accounting Enhancements - Accounting Dashboard 3-Column Layout & Overflow Fixes
 * 
 * Ensures the Odoo 19 Accounting Dashboard renders 3 cards per row (like Enterprise)
 * and ensures onboarding/expense cards never overflow their content.
 */

function formatAccountingDashboard() {
    // Find accounting kanban view
    const kanbanViews = document.querySelectorAll(".o_kanban_view");
    
    kanbanViews.forEach((view) => {
        // Check if this is the Accounting Dashboard (has .o_account_kanban, .hudson_accounting_dashboard, or contains journal dashboard elements)
        const isAccountDashboard = 
            view.classList.contains("o_account_kanban") ||
            view.classList.contains("hudson_accounting_dashboard") ||
            view.querySelector(".o_dashboard_graph") !== null ||
            (view.closest(".o_action") && view.closest(".o_action").dataset.actionName === "Dashboard");

        if (!isAccountDashboard) {
            return;
        }

        // Add helper class
        view.classList.add("hudson_accounting_dashboard");

        // Find the kanban renderer
        const renderer = view.querySelector(".o_kanban_renderer");
        if (renderer) {
            renderer.classList.add("hudson_acc_renderer_3col");
            
            // Apply 3-column grid layout directly via inline style for guaranteed enforcement
            const width = window.innerWidth;
            let colCount = 3;
            if (width < 768) {
                colCount = 1;
            } else if (width < 1200) {
                colCount = 2;
            }

            renderer.style.setProperty("display", "grid", "important");
            renderer.style.setProperty("grid-template-columns", `repeat(${colCount}, minmax(0, 1fr))`, "important");
            renderer.style.setProperty("gap", "16px", "important");
            renderer.style.setProperty("width", "100%", "important");
            renderer.style.setProperty("box-sizing", "border-box", "important");

            // Format child records
            const records = renderer.querySelectorAll(":scope > .o_kanban_record");
            records.forEach((record) => {
                record.style.setProperty("width", "100%", "important");
                record.style.setProperty("max-width", "100%", "important");
                record.style.setProperty("min-width", "0", "important");
                record.style.setProperty("flex", "none", "important");
                record.style.setProperty("margin", "0", "important");
                record.style.setProperty("height", "auto", "important");
                record.style.setProperty("min-height", "fit-content", "important");
                record.style.setProperty("overflow", "visible", "important");

                // Fix inner card body and illustrations in Expense / Onboarding cards
                const cardBodies = record.querySelectorAll(".o_kanban_record_body, .o_kanban_card_content");
                cardBodies.forEach((body) => {
                    body.style.setProperty("height", "auto", "important");
                    body.style.setProperty("min-height", "auto", "important");
                    body.style.setProperty("overflow", "visible", "important");
                });

                const svgsAndImgs = record.querySelectorAll("svg, img");
                svgsAndImgs.forEach((img) => {
                    img.style.setProperty("max-height", "55px", "important");
                    img.style.setProperty("width", "auto", "important");
                });
            });
        }
    });
}

// Service that registers on webclient start and on resize / mutations
const accountDashboardLayoutService = {
    dependencies: [],
    start() {
        // Initial delayed checks
        setTimeout(formatAccountingDashboard, 300);
        setTimeout(formatAccountingDashboard, 1000);
        setTimeout(formatAccountingDashboard, 2000);

        // Resize listener
        window.addEventListener("resize", () => {
            formatAccountingDashboard();
        });

        // MutationObserver to catch view renders / tab switches / filter changes
        const observer = new MutationObserver((mutations) => {
            const hasNewNodes = mutations.some((m) => m.addedNodes.length > 0);
            if (hasNewNodes) {
                clearTimeout(accountDashboardLayoutService._debounce);
                accountDashboardLayoutService._debounce = setTimeout(formatAccountingDashboard, 80);
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        return {};
    },
    _debounce: null,
};

registry.category("services").add("hudson_account_dashboard_layout", accountDashboardLayoutService);
