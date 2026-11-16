import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/core/popover/popover_hook";
import { Component, t, useProps } from "@odoo/owl";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Pharmacy availability of a prescribed medicine, shown like the forecast icon of sales order
 * lines: a chart icon coloured by stock status, with a popover giving on hand / free / forecasted
 * quantities of the branch pharmacy and a link to the inventory forecast report.
 */
export class RxStockPopover extends Component {
    static template = "dental_pharmacy.RxStockPopover";
    props = useProps({
        record: t.object(),
        close: t.function(),
    });

    setup() {
        this.actionService = useService("action");
    }

    get data() {
        return this.props.record.data;
    }

    get uomName() {
        return (this.data.uom_id && this.data.uom_id.display_name) || "";
    }

    get needed() {
        return Math.max((this.data.quantity || 0) - (this.data.dispensed_qty || 0), 0);
    }

    format(value) {
        return Number.isInteger(value) ? String(value) : (value || 0).toFixed(2);
    }

    openForecast() {
        this.props.close();
        this.actionService.doAction("stock.stock_forecasted_product_product_action", {
            additionalContext: {
                active_model: "product.product",
                active_id: this.data.medicine_id.id,
                warehouse_id: this.data.stock_warehouse_id && this.data.stock_warehouse_id.id,
            },
        });
    }
}

export class RxStockWidget extends Component {
    static components = { Popover: RxStockPopover };
    static template = "dental_pharmacy.RxStock";
    props = useProps(standardWidgetProps);

    setup() {
        this.popover = usePopover(this.constructor.components.Popover, { position: "top" });
    }

    get data() {
        return this.props.record.data;
    }

    get visible() {
        return Boolean(this.data.medicine_id && this.data.stock_alert);
    }

    get colorClass() {
        return {
            ok: "text-success",
            low: "text-warning",
            insufficient: "text-warning",
            out: "text-danger",
        }[this.data.stock_alert] || "";
    }

    showPopup(ev) {
        this.popover.open(ev.currentTarget, { record: this.props.record });
    }
}

export const rxStockWidget = {
    component: RxStockWidget,
    fieldDependencies: [
        { name: "medicine_id", type: "many2one" },
        { name: "quantity", type: "float" },
        { name: "dispensed_qty", type: "float" },
        { name: "uom_id", type: "many2one" },
        { name: "stock_alert", type: "selection" },
        { name: "stock_alert_note", type: "char" },
        { name: "stock_on_hand", type: "float" },
        { name: "stock_free_qty", type: "float" },
        { name: "stock_forecast_qty", type: "float" },
        { name: "stock_warehouse_id", type: "many2one" },
        { name: "stock_forecast_access", type: "boolean" },
    ],
};
registry.category("view_widgets").add("dental_rx_stock", rxStockWidget);
