/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";
import { CameraDialog } from "./camera_dialog";
import { rpc, ConnectionLostError } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

patch(ActivityMenu.prototype, {
    async checking(latitude = false, longitude = false) {
        if (!this._attendancePhoto) {
            this.dialogService.add(CameraDialog, {
                onConfirm: async (base64Data) => {
                    this._attendancePhoto = base64Data;
                    await this.checking(latitude, longitude);
                },
                onClose: () => {
                    this._attendanceInProgress = false;
                }
            });
            return;
        }

        try {
            this.employee = await rpc("/hr_attendance/systray_check_in_out", {
                latitude,
                longitude,
                photo: this._attendancePhoto
            });
            this._searchReadEmployeeFill();
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                this.notification.add(
                    _t("Connection lost. Check in/out could not be recorded."), 
                    { 
                        title: _t("Attendance Error"),
                        type: "danger",
                        sticky: false,
                    }
                );
            } else if (error && error.data && error.data.message) {
                // Handle the user error raised by the radius checking
                this.notification.add(
                    error.data.message, 
                    { 
                        title: _t("Attendance Blocked"),
                        type: "danger",
                        sticky: false,
                    }
                );
            } else {
                throw error;
            }
        } finally {
            this._attendanceInProgress = false;
            this._attendancePhoto = null;
        }
    }
});
