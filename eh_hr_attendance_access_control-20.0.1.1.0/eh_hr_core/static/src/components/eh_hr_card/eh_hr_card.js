/** @odoo-module **/
/**
 * <HrCard> - the platform's base card primitive.
 *
 * Every dashboard tile, drawer, list-detail panel and form section in the
 * EH HR Platform composes <HrCard> rather than re-implementing markup.
 *
 * Owl 3 ignores a class level prop defaults attribute and throws when it
 * finds one, so the schema below carries both the types and the defaults.
 */
import { Component, t, useProps } from "@odoo/owl";

export class HrCard extends Component {
    static template = "eh_hr_core.HrCard";
    props = useProps({
        tone: t.string().optional("default"),
        compact: t.boolean().optional(false),
        loading: t.boolean().optional(false),
        slots: t.object().optional(),
    });

    get toneClass() {
        return `o_hrp_card o_hrp_card--${this.props.tone}` +
               (this.props.compact ? " o_hrp_card--compact" : "");
    }
}
