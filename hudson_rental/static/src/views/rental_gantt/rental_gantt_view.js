import { registry } from "@web/core/registry";
import { RentalGanttController } from "./rental_gantt_controller";
import { RentalGanttModel } from "./rental_gantt_model";

/**
 * <gantt js_class="rental_gantt" default_scale="week" scales="day,week,month,year"
 *        default_group_by="product_id"/>
 * Registered under its own key: other modules may register their own "gantt" view.
 */
export class RentalGanttArchParser {
    parse(xmlDoc) {
        const scales = (xmlDoc.getAttribute("scales") || "day,week,month,year").split(",");
        const defaultScale = xmlDoc.getAttribute("default_scale") || "week";
        return {
            scales,
            defaultScale: scales.includes(defaultScale) ? defaultScale : scales[0],
            defaultGroupBy: xmlDoc.getAttribute("default_group_by") || "product_id",
        };
    }
}

export const rentalGanttView = {
    type: "gantt",
    searchMenuTypes: ["filter", "groupBy", "favorite"],
    ArchParser: RentalGanttArchParser,
    Controller: RentalGanttController,
    Model: RentalGanttModel,
    props: (genericProps, view) => ({
        ...genericProps,
        Model: view.Model,
        archInfo: new view.ArchParser().parse(genericProps.arch),
    }),
};

registry.category("views").add("rental_gantt", rentalGanttView);
