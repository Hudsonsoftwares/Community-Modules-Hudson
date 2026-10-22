/** @odoo-module **/

import { Model } from "@web/model/model";

const { DateTime } = luxon;

function parseUtcDateTime(str) {
    if (!str) return null;
    let dt = DateTime.fromSQL(str, { zone: "UTC" });
    if (!dt.isValid) {
        dt = DateTime.fromISO(str, { zone: "UTC" });
    }
    return dt.isValid ? dt : null;
}

function formatHoursToHm(hours) {
    if (hours === undefined || hours === null || isNaN(hours) || hours <= 0) return "0h";
    const totalMinutes = Math.round(hours * 60);
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    if (h > 0 && m > 0) return `${h}h ${m}m`;
    if (h > 0) return `${h}h`;
    return `${m}m`;
}

export class AttendanceGanttModel extends Model {

    static services = ["orm"];

    setup(params, services) {
        this.resModel = params.resModel || "hr.attendance";
        this.orm = services?.orm || this.orm;
        this.scale = params.archInfo?.defaultScale || "day";
        this.focusDate = DateTime.now();
        this.employees = [];
        this.attendances = [];
        this.userTz = "UTC";
        this.serverTime = null;
        this.currentDomain = [];
        this.processedRows = [];
        this.slots = [];
        this.dateTitle = "";
    }

    async load(params = {}) {
        if (params.domain !== undefined) {
            this.currentDomain = params.domain;
        }
        await this._fetchData();
        this._computeProcessedData();
    }

    async setDate(direction) {
        if (direction === "today") {
            this.focusDate = DateTime.now();
        } else if (direction === "previous") {
            if (this.scale === "day") {
                this.focusDate = this.focusDate.minus({ days: 1 });
            } else if (this.scale === "week") {
                this.focusDate = this.focusDate.minus({ weeks: 1 });
            } else if (this.scale === "month") {
                this.focusDate = this.focusDate.minus({ months: 1 });
            }
        } else if (direction === "next") {
            if (this.scale === "day") {
                this.focusDate = this.focusDate.plus({ days: 1 });
            } else if (this.scale === "week") {
                this.focusDate = this.focusDate.plus({ weeks: 1 });
            } else if (this.scale === "month") {
                this.focusDate = this.focusDate.plus({ months: 1 });
            }
        }
        await this.load();
        this.notify();
    }

    async setScale(scale) {
        this.scale = scale;
        await this.load();
        this.notify();
    }

    getPeriodBounds() {
        let start, end;
        if (this.scale === "day") {
            start = this.focusDate.startOf("day");
            end = this.focusDate.endOf("day");
        } else if (this.scale === "week") {
            start = this.focusDate.startOf("week");
            end = this.focusDate.endOf("week");
        } else if (this.scale === "month") {
            start = this.focusDate.startOf("month");
            end = this.focusDate.endOf("month");
        }
        return { start, end };
    }

    async _fetchData() {
        const { start, end } = this.getPeriodBounds();
        const dateStartUtc = start.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
        const dateStopUtc = end.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");

        try {
            const result = await this.orm.call(
                this.resModel,
                "get_attendance_gantt_data",
                [],
                {
                    domain: this.currentDomain,
                    date_start: dateStartUtc,
                    date_stop: dateStopUtc,
                    scale: this.scale,
                }
            );
            this.employees = result.employees || [];
            this.attendances = result.attendances || [];
            this.userTz = result.user_tz || "UTC";
            this.serverTime = result.server_time ? DateTime.fromISO(result.server_time) : DateTime.now();
        } catch (error) {
            console.error("Error fetching attendance gantt data:", error);
            this.employees = [];
            this.attendances = [];
        }
    }

    _computeProcessedData() {
        const { start, end } = this.getPeriodBounds();
        const now = DateTime.now();

        // 1. Compute Date Title
        if (this.scale === "day") {
            this.dateTitle = this.focusDate.toFormat("cccc, d MMMM yyyy");
        } else if (this.scale === "week") {
            this.dateTitle = `${start.toFormat("d MMM")} - ${end.toFormat("d MMM yyyy")}`;
        } else if (this.scale === "month") {
            this.dateTitle = this.focusDate.toFormat("MMMM yyyy");
        }

        // 2. Compute Header Slots
        this.slots = [];
        if (this.scale === "day") {
            const isToday = this.focusDate.hasSame(now, "day");
            const currentHour = now.hour;
            for (let h = 0; h < 24; h++) {
                let label;
                if (h === 0) label = "12am";
                else if (h < 12) label = `${h}am`;
                else if (h === 12) label = "12pm";
                else label = `${h - 12}pm`;

                this.slots.push({
                    index: h,
                    label,
                    isCurrent: isToday && currentHour === h,
                    isWeekend: false,
                });
            }
        } else if (this.scale === "week") {
            let cursor = start;
            while (cursor <= end) {
                this.slots.push({
                    index: cursor.weekday,
                    label: cursor.toFormat("ccc d"),
                    isCurrent: cursor.hasSame(now, "day"),
                    isWeekend: cursor.weekday >= 6,
                });
                cursor = cursor.plus({ days: 1 });
            }
        } else if (this.scale === "month") {
            let cursor = start;
            while (cursor <= end) {
                this.slots.push({
                    index: cursor.day,
                    label: `${cursor.day}`,
                    isCurrent: cursor.hasSame(now, "day"),
                    isWeekend: cursor.weekday >= 6,
                });
                cursor = cursor.plus({ days: 1 });
            }
        }

        // 3. Process Employee Rows & Attendance Bars
        const periodTotalSeconds = end.diff(start, "seconds").seconds;

        const attendancesByEmployee = {};
        for (const att of this.attendances) {
            const empId = Array.isArray(att.employee_id) ? att.employee_id[0] : att.employee_id;
            if (!attendancesByEmployee[empId]) {
                attendancesByEmployee[empId] = [];
            }
            attendancesByEmployee[empId].push(att);
        }

        const colors = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2", "#4f46e5"];

        this.processedRows = this.employees.map((emp, idx) => {
            const empAttendances = attendancesByEmployee[emp.id] || [];
            const bars = [];
            const dailyPlannedHours = emp.daily_planned_hours || 8.0;

            // Determine planned hours for this view scale
            let periodPlannedHours = dailyPlannedHours;
            if (this.scale === "week") {
                periodPlannedHours = dailyPlannedHours * 5;
            } else if (this.scale === "month") {
                const daysCount = Math.max(1, Math.round(end.diff(start, "days").days));
                periodPlannedHours = dailyPlannedHours * Math.max(1, Math.round((daysCount * 5) / 7));
            }

            // Compute total worked hours across all attendances in visible period
            let totalWorkedHours = 0;
            for (const att of empAttendances) {
                if (att.worked_hours) {
                    totalWorkedHours += att.worked_hours;
                } else if (!att.check_out && att.check_in) {
                    const parsedIn = parseUtcDateTime(att.check_in);
                    if (parsedIn) {
                        const elapsedSec = Math.max(0, now.diff(parsedIn.setZone(this.userTz), "seconds").seconds);
                        totalWorkedHours += elapsedSec / 3600;
                    }
                }
            }

            const hasAttendance = empAttendances.length > 0;
            const hasOvertime = totalWorkedHours > (periodPlannedHours + 0.01);
            const overtimeHours = hasOvertime ? totalWorkedHours - periodPlannedHours : 0;
            const dailyWorkedDisplay = `${formatHoursToHm(totalWorkedHours)} / ${formatHoursToHm(periodPlannedHours)}`;
            const overtimeDisplay = hasOvertime ? formatHoursToHm(overtimeHours) : "";
            const employeeTooltip = `${emp.name}${hasAttendance ? `\nWorked: ${dailyWorkedDisplay}` : ' (No attendance recorded)'}${hasOvertime ? `\nOvertime: +${overtimeDisplay}` : ''}`;

            // Compute Initials and Color
            const nameParts = (emp.name || "").trim().split(" ");
            let initials = "";
            if (nameParts.length >= 2) {
                initials = (nameParts[0][0] + nameParts[1][0]).toUpperCase();
            } else if (nameParts.length === 1 && nameParts[0].length > 0) {
                initials = nameParts[0].substring(0, 2).toUpperCase();
            }
            const color = colors[idx % colors.length];

            // Group attendances by calendar day (in user timezone) to track daily cumulative quota
            const attendancesByDay = {};
            for (const att of empAttendances) {
                const parsedIn = parseUtcDateTime(att.check_in);
                if (!parsedIn) continue;
                const dayKey = parsedIn.setZone(this.userTz).toFormat("yyyy-MM-dd");
                if (!attendancesByDay[dayKey]) {
                    attendancesByDay[dayKey] = [];
                }
                attendancesByDay[dayKey].push(att);
            }

            // For each day, sort chronologically and compute running regular quota vs overtime
            const attDayQuotas = {};
            for (const dayKey of Object.keys(attendancesByDay)) {
                const dayAtts = attendancesByDay[dayKey];
                dayAtts.sort((a, b) => {
                    const tA = parseUtcDateTime(a.check_in)?.toMillis() || 0;
                    const tB = parseUtcDateTime(b.check_in)?.toMillis() || 0;
                    return tA - tB;
                });

                let cumulativeRegHours = 0;
                for (const att of dayAtts) {
                    const parsedCheckIn = parseUtcDateTime(att.check_in);
                    const dtCheckIn = parsedCheckIn.setZone(this.userTz);
                    let dtCheckOut = now;
                    if (att.check_out) {
                        const parsedCheckOut = parseUtcDateTime(att.check_out);
                        if (parsedCheckOut) dtCheckOut = parsedCheckOut.setZone(this.userTz);
                    }
                    const totalDurSec = Math.max(0, dtCheckOut.diff(dtCheckIn, "seconds").seconds);
                    const attDurHours = att.worked_hours || (totalDurSec / 3600);

                    const remainingQuota = Math.max(0, dailyPlannedHours - cumulativeRegHours);
                    const regHours = Math.min(attDurHours, remainingQuota);
                    const otHours = Math.max(0, attDurHours - regHours);
                    cumulativeRegHours += regHours;

                    attDayQuotas[att.id] = {
                        durHours: attDurHours,
                        regHours,
                        otHours,
                        isAllOvertime: regHours <= 0.005,
                    };
                }
            }

            for (const att of empAttendances) {
                const parsedCheckIn = parseUtcDateTime(att.check_in);
                if (!parsedCheckIn) continue;

                let dtCheckIn = parsedCheckIn.setZone(this.userTz);
                let dtCheckOut;
                let isActive = false;

                if (att.check_out) {
                    const parsedCheckOut = parseUtcDateTime(att.check_out);
                    dtCheckOut = parsedCheckOut ? parsedCheckOut.setZone(this.userTz) : now;
                } else {
                    dtCheckOut = now;
                    isActive = true;
                }

                // Bound check to current visible period
                const barStart = dtCheckIn < start ? start : dtCheckIn;
                const barEnd = dtCheckOut > end ? end : dtCheckOut;

                if (barEnd <= start || barStart >= end) {
                    continue;
                }

                const startOffsetSec = barStart.diff(start, "seconds").seconds;
                const durationSec = Math.max(barEnd.diff(barStart, "seconds").seconds, 300); // min 5 mins visually

                const leftPercent = Math.max(0, Math.min(100, (startOffsetSec / periodTotalSeconds) * 100));
                const widthPercent = Math.max(1, Math.min(100 - leftPercent, (durationSec / periodTotalSeconds) * 100));

                const quota = attDayQuotas[att.id] || { durHours: durationSec / 3600, regHours: durationSec / 3600, otHours: 0, isAllOvertime: false };
                const isAllOvertime = quota.isAllOvertime && !isActive;
                const barHasOvertime = quota.otHours > 0.02 && !isActive;

                let label = "";
                let regPercent = 100;
                let otPercent = 0;
                let barStyle = "";

                if (isActive) {
                    // Currently working: Green color, label e.g. "From 09:00:00 am"
                    label = `From ${dtCheckIn.toFormat("hh:mm:ss a").toLowerCase()}`;
                    barStyle = "background-color: #76ba85; background: #76ba85; color: #153f1d;";
                } else {
                    // Checked out: Grey color or Pale Overtime color
                    const totalDurSec = Math.max(0, dtCheckOut.diff(dtCheckIn, "seconds").seconds);
                    const durTotalMins = Math.round(totalDurSec / 60);
                    const durHours = Math.floor(durTotalMins / 60);
                    const durMins = durTotalMins % 60;
                    const durHhMm = `${String(durHours).padStart(2, "0")}:${String(durMins).padStart(2, "0")}`;
                    const inStr = dtCheckIn.toFormat("hh:mm:ss a").toLowerCase();
                    const outStr = dtCheckOut.toFormat("hh:mm:ss a").toLowerCase();
                    label = `${durHhMm} (${inStr}-${outStr})`;

                    if (isAllOvertime) {
                        regPercent = 0;
                        otPercent = 100;
                        barStyle = "background-color: #cbd5e1; background: #cbd5e1; color: #1e293b;";
                    } else if (barHasOvertime) {
                        const regRatio = Math.min(1, Math.max(0, quota.regHours / quota.durHours));
                        regPercent = (regRatio * 100).toFixed(1);
                        otPercent = (100 - regPercent).toFixed(1);
                        barStyle = `background: linear-gradient(to right, #9da5b0 0%, #9da5b0 ${regPercent}%, #cbd5e1 ${regPercent}%, #cbd5e1 100%);`;
                    } else {
                        barStyle = "background-color: #9da5b0; background: #9da5b0; color: #1e293b;";
                    }
                }

                let tooltip = `Employee: ${emp.name}
Check In: ${dtCheckIn.toFormat("dd/MM/yyyy hh:mm:ss a")}
Check Out: ${att.check_out ? dtCheckOut.toFormat("dd/MM/yyyy hh:mm:ss a") : "Currently Active"}
Duration: ${formatHoursToHm(quota.durHours)}`;
                if (quota.otHours > 0) {
                    tooltip += `\n- Regular: ${formatHoursToHm(quota.regHours)}\n- Overtime: +${formatHoursToHm(quota.otHours)}`;
                }
                tooltip += `\nDay Planned: ${formatHoursToHm(dailyPlannedHours)} scheduled`;
                tooltip += `\nMode: ${att.is_wfh ? "Work From Home (" + (att.wfh_status || "verified") + ")" : "Office / On-Site"}`;

                bars.push({
                    id: att.id,
                    left: leftPercent.toFixed(2),
                    width: widthPercent.toFixed(2),
                    label,
                    tooltip,
                    isWfh: att.is_wfh,
                    isActive,
                    isAllOvertime,
                    hasOvertime: barHasOvertime,
                    regPercent,
                    otPercent,
                    barStyle,
                });
            }

            return {
                employee: emp,
                initials,
                color,
                avatarUrl: `/web/image?model=hr.employee&id=${emp.id}&field=avatar_128`,
                hasAttendance,
                totalWorkedHours,
                dailyPlannedHours,
                dailyWorkedDisplay,
                hasOvertime,
                overtimeDisplay,
                employeeTooltip,
                bars,
            };
        });
    }
}
