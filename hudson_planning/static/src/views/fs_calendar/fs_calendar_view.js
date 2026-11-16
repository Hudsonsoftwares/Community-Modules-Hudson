/** @odoo-module **/
// Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import { serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { CalendarModel } from "@web/views/calendar/calendar_model";
import { calendarView } from "@web/views/calendar/calendar_view";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

const SLOT_MODEL = "fs.planning.slot";

/**
 * Calendar of the shifts with the "to schedule" section of the side panel
 * (``schedule="1"``) filled like the schedule's side panel: the hours of the
 * sales orders and the field service jobs without dates. Dropped on a day
 * or an hour, an item is planned from there (its hours of working time) as an
 * open shift, opened to assign it.
 *
 * Items that are not shifts (e.g. field service jobs) get a negative id in the
 * section, the draggable items carrying only an id.
 */
export class FsCalendarModel extends CalendarModel {
    async fetchEventsToSchedule(params) {
        const { data } = params;
        const items = await this.orm.call(SLOT_MODEL, "get_calendar_to_schedule", [
            serializeDateTime(data.range.start),
            serializeDateTime(data.range.end),
        ], { context: this.meta.context });
        this.toScheduleRefs = {};
        const records = items.map((item, index) => {
            const [model, resId] = item.ref.split(",");
            const id = model === SLOT_MODEL ? parseInt(resId) : -(index + 1);
            this.toScheduleRefs[id] = item.ref;
            return { id, display_name: item.name, ref: item.ref, hours: item.hours };
        });
        data.eventsToSchedule = { length: records.length, records };
    }

    async loadMoreEventsToSchedule() {
        // All the work to schedule is loaded at once.
    }

    async scheduleEvent(eventId, date) {
        const ref = (this.toScheduleRefs || {})[eventId] || `${SLOT_MODEL},${eventId}`;
        // Month view: the day, from its first working hour
        const start = this.hasTimePrecision ? date : date.startOf("day");
        let slotId = false;
        try {
            slotId = await this.orm.call(SLOT_MODEL, "action_plan_from_calendar", [ref, serializeDateTime(start)], {
                context: this.meta.context,
            });
        } finally {
            await this.load();
        }
        if (slotId) {
            this.bus.trigger("FS_CALENDAR_PLANNED", { slotId });
        }
    }

    async unscheduleEvent(eventId) {
        try {
            await this.orm.call(SLOT_MODEL, "action_unschedule_from_calendar", [[eventId]], {
                context: this.meta.context,
            });
        } finally {
            await this.load();
        }
    }
}

export class FsCalendarController extends CalendarController {
    setup() {
        super.setup();
        // The planned shift is opened to assign it to an employee.
        useBus(this.model.bus, "FS_CALENDAR_PLANNED", ({ detail }) => {
            const record = this.model.records[detail.slotId];
            if (record && record.rawRecord.resource_id) {
                return;
            }
            this.displayDialog(FormViewDialog, {
                resModel: SLOT_MODEL,
                resId: detail.slotId,
                context: this.props.context,
                title: _t("Assign the shift"),
                viewId: this.model.formViewId,
                onRecordSaved: () => this.model.load(),
            });
        });
    }

    /** A job of the "to schedule" section (negative id) opens its own form. */
    async editRecord(record, context = {}) {
        if (record.id < 0) {
            const ref = (this.model.toScheduleRefs || {})[record.id];
            if (!ref) {
                return;
            }
            const [resModel, resId] = ref.split(",");
            this.displayDialog(FormViewDialog, {
                resModel,
                resId: parseInt(resId),
                title: record.title || record.display_name,
                onRecordSaved: () => this.model.load(),
            });
            return;
        }
        return super.editRecord(record, context);
    }
}

export const fsCalendarView = {
    ...calendarView,
    Controller: FsCalendarController,
    Model: FsCalendarModel,
};

registry.category("views").add("fs_calendar", fsCalendarView);
