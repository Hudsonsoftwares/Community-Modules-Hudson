/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";
import { CameraDialog } from "./camera_dialog";
import { rpc, ConnectionLostError } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

patch(ActivityMenu.prototype, {
    async checking(latitude = false, longitude = false) {
        // Step 1: Prompt for Camera / Photo Verification if not yet captured
        if (!this._attendancePhoto) {
            this.dialogService.add(CameraDialog, {
                onConfirm: async (base64Data) => {
                    this._attendancePhoto = base64Data;
                    await this.checking(latitude, longitude);
                },
                onClose: () => {
                    this._attendanceInProgress = false;
                    this._attendancePhoto = null;
                }
            });
            return;
        }

        // Step 2: If coordinates are missing, attempt to acquire them via GPS
        if ((latitude === false || longitude === false) && navigator.geolocation) {
            try {
                const position = await new Promise((resolve, reject) => {
                    navigator.geolocation.getCurrentPosition(resolve, reject, {
                        enableHighAccuracy: true,
                        timeout: 8000,
                        maximumAge: 0,
                    });
                });
                latitude = position.coords.latitude;
                longitude = position.coords.longitude;
            } catch (geoErr) {
                console.warn("Could not retrieve GPS coordinates before check in/out:", geoErr);
            }
        }

        // Step 3: Send check-in/out request with photo and coordinates
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
                this.notification.add(
                    error.data.message, 
                    { 
                        title: _t("Attendance Blocked"),
                        type: "danger",
                        sticky: true,
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
