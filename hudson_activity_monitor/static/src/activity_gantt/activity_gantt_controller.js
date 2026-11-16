/** @odoo-module **/

import { Component, signal, t, useProps } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { useModel } from "@web/model/model";
import { useService } from "@web/core/utils/hooks";
import { standardViewProps } from "@web/views/standard_view_props";
import { formatHours } from "./activity_gantt_model";

export class ActivityGanttController extends Component {
    static template = "hudson_activity_monitor.ActivityGantt";
    static components = { Layout, SearchBar, CogMenu };
    props = useProps({
        ...standardViewProps,
        Model: t.function(),
        archInfo: t.object(),
    });

    setup() {
        this.rootRef = signal.ref();
        this.action = useService("action");
        this.searchBarToggler = useSearchBarToggler();
        this.model = useModel(this.props.Model, {
            resModel: this.props.resModel,
            archInfo: this.props.archInfo,
            context: this.props.context,
        });
        // useModel re-renders this component on model.notify() (OWL 3 has no this.render()).
    }

    fmt(hours) {
        return formatHours(hours);
    }

    segmentClass(seg) {
        let color = `o_ag_state_${seg.state}`;
        if (this.model.colorBy === "category" && seg.state === "active") {
            color = `o_ag_cat_${seg.category || "neutral"}`;
        }
        return `o_ag_segment ${color}${seg.live ? " o_ag_live" : ""}`;
    }

    _range(start, end) {
        return [
            ["date_end", ">", start.toUTC().toFormat("yyyy-MM-dd HH:mm:ss")],
            ["date_start", "<", end.toUTC().toFormat("yyyy-MM-dd HH:mm:ss")],
        ];
    }

    /** Click on a bar: the record itself, or the list of merged records. */
    openSegment(row, seg) {
        if (seg.count === 1) {
            this.action.doAction({
                type: "ir.actions.act_window",
                name: `${row.name} - ${seg.state === "active" ? seg.app || "Unknown" : seg.state}`,
                res_model: this.props.resModel,
                res_id: seg.id,
                views: [[false, "form"]],
                target: "new",
            });
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${row.name} - ${seg.startDt.toFormat("HH:mm")} to ${seg.endDt.toFormat("HH:mm")}`,
            res_model: this.props.resModel,
            views: [[false, "list"], [false, "form"]],
            domain: [["employee_id", "=", row.id], ...this._range(seg.startDt, seg.endDt)],
            target: "new",
        });
    }

    /** Click on an employee: their activity for the visible period. */
    openEmployee(row) {
        const { start, end } = this.model.bounds;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${row.name} - ${this.model.title}`,
            res_model: this.props.resModel,
            views: [[false, "list"], [false, "pivot"], [false, "graph"], [false, "form"]],
            domain: [["employee_id", "=", row.id], ...this._range(start, end)],
        });
    }
}
