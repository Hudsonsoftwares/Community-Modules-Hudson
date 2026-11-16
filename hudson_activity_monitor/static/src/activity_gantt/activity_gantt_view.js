/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ActivityGanttController } from "./activity_gantt_controller";
import { ActivityGanttModel } from "./activity_gantt_model";

function parseArch(arch) {
    const scale = arch.getAttribute("default_scale");
    return { defaultScale: scale === "week" ? "week" : "day" };
}

export const activityGanttView = {
    type: "gantt",
    display_name: "Timeline",
    icon: "view_timeline",
    multiRecord: true,
    searchMenuTypes: ["filter", "favorite"],
    Controller: ActivityGanttController,
    Model: ActivityGanttModel,
    props: (genericProps, view) => ({
        ...genericProps,
        Model: view.Model,
        archInfo: parseArch(genericProps.arch),
    }),
};

// Only our own js_class: hudson_attendance_enhancement already registers "gantt".
registry.category("views").add("activity_gantt", activityGanttView);
