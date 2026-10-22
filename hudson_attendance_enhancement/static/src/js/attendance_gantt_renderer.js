/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

function formatTime12h(hours, minutes) {
    const period = hours >= 12 && hours < 24 ? "pm" : "am";
    let h12 = hours % 12;
    if (h12 === 0) h12 = 12;
    const mStr = String(minutes).padStart(2, "0");
    return `${String(h12).padStart(2, "0")}:${mStr} ${period}`;
}

export class AttendanceGanttRenderer extends Component {
    static template = "hudson_attendance_enhancement.AttendanceGanttRenderer";
    static props = {
        model: Object,
        onBarClick: Function,
        onTimeRangeSelected: Function,
        onEmployeeClick: Function,
        onExtendAttendance: Function,
    };

    setup() {
        this.state = useState({
            dragSelection: {
                active: false,
                employeeId: null,
                left: 0,
                width: 0,
                label: "",
            },
            resizingBar: {
                active: false,
                barId: null,
                handleType: null,
                left: 0,
                width: 0,
                label: "",
            },
        });
    }

    onBarClick(barId, ev) {
        ev.stopPropagation();
        this.props.onBarClick(barId);
    }

    onHandleMouseDown(bar, row, handleType, ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (ev.button !== 0) return;

        const trackEl = ev.currentTarget.closest(".o_attendance_gantt_timeline_track");
        const rect = trackEl.getBoundingClientRect();

        const initialLeft = parseFloat(bar.left);
        const initialWidth = parseFloat(bar.width);
        const scale = this.props.model.scale || "day";

        this.state.resizingBar.active = true;
        this.state.resizingBar.barId = bar.id;
        this.state.resizingBar.handleType = handleType;
        this.state.resizingBar.left = initialLeft;
        this.state.resizingBar.width = initialWidth;
        this.state.resizingBar.label = bar.label;

        const onMouseMove = (moveEv) => {
            moveEv.preventDefault();
            const currentRatio = Math.max(0, Math.min(1, (moveEv.clientX - rect.left) / rect.width));

            if (scale === "day") {
                const currentMin = Math.round((currentRatio * 1440) / 15) * 15;

                if (handleType === "end") {
                    const startMin = Math.round((initialLeft / 100) * 1440);
                    let newEndMin = Math.max(startMin + 15, Math.min(1440, currentMin));
                    const newWidth = ((newEndMin - startMin) / 1440) * 100;

                    const h2 = Math.floor(newEndMin / 60);
                    const min2 = newEndMin % 60;
                    const durHours = Math.floor((newEndMin - startMin) / 60);
                    const durMins = (newEndMin - startMin) % 60;
                    const durStr = durHours > 0 ? `${durHours}h ${durMins}m` : `${durMins}m`;

                    this.state.resizingBar.width = newWidth.toFixed(2);
                    this.state.resizingBar.newEndMin = newEndMin;
                    this.state.resizingBar.label = `Extend to ${formatTime12h(h2, min2)} (${durStr})`;
                } else if (handleType === "start") {
                    const endMin = Math.round(((initialLeft + initialWidth) / 100) * 1440);
                    let newStartMin = Math.max(0, Math.min(endMin - 15, currentMin));
                    const newLeft = (newStartMin / 1440) * 100;
                    const newWidth = ((endMin - newStartMin) / 1440) * 100;

                    const h1 = Math.floor(newStartMin / 60);
                    const min1 = newStartMin % 60;
                    const durHours = Math.floor((endMin - newStartMin) / 60);
                    const durMins = (endMin - newStartMin) % 60;
                    const durStr = durHours > 0 ? `${durHours}h ${durMins}m` : `${durMins}m`;

                    this.state.resizingBar.left = newLeft.toFixed(2);
                    this.state.resizingBar.width = newWidth.toFixed(2);
                    this.state.resizingBar.newStartMin = newStartMin;
                    this.state.resizingBar.label = `Start at ${formatTime12h(h1, min1)} (${durStr})`;
                }
            }
        };

        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);

            if (!this.state.resizingBar.active) return;

            const resizeData = { ...this.state.resizingBar };
            this.state.resizingBar.active = false;
            this.state.resizingBar.barId = null;

            const focusDay = this.props.model.focusDate;
            const updateVals = {};

            if (handleType === "end" && resizeData.newEndMin !== undefined) {
                const h2 = Math.floor(resizeData.newEndMin / 60);
                const min2 = resizeData.newEndMin % 60;
                let dtEnd;
                if (h2 >= 24) {
                    dtEnd = focusDay.set({ hour: 23, minute: 59, second: 59, millisecond: 0 });
                } else {
                    dtEnd = focusDay.set({ hour: h2, minute: min2, second: 0, millisecond: 0 });
                }
                updateVals.check_out = dtEnd.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
            } else if (handleType === "start" && resizeData.newStartMin !== undefined) {
                const h1 = Math.floor(resizeData.newStartMin / 60);
                const min1 = resizeData.newStartMin % 60;
                const dtStart = focusDay.set({ hour: h1, minute: min1, second: 0, millisecond: 0 });
                updateVals.check_in = dtStart.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
            }

            if (Object.keys(updateVals).length > 0) {
                this.props.onExtendAttendance(bar.id, updateVals);
            }
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }

    onTrackMouseDown(row, ev) {
        // Only handle primary (left) click
        if (ev.button !== 0) return;
        if (ev.target.closest(".o_attendance_gantt_bar")) return;

        ev.preventDefault();
        const trackEl = ev.currentTarget;
        const rect = trackEl.getBoundingClientRect();
        const startRatio = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));

        let currentRatio = startRatio;
        const scale = this.props.model.scale || "day";

        const updateSelectionState = () => {
            const r1 = Math.min(startRatio, currentRatio);
            const r2 = Math.max(startRatio, currentRatio);

            if (scale === "day") {
                let m1 = Math.round((r1 * 24 * 60) / 15) * 15;
                let m2 = Math.round((r2 * 24 * 60) / 15) * 15;
                if (m2 <= m1) m2 = m1 + 15;
                if (m2 > 1440) m2 = 1440;

                const left = (m1 / 1440) * 100;
                const width = ((m2 - m1) / 1440) * 100;

                const h1 = Math.floor(m1 / 60);
                const min1 = m1 % 60;
                const h2 = Math.floor(m2 / 60);
                const min2 = m2 % 60;

                const durHours = Math.floor((m2 - m1) / 60);
                const durMinutes = (m2 - m1) % 60;
                const durStr = durHours > 0 ? `${durHours}h ${durMinutes}m` : `${durMinutes}m`;

                this.state.dragSelection.active = true;
                this.state.dragSelection.employeeId = row.employee.id;
                this.state.dragSelection.left = left.toFixed(2);
                this.state.dragSelection.width = width.toFixed(2);
                this.state.dragSelection.label = `${formatTime12h(h1, min1)} - ${formatTime12h(h2, min2)} (${durStr})`;
            } else if (scale === "week") {
                const d1 = Math.floor(r1 * 7);
                const d2 = Math.min(6, Math.floor(r2 * 7));
                const left = (d1 / 7) * 100;
                const width = ((d2 - d1 + 1) / 7) * 100;

                this.state.dragSelection.active = true;
                this.state.dragSelection.employeeId = row.employee.id;
                this.state.dragSelection.left = left.toFixed(2);
                this.state.dragSelection.width = width.toFixed(2);
                this.state.dragSelection.label = `Days: ${d2 - d1 + 1}`;
            } else if (scale === "month") {
                const daysInMonth = this.props.model.focusDate.daysInMonth;
                const day1 = Math.max(1, Math.min(daysInMonth, Math.floor(r1 * daysInMonth) + 1));
                const day2 = Math.max(day1, Math.min(daysInMonth, Math.floor(r2 * daysInMonth) + 1));
                const left = ((day1 - 1) / daysInMonth) * 100;
                const width = ((day2 - day1 + 1) / daysInMonth) * 100;

                this.state.dragSelection.active = true;
                this.state.dragSelection.employeeId = row.employee.id;
                this.state.dragSelection.left = left.toFixed(2);
                this.state.dragSelection.width = width.toFixed(2);
                this.state.dragSelection.label = `${day2 - day1 + 1} day(s)`;
            }
        };

        updateSelectionState();

        const onMouseMove = (moveEv) => {
            currentRatio = Math.max(0, Math.min(1, (moveEv.clientX - rect.left) / rect.width));
            updateSelectionState();
        };

        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);

            if (!this.state.dragSelection.active) return;

            const r1 = Math.min(startRatio, currentRatio);
            const r2 = Math.max(startRatio, currentRatio);
            const employeeId = row.employee.id;

            this.state.dragSelection.active = false;
            this.state.dragSelection.employeeId = null;

            let dtStart, dtEnd;
            const focusDay = this.props.model.focusDate;

            if (scale === "day") {
                let m1 = Math.round((r1 * 24 * 60) / 15) * 15;
                let m2 = Math.round((r2 * 24 * 60) / 15) * 15;
                if (m2 <= m1) m2 = m1 + 15;
                if (m2 > 1440) m2 = 1440;

                const h1 = Math.floor(m1 / 60);
                const min1 = m1 % 60;
                let h2 = Math.floor(m2 / 60);
                let min2 = m2 % 60;

                dtStart = focusDay.set({ hour: h1, minute: min1, second: 0, millisecond: 0 });
                if (h2 >= 24) {
                    dtEnd = focusDay.set({ hour: 23, minute: 59, second: 59, millisecond: 0 });
                } else {
                    dtEnd = focusDay.set({ hour: h2, minute: min2, second: 0, millisecond: 0 });
                }
            } else if (scale === "week") {
                const d1 = Math.floor(r1 * 7);
                const d2 = Math.min(6, Math.floor(r2 * 7));
                dtStart = focusDay.startOf("week").plus({ days: d1 }).set({ hour: 9, minute: 0, second: 0 });
                dtEnd = focusDay.startOf("week").plus({ days: d2 }).set({ hour: 18, minute: 0, second: 0 });
            } else if (scale === "month") {
                const daysInMonth = focusDay.daysInMonth;
                const day1 = Math.max(1, Math.min(daysInMonth, Math.floor(r1 * daysInMonth) + 1));
                const day2 = Math.max(day1, Math.min(daysInMonth, Math.floor(r2 * daysInMonth) + 1));
                dtStart = focusDay.set({ day: day1, hour: 9, minute: 0, second: 0 });
                dtEnd = focusDay.set({ day: day2, hour: 18, minute: 0, second: 0 });
            }

            const checkInUtc = dtStart.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
            const checkOutUtc = dtEnd.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");

            this.props.onTimeRangeSelected(employeeId, checkInUtc, checkOutUtc);
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }
}
