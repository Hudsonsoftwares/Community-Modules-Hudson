/** @odoo-module **/
/**
 * <HrStat> - one headline number with an optional unit and delta badge.
 *
 * Owl 3 ignores a class level prop defaults attribute and throws when it
 * finds one, so the schema below carries both the types and the defaults.
 */
import { Component, t, useProps } from "@odoo/owl";

export class HrStat extends Component {
    static template = "eh_hr_core.HrStat";
    props = useProps({
        label: t.string(),
        value: t.or([t.string(), t.number()]),
        unit: t.string().optional(),
        delta: t.number().optional(),
        tone: t.string().optional("neutral"),
    });

    get deltaSign() {
        if (this.props.delta === undefined || this.props.delta === 0) return "";
        return this.props.delta > 0 ? "▲" : "▼";
    }
    get deltaClass() {
        if (this.props.delta === undefined) return "";
        if (this.props.delta > 0) return "o_hrp_stat__delta--up";
        if (this.props.delta < 0) return "o_hrp_stat__delta--down";
        return "";
    }
}
