/** @odoo-module **/

import { Model } from "@web/model/model";

const { DateTime } = luxon;

const STATE_LABELS = { active: "Active", idle: "Idle", locked: "Locked / Away" };

export function formatHours(hours) {
    const minutes = Math.round((hours || 0) * 60);
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h && m) return `${h}h ${m}m`;
    if (h) return `${h}h`;
    return `${m}m`;
}

/**
 * Loads hr.activity.span through `get_activity_timeline` for the visible period
 * (one day or one week, in the browser's time zone) and lays the segments out
 * as percentages of the period.
 */
export class ActivityGanttModel extends Model {
    static services = ["orm"];

    setup(params, services) {
        this.orm = services.orm;
        this.resModel = params.resModel;
        this.scale = params.archInfo.defaultScale;
        this.colorBy = "state";
        const initial = params.context && params.context.initial_date;
        this.focusDate = initial ? DateTime.fromISO(initial) : DateTime.now();
        this.domain = [];
        this.rows = [];
        this.showTitles = false;
    }

    async load(params = {}) {
        if (params.domain !== undefined) {
            this.domain = params.domain;
        }
        const { start, end } = this.bounds;
        const result = await this.orm.call(this.resModel, "get_activity_timeline", [
            this.domain,
            start.toUTC().toFormat("yyyy-MM-dd HH:mm:ss"),
            end.toUTC().toFormat("yyyy-MM-dd HH:mm:ss"),
        ], { merge_by: this.scale === "day" ? "app" : "state" });
        this.showTitles = result.show_titles;
        const total = end.diff(start).as("milliseconds");
        this.rows = result.rows.map((row) => ({
            ...row,
            topAppsLabel: row.top_apps.map((a) => `${a.name} (${formatHours(a.hours)})`).join(", "),
            segments: row.segments.map((seg) => this._layoutSegment(seg, start, total)),
        }));
    }

    _layoutSegment(seg, start, total) {
        const s = DateTime.fromSQL(seg.start, { zone: "UTC" }).toLocal();
        const e = DateTime.fromSQL(seg.end, { zone: "UTC" }).toLocal();
        const left = (s.diff(start).as("milliseconds") / total) * 100;
        const width = Math.max((e.diff(s).as("milliseconds") / total) * 100, 0.06);
        const name = seg.state === "active" ? seg.app || "Unknown" : STATE_LABELS[seg.state];
        const lines = [name];
        if (seg.title) {
            lines.push(seg.title);
        }
        lines.push(`${s.toFormat("HH:mm")} - ${e.toFormat("HH:mm")}  (${formatHours(seg.hours)})`);
        if (seg.count > 1) {
            lines.push(`${seg.count} records`);
        }
        if (seg.live) {
            lines.push("Live");
        }
        return { ...seg, startDt: s, endDt: e, left, width, tooltip: lines.join("\n") };
    }

    get unit() {
        return this.scale === "day" ? "day" : "week";
    }

    get bounds() {
        const start = this.focusDate.startOf(this.unit);
        return { start, end: start.plus({ [`${this.unit}s`]: 1 }) };
    }

    get title() {
        const { start, end } = this.bounds;
        if (this.scale === "day") {
            return start.toFormat("cccc, d LLLL yyyy");
        }
        return `${start.toFormat("d LLL")} - ${end.minus({ days: 1 }).toFormat("d LLL yyyy")}`;
    }

    get ticks() {
        const { start } = this.bounds;
        if (this.scale === "day") {
            return Array.from({ length: 24 }, (_v, i) => ({
                key: i,
                left: (i / 24) * 100,
                label: i % 2 === 0 ? start.plus({ hours: i }).toFormat("h a") : "",
            }));
        }
        return Array.from({ length: 7 }, (_v, i) => ({
            key: i,
            left: (i / 7) * 100,
            label: start.plus({ days: i }).toFormat("ccc d"),
        }));
    }

    get nowLeft() {
        const { start, end } = this.bounds;
        const now = DateTime.now();
        if (now < start || now >= end) {
            return null;
        }
        return (now.diff(start).as("milliseconds") / end.diff(start).as("milliseconds")) * 100;
    }

    async navigate(direction) {
        if (direction === "today") {
            this.focusDate = DateTime.now();
        } else {
            const delta = { [`${this.unit}s`]: direction === "next" ? 1 : -1 };
            this.focusDate = this.focusDate.plus(delta);
        }
        await this.load();
        this.notify();
    }

    async setScale(scale) {
        this.scale = scale;
        await this.load();
        this.notify();
    }

    setColorBy(colorBy) {
        this.colorBy = colorBy;
        this.notify();
    }
}
