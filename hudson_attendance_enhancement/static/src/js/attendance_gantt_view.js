/** @odoo-module **/

import { registry } from "@web/core/registry";
import { AttendanceGanttArchParser } from "./attendance_gantt_arch_parser";
import { AttendanceGanttController } from "./attendance_gantt_controller";
import { AttendanceGanttModel } from "./attendance_gantt_model";
import { AttendanceGanttRenderer } from "./attendance_gantt_renderer";

export const attendanceGanttView = {
    type: "gantt",
    display_name: "Gantt",
    icon: "view_timeline",
    multiRecord: true,
    searchMenuTypes: ["filter", "favorite"],

    ArchParser: AttendanceGanttArchParser,
    Controller: AttendanceGanttController,
    Model: AttendanceGanttModel,
    Renderer: AttendanceGanttRenderer,

    props: (genericProps, view) => {
        const { ArchParser, Model, Renderer } = view;
        const { arch, relatedModels, resModel } = genericProps;
        return {
            ...genericProps,
            archInfo: new ArchParser().parse(arch, relatedModels, resModel),
            Model,
            Renderer,
        };
    },
};

registry.category("views").add("gantt", attendanceGanttView);
