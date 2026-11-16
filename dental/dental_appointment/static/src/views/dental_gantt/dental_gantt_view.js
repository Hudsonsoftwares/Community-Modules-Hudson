// Dental Gantt view (planning board) - one row per doctor
import { registry } from "@web/core/registry";
import { DentalGanttController } from "./dental_gantt_controller";

const SCALES = ["day", "week", "month"];

function parseBool(value, defaultValue) {
    if (value === null || value === undefined) {
        return defaultValue;
    }
    return !["0", "false", "False"].includes(value);
}

function parseHour(value, defaultValue) {
    const hour = parseFloat(value);
    return Number.isFinite(hour) ? Math.min(Math.max(hour, 0), 24) : defaultValue;
}

/**
 * Reads the <dental_gantt> arch:
 *   <dental_gantt date_start="date_start" date_stop="date_end" resource_field="doctor_id"
 *                 color_field="state" default_scale="week" day_start_hour="8" day_end_hour="20"
 *                 draggable_states="pending,confirmed">
 *       <field name="patient_id"/>   (first field = bar label, all fields = bar tooltip)
 *   </dental_gantt>
 */
export function parseDentalGanttArch(arch) {
    const root =
        typeof arch === "string"
            ? new DOMParser().parseFromString(arch, "text/xml").documentElement
            : arch;
    const attr = (name) => root.getAttribute(name);
    const defaultScale = attr("default_scale");
    let dayStartHour = parseHour(attr("day_start_hour"), 8);
    let dayEndHour = parseHour(attr("day_end_hour"), 20);
    if (dayEndHour <= dayStartHour) {
        [dayStartHour, dayEndHour] = [0, 24];
    }
    const draggableStates = attr("draggable_states");
    return {
        dateStart: attr("date_start"),
        dateStop: attr("date_stop"),
        resourceField: attr("resource_field"),
        colorField: attr("color_field") || false,
        defaultScale: SCALES.includes(defaultScale) ? defaultScale : "week",
        dayStartHour,
        dayEndHour,
        draggableStates: draggableStates ? draggableStates.split(",").map((s) => s.trim()) : null,
        canCreate: parseBool(attr("create"), true),
        canEdit: parseBool(attr("edit"), true),
        fieldNames: [...root.querySelectorAll(":scope > field")].map((f) => f.getAttribute("name")),
    };
}

export const dentalGanttView = {
    type: "dental_gantt",
    searchMenuTypes: ["filter", "favorite"],
    Controller: DentalGanttController,
    props: (genericProps) => ({
        ...genericProps,
        archInfo: parseDentalGanttArch(genericProps.arch),
    }),
};

registry.category("views").add("dental_gantt", dentalGanttView);
