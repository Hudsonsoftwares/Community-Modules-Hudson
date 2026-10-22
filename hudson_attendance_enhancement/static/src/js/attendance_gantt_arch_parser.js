/** @odoo-module **/

import { getActiveActions } from "@web/views/utils";

export class AttendanceGanttArchParser {
    parse(xmlDoc) {
        const archInfo = {
            activeActions: getActiveActions(xmlDoc),
            dateStart: xmlDoc.getAttribute("date_start") || "check_in",
            dateStop: xmlDoc.getAttribute("date_stop") || "check_out",
            defaultScale: xmlDoc.getAttribute("default_scale") || "day",
            scales: (xmlDoc.getAttribute("scales") || "day,week,month").split(","),
            defaultGroupBy: xmlDoc.getAttribute("default_group_by") || "employee_id",
            xmlDoc,
        };
        return archInfo;
    }
}
