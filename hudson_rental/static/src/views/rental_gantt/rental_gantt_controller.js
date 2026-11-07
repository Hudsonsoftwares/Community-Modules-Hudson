import { Component, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { serializeDateTime } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";
import { useModel } from "@web/model/model";
import { useSetupAction } from "@web/search/action_hook";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { standardViewProps } from "@web/views/standard_view_props";
import { ViewScaleSelector } from "@web/views/view_components/view_scale_selector";

const { DateTime } = luxon;

export const SCALE_LABELS = {
    day: _t("Day"),
    week: _t("Week"),
    month: _t("Month"),
    year: _t("Year"),
};

// Colour of each schedule status (see sale.order.line rental_gantt_status)
export const STATUS_LEGEND = [
    { key: "quotation", label: _t("Quotation") },
    { key: "reserved", label: _t("Reserved") },
    { key: "late_pickup", label: _t("Late Pickup") },
    { key: "early_pickup", label: _t("Early Pickup") },
    { key: "picked_up", label: _t("Picked-up") },
    { key: "late_return", label: _t("Late Return") },
    { key: "returned", label: _t("Returned") },
    { key: "returned_late", label: _t("Returned Late") },
];

/**
 * Rental schedule: one row per product (or per value of the chosen grouping), with the
 * rentals drawn as pills on a timeline coloured by their pickup / return status.
 */
export class RentalGanttController extends Component {
    static template = "hudson_rental.RentalGanttController";
    static components = { Layout, SearchBar, CogMenu, ViewScaleSelector };
    props = useProps({
        ...standardViewProps,
        Model: t.function(),
        archInfo: t.object(),
    });

    setup() {
        this.action = useService("action");
        this.searchBarToggler = useSearchBarToggler();
        this.state = proxy({ isFullscreen: false });
        // Columns being selected by dragging in a row
        this.selection = proxy({ rowKey: null, from: 0, to: 0 });
        onWillUnmount(() => this._stopSelecting());
        this.model = useModel(this.props.Model, {
            resModel: this.props.resModel,
            fields: this.props.fields,
            archInfo: this.props.archInfo,
            state: this.props.state,
        });
        useSetupAction({ getLocalState: () => this.model.exportedState });
        this.legend = STATUS_LEGEND;
    }

    get scales() {
        return Object.fromEntries(this.props.archInfo.scales.map((s) => [s, { description: SCALE_LABELS[s] }]));
    }

    get statusLabels() {
        return Object.fromEntries(STATUS_LEGEND.map((s) => [s.key, s.label]));
    }

    setScale(scale) {
        return this.model.setScale(scale);
    }

    move(direction) {
        return this.model.move(direction);
    }

    rowHeight(row) {
        return `height: ${Math.max(row.laneCount, 1) * 26 + 14}px;`;
    }

    pillStyle(pill) {
        return `left: ${pill.left}%; width: ${pill.width}%; top: ${pill.lane * 26 + 7}px;`;
    }

    gridStyle() {
        return `grid-template-columns: repeat(${this.model.columns.length}, minmax(${this.minColumnWidth}px, 1fr));`;
    }

    get minColumnWidth() {
        return { day: 48, week: 110, month: 34, year: 70 }[this.model.scale] || 40;
    }

    pillTitle(pill) {
        const format = (date) => date.toLocaleString(DateTime.DATETIME_MED);
        const record = pill.record;
        const lines = [
            record.order_id && record.order_id[1],
            record.order_partner_id && record.order_partner_id[1],
            record.product_id && `${record.product_id[1]} × ${record.product_uom_qty}`,
            `${format(pill.start)} → ${format(pill.stop)}`,
            this.statusLabels[pill.status],
        ];
        return lines.filter(Boolean).join("\n");
    }

    openOrder(pill) {
        const orderId = pill.record.order_id && pill.record.order_id[0];
        if (!orderId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: orderId,
            views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------------
    // Selecting a period: press on an empty spot of a row and drag over the
    // columns to rent (a simple click selects one column), like Odoo's Gantt.
    // ------------------------------------------------------------------

    _columnIndex(cellsEl, clientX) {
        const rect = cellsEl.getBoundingClientRect();
        const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 0.9999);
        return Math.floor(ratio * this.model.columns.length);
    }

    onCellsPointerDown(row, ev) {
        if (ev.button !== 0 || ev.target.closest(".o_rental_gantt_pill")) {
            return;
        }
        ev.preventDefault();
        const cellsEl = ev.currentTarget;
        const index = this._columnIndex(cellsEl, ev.clientX);
        Object.assign(this.selection, { rowKey: row.key, from: index, to: index });
        const onMove = (moveEv) => {
            this.selection.to = this._columnIndex(cellsEl, moveEv.clientX);
        };
        const onUp = () => {
            this._stopSelecting();
            const from = Math.min(this.selection.from, this.selection.to);
            const to = Math.max(this.selection.from, this.selection.to);
            this.selection.rowKey = null;
            this.createFromColumns(row, from, to);
        };
        const onCancel = () => {
            this._stopSelecting();
            this.selection.rowKey = null;
        };
        const onKey = (keyEv) => keyEv.key === "Escape" && onCancel();
        this._listeners = [
            ["pointermove", onMove],
            ["pointerup", onUp],
            ["pointercancel", onCancel],
            ["keydown", onKey],
        ];
        for (const [type, handler] of this._listeners) {
            window.addEventListener(type, handler);
        }
    }

    _stopSelecting() {
        for (const [type, handler] of this._listeners || []) {
            window.removeEventListener(type, handler);
        }
        this._listeners = [];
    }

    selectionStyle(row) {
        const count = this.model.columns.length;
        const from = Math.min(this.selection.from, this.selection.to);
        const to = Math.max(this.selection.from, this.selection.to);
        return `left: ${(from / count) * 100}%; width: ${((to - from + 1) / count) * 100}%;`;
    }

    /**
     * Rental period of the selected columns: from the start of the first one to the end of
     * the last one. Daily and longer products use their pickup / return times instead
     * (e.g. Mon 8:00 -> Wed 18:00) when the hourly scale isn't shown.
     */
    _selectedPeriod(row, from, to) {
        let pickup = this.model.columnStart(from);
        let returnDate = this.model.columnStart(to + 1);
        if (row.times && this.model.scale !== "day") {
            const at = (date, time) => {
                const minutes = Math.round(time * 60);
                return date.set({ hour: Math.floor(minutes / 60), minute: minutes % 60, second: 0 });
            };
            const timedPickup = at(pickup, row.times.pickup);
            const timedReturn = at(returnDate.minus({ days: 1 }), row.times.return);
            if (timedReturn > timedPickup) {
                pickup = timedPickup;
                returnDate = timedReturn;
            }
        }
        return { pickup, returnDate };
    }

    createFromColumns(row, from, to) {
        const { pickup, returnDate } = this._selectedPeriod(row, from, to);
        const context = {
            default_rental_start_date: serializeDateTime(pickup),
            default_rental_end_date: serializeDateTime(returnDate),
        };
        if (this.model.groupField === "product_id" && row.key) {
            context.default_order_line = [[0, 0, { product_id: row.key, product_uom_qty: 1 }]];
        } else if (this.model.groupField === "order_partner_id" && row.key) {
            context.default_partner_id = row.key;
        }
        this.createOrder(context);
    }

    createOrder(context = {}) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            views: [[false, "form"]],
            context,
        });
    }
}
