import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { Domain } from "@web/core/domain";
import { Model } from "@web/model/model";

const { DateTime } = luxon;

export const RECORD_FIELDS = [
    "order_id",
    "order_partner_id",
    "product_id",
    "rental_start_date",
    "rental_end_date",
    "rental_gantt_status",
    "product_uom_qty",
    "qty_delivered",
    "qty_returned",
    "rental_pickup_date",
    "rental_return_date",
];

/**
 * Data of the rental schedule: the rental lines overlapping the displayed period,
 * grouped in rows (by product unless another grouping is chosen in the search).
 */
export class RentalGanttModel extends Model {
    setup(params) {
        this.resModel = params.resModel;
        this.fields = params.fields || {};
        this.archInfo = params.archInfo;
        this.scale = params.state?.scale || this.archInfo.defaultScale;
        this.focusDate = params.state?.focusDate ? DateTime.fromISO(params.state.focusDate) : DateTime.now();
        this.searchParams = { context: {}, domain: [], groupBy: [] };
        this.rows = [];
        this.columns = [];
    }

    // ------------------------------------------------------------------
    // Period
    // ------------------------------------------------------------------

    get range() {
        const focus = this.focusDate;
        let start;
        let stop;
        switch (this.scale) {
            case "day":
                start = focus.startOf("day");
                stop = start.plus({ days: 1 });
                break;
            case "week": {
                const weekStart = localization.weekStart || 7; // 1 = Monday ... 7 = Sunday
                start = focus.minus({ days: (focus.weekday - weekStart + 7) % 7 }).startOf("day");
                stop = start.plus({ weeks: 1 });
                break;
            }
            case "year":
                start = focus.startOf("year");
                stop = start.plus({ years: 1 });
                break;
            default:
                start = focus.startOf("month");
                stop = start.plus({ months: 1 });
        }
        return { start, stop };
    }

    _computeColumns() {
        const { start, stop } = this.range;
        const step = this.step;
        const now = DateTime.now();
        const columns = [];
        for (let date = start; date < stop; date = date.plus(step)) {
            const end = date.plus(step);
            let label;
            if (this.scale === "day") {
                label = date.toFormat("h a");
            } else if (this.scale === "year") {
                label = date.toFormat("LLLL");
            } else if (this.scale === "week") {
                label = date.toFormat("cccc d");
            } else {
                label = date.toFormat("d");
            }
            columns.push({
                key: date.toISO(),
                label,
                isToday: now >= date && now < end,
                isWeekend: this.scale !== "day" && this.scale !== "year" && [6, 7].includes(date.weekday),
            });
        }
        return columns;
    }

    get title() {
        const { start, stop } = this.range;
        switch (this.scale) {
            case "day":
                return start.toFormat("cccc d LLLL yyyy");
            case "week":
                return _t("Week %(week)s, %(start)s - %(end)s", {
                    week: start.plus({ days: 3 }).weekNumber,
                    start: start.toFormat("d LLL"),
                    end: stop.minus({ days: 1 }).toFormat("d LLL yyyy"),
                });
            case "year":
                return start.toFormat("yyyy");
            default:
                return start.toFormat("LLLL yyyy");
        }
    }

    // ------------------------------------------------------------------
    // Loading
    // ------------------------------------------------------------------

    async load(searchParams = {}) {
        for (const key of ["context", "domain", "groupBy"]) {
            if (searchParams[key] !== undefined) {
                this.searchParams[key] = searchParams[key];
            }
        }
        const { start, stop } = this.range;
        const domain = Domain.and([
            this.searchParams.domain || [],
            [
                ["state", "!=", "cancel"],
                ["rental_start_date", "<", serializeDateTime(stop)],
                ["rental_end_date", ">", serializeDateTime(start)],
            ],
        ]).toList();
        const context = this.searchParams.context || {};
        const records = await this.orm.searchRead(this.resModel, domain, RECORD_FIELDS, {
            context,
            order: "rental_start_date asc, id asc",
        });

        const groupField = this.groupField;
        const extraRows = groupField === "product_id" ? await this._loadRentalProducts(context) : [];
        this.columns = this._computeColumns();
        this.rows = this._buildRows(records, groupField, extraRows);
        this.notify();
    }

    /** Length of one column of the current scale, as a luxon duration object. */
    get step() {
        return { day: { hours: 1 }, year: { months: 1 } }[this.scale] || { days: 1 };
    }

    /** Start of the column at ``index``. */
    columnStart(index) {
        const [unit, value] = Object.entries(this.step)[0];
        return this.range.start.plus({ [unit]: index * value });
    }

    get groupField() {
        const groupBy = (this.searchParams.groupBy || [])[0];
        return (groupBy && groupBy.split(":")[0]) || this.archInfo.defaultGroupBy;
    }

    /** Every rentable product gets a row, even without rentals in the period. */
    async _loadRentalProducts(context) {
        const products = await this.orm.searchRead(
            "product.product",
            [["is_rental", "=", true]],
            ["display_name", "rental_periodicity", "rental_pickup_time", "rental_return_time"],
            { context, order: "default_code, name", limit: 200 }
        );
        return products.map((product) => ({
            id: product.id,
            label: product.display_name,
            // Daily and longer rentals are picked up / returned at the product's times
            times:
                product.rental_periodicity && product.rental_periodicity !== "hour"
                    ? { pickup: product.rental_pickup_time, return: product.rental_return_time }
                    : null,
        }));
    }

    _buildRows(records, groupField, extraRows) {
        const rows = new Map();
        const undefinedLabel = _t("Undefined %s", this.fields[groupField]?.string || "");
        const getRow = (key, label, times = null) => {
            if (!rows.has(key)) {
                rows.set(key, { key, label, times, pills: [] });
            }
            return rows.get(key);
        };
        for (const extra of extraRows) {
            getRow(extra.id, extra.label, extra.times);
        }
        const { start, stop } = this.range;
        const total = stop.toMillis() - start.toMillis();
        for (const record of records) {
            const value = record[groupField];
            const [key, label] = Array.isArray(value)
                ? value
                : value
                  ? [String(value), String(value)]
                  : [false, undefinedLabel];
            const pillStart = deserializeDateTime(record.rental_start_date);
            const pillStop = deserializeDateTime(record.rental_end_date);
            const left = Math.max(0, (pillStart.toMillis() - start.toMillis()) / total);
            const right = Math.min(1, (pillStop.toMillis() - start.toMillis()) / total);
            getRow(key, label).pills.push({
                id: record.id,
                record,
                start: pillStart,
                stop: pillStop,
                left: left * 100,
                width: Math.max((right - left) * 100, 0.4),
                continuesBefore: pillStart < start,
                continuesAfter: pillStop > stop,
                label: [record.order_partner_id && record.order_partner_id[1], record.order_id && record.order_id[1]]
                    .filter(Boolean)
                    .join(", "),
                status: record.rental_gantt_status,
            });
        }
        for (const row of rows.values()) {
            row.laneCount = this._assignLanes(row.pills);
        }
        return [...rows.values()];
    }

    /** Overlapping pills of a row are stacked on separate lanes. */
    _assignLanes(pills) {
        const laneEnds = [];
        for (const pill of pills.sort((a, b) => a.start - b.start)) {
            let lane = laneEnds.findIndex((end) => end <= pill.start);
            if (lane === -1) {
                lane = laneEnds.length;
                laneEnds.push(pill.stop);
            } else {
                laneEnds[lane] = pill.stop;
            }
            pill.lane = lane;
        }
        return Math.max(laneEnds.length, 1);
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    async setScale(scale) {
        this.scale = scale;
        await this.load();
    }

    async move(direction) {
        if (direction === "today") {
            this.focusDate = DateTime.now();
        } else {
            const unit = { day: "days", week: "weeks", month: "months", year: "years" }[this.scale];
            this.focusDate = this.focusDate.plus({ [unit]: direction === "next" ? 1 : -1 });
        }
        await this.load();
    }

    get exportedState() {
        return { scale: this.scale, focusDate: this.focusDate.toISO() };
    }
}
