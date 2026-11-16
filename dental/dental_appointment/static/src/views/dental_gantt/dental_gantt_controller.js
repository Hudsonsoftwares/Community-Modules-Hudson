import { Component, onWillStart, onWillUpdateProps, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { user } from "@web/core/user";
import { KeepLast } from "@web/core/utils/concurrency";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { standardViewProps } from "@web/views/standard_view_props";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

const { DateTime } = luxon;

const SNAP_MINUTES = 15;
const DEFAULT_DURATION_MINUTES = 30;
const LANE_HEIGHT = 30; // px, keep in sync with $o-dg-lane-height
const ROW_PADDING = 8; // px
const DRAG_THRESHOLD = 5; // px
const UNASSIGNED_ROW_ID = 0;

export const SCALE_LABELS = {
    day: _t("Day"),
    week: _t("Week"),
    month: _t("Month"),
};

function m2o(value) {
    if (!value) {
        return null;
    }
    if (Array.isArray(value)) {
        return { id: value[0], name: value[1] };
    }
    return { id: value.id, name: value.display_name };
}

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

/**
 * Gantt-style planning board: one row per doctor (resource), appointments drawn as bars
 * on a day / week / month timeline. Bars open the record on click and can be dragged
 * to another time or doctor to reschedule.
 */
export class DentalGanttController extends Component {
    static template = "dental_appointment.DentalGanttView";
    static components = { Layout, SearchBar, CogMenu };

    props = useProps({
        ...standardViewProps,
        archInfo: t.object(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.addDialog = useOwnedDialogs();
        this.searchBarToggler = useSearchBarToggler();
        this.keepLast = new KeepLast();
        this.scaleLabels = SCALE_LABELS;
        this.scales = Object.keys(SCALE_LABELS);
        this.myDoctors = [];
        this.myDoctorIds = [];

        const saved = this.props.state?.ganttState || {};
        this.state = proxy({
            scale: saved.scale || this.props.archInfo.defaultScale,
            focusDate: saved.focusDate || DateTime.now().toISODate(),
            onlyMine: saved.onlyMine, // decided on first load when unknown
            hideEmpty: saved.hideEmpty ?? false,
            records: [],
            resources: [],
            drag: null,
        });

        useSetupAction({
            getLocalState: () => ({
                ganttState: {
                    scale: this.state.scale,
                    focusDate: this.state.focusDate,
                    onlyMine: this.state.onlyMine,
                    hideEmpty: this.state.hideEmpty,
                },
            }),
        });

        onWillStart(async () => {
            const myDoctors = await this.orm.searchRead(
                "hr.employee.public",
                [["user_id", "=", user.userId], ["is_dentist", "=", true]],
                ["id", "display_name"]
            );
            this.myDoctors = myDoctors.map((d) => ({ id: d.id, name: d.display_name }));
            this.myDoctorIds = this.myDoctors.map((d) => d.id);
            if (this.state.onlyMine === undefined) {
                // Doctors land on their own schedule; front desk / managers see everyone
                this.state.onlyMine = this.myDoctorIds.length > 0;
            }
            await this.load(this.props);
        });
        onWillUpdateProps((nextProps) => this.load(nextProps));
        onWillUnmount(() => this.stopDrag?.());
    }

    // -------------------------------------------------------------------------
    // Getters
    // -------------------------------------------------------------------------

    get archInfo() {
        return this.props.archInfo;
    }

    get focusDate() {
        return DateTime.fromISO(this.state.focusDate);
    }

    /** First and last day (start of day) of the displayed period. */
    get range() {
        const focus = this.focusDate;
        const unit = this.state.scale;
        const start = focus.startOf(unit === "day" ? "day" : unit);
        const end = focus.endOf(unit === "day" ? "day" : unit).startOf("day");
        return { start, end };
    }

    get days() {
        const key = `${this.state.scale}|${this.state.focusDate}`;
        if (this._daysCache?.key !== key) {
            const { start, end } = this.range;
            const days = [];
            for (let d = start; d <= end; d = d.plus({ days: 1 })) {
                days.push(d);
            }
            this._daysCache = { key, days };
        }
        return this._daysCache.days;
    }

    get hours() {
        const { dayStartHour, dayEndHour } = this.archInfo;
        const hours = [];
        for (let h = Math.floor(dayStartHour); h < dayEndHour; h++) {
            hours.push(h);
        }
        return hours;
    }

    get title() {
        const { start, end } = this.range;
        switch (this.state.scale) {
            case "day":
                return start.toFormat("cccc, d LLLL yyyy");
            case "week":
                return start.month === end.month
                    ? `${start.toFormat("d")} – ${end.toFormat("d LLL yyyy")}`
                    : `${start.toFormat("d LLL")} – ${end.toFormat("d LLL yyyy")}`;
            default:
                return start.toFormat("LLLL yyyy");
        }
    }

    /** Header cells: hours for the day scale, days otherwise. */
    get columns() {
        const today = DateTime.now().toISODate();
        if (this.state.scale === "day") {
            return this.hours.map((h) => ({
                key: `h${h}`,
                label: `${String(h).padStart(2, "0")}:00`,
                sublabel: "",
                isToday: false,
                isWeekend: false,
            }));
        }
        const isWeek = this.state.scale === "week";
        return this.days.map((d) => ({
            key: d.toISODate(),
            label: isWeek ? d.toFormat("ccc") : d.toFormat("d"),
            sublabel: isWeek ? d.toFormat("d LLL") : d.toFormat("ccccc"),
            isToday: d.toISODate() === today,
            isWeekend: d.weekday > 5,
            date: d,
        }));
    }

    /** Position (in %) of the "now" marker, or null when now is not displayed. */
    get nowPosition() {
        if (this.isCellMode) {
            return null;
        }
        const now = DateTime.now();
        const { start, end } = this.range;
        if (now < start || now >= end.plus({ days: 1 })) {
            return null;
        }
        const { dayStartHour, dayEndHour } = this.archInfo;
        const hour = now.hour + now.minute / 60;
        if (hour < dayStartHour || hour > dayEndHour) {
            return null;
        }
        return this.toFraction(now) * 100;
    }

    /**
     * Week / month: like a planning board, appointments fill their day cell and are stacked.
     * Day: bars are proportional to the real start / end time.
     */
    get isCellMode() {
        return this.state.scale !== "day";
    }

    dayIndexOf(dt) {
        return Math.round(dt.startOf("day").diff(this.days[0], "days").days);
    }

    get canCreate() {
        return this.archInfo.canCreate;
    }

    get colorSelection() {
        const field = this.archInfo.colorField && this.props.fields[this.archInfo.colorField];
        return field?.type === "selection" ? field.selection : null;
    }

    /** Rows (one per resource) with their bars laid out in non-overlapping lanes. */
    get rows() {
        const { resourceField } = this.archInfo;
        const rowsById = new Map();
        for (const res of this.state.resources) {
            rowsById.set(res.id, { id: res.id, name: res.name, items: [], hours: 0 });
        }
        for (const rec of this.state.records) {
            const res = m2o(rec[resourceField]);
            const rowId = res ? res.id : UNASSIGNED_ROW_ID;
            if (!rowsById.has(rowId)) {
                rowsById.set(rowId, {
                    id: rowId,
                    name: res ? res.name : _t("Unassigned"),
                    items: [],
                    hours: 0,
                });
            }
            const row = rowsById.get(rowId);
            row.items.push(this.makeItem(rec));
            row.hours += (rec.end - rec.start) / 3_600_000;
        }
        let rows = [...rowsById.values()];
        if (this.state.hideEmpty) {
            rows = rows.filter((r) => r.items.length);
        }
        for (const row of rows) {
            // Greedy lane assignment so overlapping appointments are stacked, not hidden
            const laneEnds = [];
            row.items.sort((a, b) => a.x0 - b.x0 || a.start - b.start);
            for (const item of row.items) {
                const x1 = item.x0 + item.width / 100;
                let lane = laneEnds.findIndex((laneEnd) => laneEnd <= item.x0 + 1e-9);
                if (lane === -1) {
                    lane = laneEnds.length;
                    laneEnds.push(x1);
                } else {
                    laneEnds[lane] = x1;
                }
                item.lane = lane;
                item.top = ROW_PADDING / 2 + lane * LANE_HEIGHT;
            }
            row.height = Math.max(laneEnds.length, 1) * LANE_HEIGHT + ROW_PADDING;
            row.hoursLabel = row.hours ? `${Math.round(row.hours * 10) / 10}h` : "";
        }
        return rows;
    }

    // -------------------------------------------------------------------------
    // Data
    // -------------------------------------------------------------------------

    async load(props) {
        const { dateStart, dateStop, resourceField, colorField, fieldNames } = this.archInfo;
        const { start, end } = this.range;
        let domain = Domain.and([
            props.domain,
            [
                [dateStart, "<", serializeDateTime(end.plus({ days: 1 }))],
                [dateStop, ">", serializeDateTime(start)],
            ],
        ]);
        if (this.state.onlyMine) {
            domain = Domain.and([domain, [[resourceField, "in", this.myDoctorIds]]]);
        }
        const fieldsToRead = [
            ...new Set(["display_name", dateStart, dateStop, resourceField, colorField, ...fieldNames]),
        ].filter(Boolean);
        const resourceModel = props.fields[resourceField]?.relation;
        const resourceDomain =
            resourceModel === "hr.employee.public" || resourceModel === "hr.employee"
                ? [["is_dentist", "=", true]]
                : [];

        const [records, resources] = await this.keepLast.add(
            Promise.all([
                this.orm.searchRead(props.resModel, domain.toList(props.context), fieldsToRead, {
                    context: props.context,
                    order: `${dateStart} asc`,
                }),
                this.state.onlyMine || !resourceModel
                    ? Promise.resolve(null)
                    : this.orm.searchRead(resourceModel, resourceDomain, ["display_name"], {
                          order: "name",
                      }),
            ])
        );
        for (const rec of records) {
            rec.start = deserializeDateTime(rec[dateStart]).toMillis();
            rec.end = rec[dateStop]
                ? deserializeDateTime(rec[dateStop]).toMillis()
                : rec.start + DEFAULT_DURATION_MINUTES * 60_000;
        }
        this.state.records = records;
        this.state.resources = resources
            ? resources.map((r) => ({ id: r.id, name: r.display_name }))
            : this.myDoctors.map((d) => ({ ...d }));
    }

    reload() {
        return this.load(this.props);
    }

    // -------------------------------------------------------------------------
    // Time <-> position mapping (each day spans [dayStartHour, dayEndHour])
    // -------------------------------------------------------------------------

    toFraction(dt) {
        const days = this.days;
        const { dayStartHour, dayEndHour } = this.archInfo;
        const dayIndex = Math.round(dt.startOf("day").diff(days[0], "days").days);
        if (dayIndex < 0) {
            return 0;
        }
        if (dayIndex >= days.length) {
            return 1;
        }
        const hour = dt.hour + dt.minute / 60 + dt.second / 3600;
        const within = clamp((hour - dayStartHour) / (dayEndHour - dayStartHour), 0, 1);
        return (dayIndex + within) / days.length;
    }

    fromFraction(fraction) {
        const days = this.days;
        const { dayStartHour, dayEndHour } = this.archInfo;
        const pos = clamp(fraction, 0, 0.999999) * days.length;
        const dayIndex = Math.floor(pos);
        let minutes = dayStartHour * 60 + (pos - dayIndex) * (dayEndHour - dayStartHour) * 60;
        minutes = Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
        return days[dayIndex].plus({ minutes });
    }

    makeItem(rec) {
        const start = DateTime.fromMillis(rec.start);
        const end = DateTime.fromMillis(rec.end);
        let x0, x1;
        if (this.isCellMode) {
            const last = this.days.length - 1;
            const startIndex = clamp(this.dayIndexOf(start), 0, last);
            const endIndex = clamp(this.dayIndexOf(end.minus({ milliseconds: 1 })), startIndex, last);
            x0 = startIndex / this.days.length;
            x1 = (endIndex + 1) / this.days.length;
        } else {
            x0 = this.toFraction(start);
            x1 = this.toFraction(end);
        }
        const { colorField, fieldNames, draggableStates } = this.archInfo;
        const colorValue = colorField ? rec[colorField] : false;
        const timeLabel = this.isCellMode
            ? start.toFormat("HH:mm")
            : `${start.toFormat("HH:mm")} – ${end.toFormat("HH:mm")}`;
        const label = fieldNames.length
            ? this.formatValue(fieldNames[0], rec[fieldNames[0]])
            : rec.display_name;
        const tooltip = [rec.display_name, `${start.toFormat("ccc d LLL")}, ${timeLabel}`];
        for (const fname of fieldNames) {
            const value = this.formatValue(fname, rec[fname]);
            if (value) {
                tooltip.push(`${this.props.fields[fname]?.string || fname}: ${value}`);
            }
        }
        return {
            id: rec.id,
            start: rec.start,
            end: rec.end,
            x0,
            left: x0 * 100,
            width: Math.max(x1 - x0, 0.004) * 100,
            label,
            timeLabel,
            tooltip: tooltip.join("\n"),
            colorValue,
            isEmergency: Boolean(rec.is_emergency),
            hasWarning: Boolean(rec.has_leave_conflict || rec.has_equipment_conflict),
            draggable:
                this.archInfo.canEdit &&
                (!draggableStates || !colorField || draggableStates.includes(colorValue)),
        };
    }

    formatValue(fname, value) {
        const field = this.props.fields[fname];
        if (value === false || value === null || value === undefined) {
            return "";
        }
        switch (field?.type) {
            case "many2one":
                return m2o(value)?.name || "";
            case "selection":
                return field.selection.find(([key]) => key === value)?.[1] || value;
            case "boolean":
                return value ? _t("Yes") : "";
            case "datetime":
                return formatDateTime(deserializeDateTime(value));
            default:
                return String(value);
        }
    }

    // -------------------------------------------------------------------------
    // Navigation & toolbar
    // -------------------------------------------------------------------------

    async setScale(scale) {
        this.state.scale = scale;
        await this.reload();
    }

    async navigate(direction) {
        if (direction === "today") {
            this.state.focusDate = DateTime.now().toISODate();
        } else {
            const step = direction === "next" ? 1 : -1;
            this.state.focusDate = this.focusDate.plus({ [`${this.state.scale}s`]: step }).toISODate();
        }
        await this.reload();
    }

    async toggleOnlyMine() {
        this.state.onlyMine = !this.state.onlyMine;
        await this.reload();
    }

    toggleHideEmpty() {
        this.state.hideEmpty = !this.state.hideEmpty;
    }

    async openDay(column) {
        if (!column.date) {
            return;
        }
        this.state.focusDate = column.date.toISODate();
        this.state.scale = "day";
        await this.reload();
    }

    // -------------------------------------------------------------------------
    // Records
    // -------------------------------------------------------------------------

    openRecord(resId, context = {}) {
        this.addDialog(FormViewDialog, {
            resModel: this.props.resModel,
            resId: resId || false,
            context: { ...this.props.context, ...context },
            title: resId ? _t("Appointment") : _t("New Appointment"),
            onRecordSaved: () => this.reload(),
        });
    }

    createRecord(start, rowId) {
        if (!this.canCreate) {
            return;
        }
        const { dateStart, dateStop, resourceField } = this.archInfo;
        const context = {};
        if (start) {
            context[`default_${dateStart}`] = serializeDateTime(start);
            context[`default_${dateStop}`] = serializeDateTime(
                start.plus({ minutes: DEFAULT_DURATION_MINUTES })
            );
        }
        if (rowId) {
            context[`default_${resourceField}`] = rowId;
        }
        this.openRecord(false, context);
    }

    onTrackClick(ev, row) {
        if (ev.target.closest(".o_dg_bar") || this.state.drag) {
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        const fraction = (ev.clientX - rect.left) / rect.width;
        let start;
        if (this.isCellMode) {
            const index = clamp(Math.floor(fraction * this.days.length), 0, this.days.length - 1);
            start = this.days[index].plus({ minutes: Math.round(this.archInfo.dayStartHour * 60) });
        } else {
            start = this.fromFraction(fraction);
        }
        this.createRecord(start, row.id);
    }

    // -------------------------------------------------------------------------
    // Drag & drop rescheduling
    // -------------------------------------------------------------------------

    onBarPointerDown(ev, item, row) {
        if (ev.button !== 0) {
            return;
        }
        ev.preventDefault();
        const track = ev.currentTarget.closest(".o_dg_track");
        const trackWidth = track.getBoundingClientRect().width;
        const originX = ev.clientX;
        const originY = ev.clientY;
        const duration = item.end - item.start;
        let moved = false;
        let target = null;

        const computeTarget = (e) => {
            const dx = e.clientX - originX;
            let start;
            if (this.isCellMode) {
                // move by whole days, keep the time of day
                const dayDelta = Math.round((dx / trackWidth) * this.days.length);
                start = DateTime.fromMillis(item.start).plus({ days: dayDelta });
            } else {
                start = this.fromFraction(item.x0 + dx / trackWidth);
            }
            const rowEl = document
                .elementFromPoint(e.clientX, e.clientY)
                ?.closest(".o_dg_row[data-row-id]");
            const rowId = rowEl ? parseInt(rowEl.dataset.rowId, 10) : row.id;
            return { start, end: start.plus({ milliseconds: duration }), rowId };
        };

        const onMove = (e) => {
            const dx = e.clientX - originX;
            const dy = e.clientY - originY;
            if (!moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) {
                return;
            }
            if (!item.draggable) {
                return;
            }
            moved = true;
            target = computeTarget(e);
            this.state.drag = {
                id: item.id,
                dx,
                dy,
                rowId: target.rowId,
                label: `${target.start.toFormat("ccc d LLL, HH:mm")} – ${target.end.toFormat("HH:mm")}`,
            };
        };

        const onUp = async () => {
            this.stopDrag();
            if (!moved) {
                this.openRecord(item.id);
                return;
            }
            // Keep the drag state until the click event (fired after pointerup) is ignored
            setTimeout(() => (this.state.drag = null));
            await this.reschedule(item, row, target);
        };

        this.stopDrag = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            this.stopDrag = null;
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    async reschedule(item, row, target) {
        const { dateStart, dateStop, resourceField } = this.archInfo;
        const values = {};
        if (target.start.toMillis() !== item.start) {
            values[dateStart] = serializeDateTime(target.start);
            values[dateStop] = serializeDateTime(target.end);
        }
        if (target.rowId !== row.id) {
            values[resourceField] = target.rowId || false;
        }
        if (!Object.keys(values).length) {
            return;
        }
        try {
            await this.orm.write(this.props.resModel, [item.id], values, {
                context: this.props.context,
            });
            this.notification.add(
                _t("Appointment moved to %s", target.start.toFormat("ccc d LLL, HH:mm")),
                { type: "success" }
            );
        } finally {
            // Always resync: on error (e.g. doctor already booked) the bar goes back
            await this.reload();
        }
    }
}
