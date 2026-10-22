/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CheckInOut } from "@hr_attendance/components/check_in_out/check_in_out";
import { CameraDialog } from "./camera_dialog";
import { useService } from "@web/core/utils/hooks";

patch(CheckInOut.prototype, {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
    },

    async signInOut() {
        if (!this._attendancePhoto) {
            this.dialogService.add(CameraDialog, {
                onConfirm: async (base64Data) => {
                    this._attendancePhoto = base64Data;
                    await this.signInOut();
                },
                onClose: () => {
                    this._attendancePhoto = null;
                }
            });
            return;
        }

        const photo = this._attendancePhoto;
        this._attendancePhoto = null; // reset for next attempt

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                async ({ coords: { latitude, longitude } }) => {
                    try {
                        await this.orm.call("hr.employee", "update_last_position", [
                            [this.props.employeeId],
                            latitude,
                            longitude,
                        ]);
                    } catch (e) {
                        console.warn("Could not update last position:", e);
                    }
                    await this._executeAttendanceManual(photo, latitude, longitude);
                },
                async (err) => {
                    console.warn("Geolocation denied or failed in kiosk:", err);
                    await this._executeAttendanceManual(photo, false, false);
                },
                { enableHighAccuracy: true, timeout: 8000 }
            );
        } else {
            await this._executeAttendanceManual(photo, false, false);
        }
    },

    async _executeAttendanceManual(photo, latitude, longitude) {
        try {
            const result = await this.orm.call("hr.employee", "attendance_manual", [
                [this.props.employeeId],
                this.props.nextAction,
            ], {
                photo: photo,
                latitude: latitude,
                longitude: longitude
            });
            if (result.action) {
                this.actionService.doAction(result.action);
            } else if (result.warning) {
                this.notification.add(result.warning, { type: "danger" });
            }
        } catch (error) {
            if (error && error.data && error.data.message) {
                this.notification.add(error.data.message, { type: "danger", sticky: true });
            } else {
                throw error;
            }
        }
    }
});
