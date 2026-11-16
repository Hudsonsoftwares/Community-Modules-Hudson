/** @odoo-module **/

import { Component, proxy, signal, t, useProps } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { useModel } from "@web/model/model";
import { useService } from "@web/core/utils/hooks";
import { standardViewProps } from "@web/views/standard_view_props";
import { useSetupAction } from "@web/search/action_hook";

const { DateTime } = luxon;

export class AttendanceGanttController extends Component {
    static template = "hudson_attendance_enhancement.AttendanceGanttController";
    static components = {
        Layout,
        SearchBar,
        CogMenu,
        Dropdown,
        DropdownItem,
    };
    props = useProps({
        ...standardViewProps,
        Model: t.function(),
        Renderer: t.function(),
        archInfo: t.object(),
    });

    setup() {
        this.rootRef = signal.ref();
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.searchBarToggler = useSearchBarToggler();

        this.state = proxy({
            isFullscreen: false,
        });

        this.model = useModel(this.props.Model, {
            resModel: this.props.resModel,
            archInfo: this.props.archInfo,
        });

        // useModel already re-renders this component on model.notify();
        // OWL 3 components have no this.render(), so calling it crashed every
        // navigation (previous/next/today, day/week/month).

        useSetupAction({
            rootRef: this.rootRef,
            getLocalState: () => ({
                focusDate: this.model.focusDate.toISO(),
                scale: this.model.scale,
            }),
            setLocalState: (state) => {
                if (state && state.focusDate) {
                    this.model.focusDate = DateTime.fromISO(state.focusDate);
                }
                if (state && state.scale) {
                    this.model.scale = state.scale;
                }
            },
        });
    }

    get scaleLabels() {
        return {
            day: "Day",
            week: "Week",
            month: "Month",
        };
    }

    get currentScaleLabel() {
        return this.scaleLabels[this.model.scale] || "Day";
    }

    async onDateNav(direction) {
        await this.model.setDate(direction);
    }

    async onScaleSelect(scale) {
        await this.model.setScale(scale);
    }

    toggleFullscreen() {
        this.state.isFullscreen = !this.state.isFullscreen;
    }

    createAttendance(defaultEmployeeId = null) {
        const context = {};
        if (defaultEmployeeId) {
            context.default_employee_id = defaultEmployeeId;
        }
        context.default_check_in = DateTime.now().toUTC().toFormat("yyyy-MM-dd HH:mm:ss");

        this.dialog.add(FormViewDialog, {
            resModel: this.props.resModel,
            title: "New Attendance",
            context,
            onRecordSaved: async () => {
                await this.model.load();
                this.model.notify();
            },
        });
    }

    openAttendance(resId) {
        this.dialog.add(FormViewDialog, {
            resModel: this.props.resModel,
            resId: resId,
            title: "Attendance Details",
            onRecordSaved: async () => {
                await this.model.load();
                this.model.notify();
            },
        });
    }

    openCreateWithRange(employeeId, checkIn, checkOut) {
        const context = {};
        if (employeeId) {
            context.default_employee_id = employeeId;
        }
        if (checkIn) {
            context.default_check_in = checkIn;
        }
        if (checkOut) {
            context.default_check_out = checkOut;
        }

        this.dialog.add(FormViewDialog, {
            resModel: this.props.resModel,
            title: "New Attendance",
            context,
            onRecordSaved: async () => {
                await this.model.load();
                this.model.notify();
            },
        });
    }

    openEmployee(employeeId) {
        if (!employeeId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            res_id: employeeId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onExtendAttendance(attendanceId, updateVals) {
        try {
            await this.orm.write(this.props.resModel, [attendanceId], updateVals);
            await this.model.load();
            this.model.notify();
            this.notification.add("Attendance updated successfully", { type: "success" });
        } catch (error) {
            console.error("Error extending attendance:", error);
            const msg = error.data?.message || error.message || String(error);
            this.notification.add("Failed to update attendance: " + msg, { type: "danger" });
        }
    }

    onCellClick(employeeId, ev) {
        this.createAttendance(employeeId);
    }
}
