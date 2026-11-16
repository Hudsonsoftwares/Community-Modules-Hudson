import { onWillStart } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ActivityMenu } from "@hr_attendance/components/attendance_menu/attendance_menu";

/**
 * Check-out picture, built on the core Odoo 20 check-in picture flow.
 *
 * Core shows its camera stream (AttendanceVideoStream) in the systray only
 * while the employee is checked out, and sends the snapshot as
 * `check_in_image`. When "Take Pictures on Check-Out" is enabled we also show
 * the stream while checked in; the server then stores that snapshot on the
 * attendance (`out_image`) and posts it in the chatter.
 */
patch(ActivityMenu.prototype, {
    setup() {
        super.setup();
        this.state.captureCheckOutEnabled = false;
        onWillStart(() => {
            this.lazySession.getValue("attendance_capture_check_out", (enabled) => {
                this.state.captureCheckOutEnabled = !!enabled;
            });
        });
    },

    get showVideoStream() {
        if (this.state.checkedIn) {
            return this.state.captureCheckOutEnabled && this.state.streamAvailable !== false;
        }
        return super.showVideoStream;
    },
});
