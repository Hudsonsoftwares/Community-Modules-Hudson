import { patch } from "@web/core/utils/patch";
import { KioskConfirmation } from "@hr_attendance/components/confirmation/confirmation";
import { KioskPinCode } from "@hr_attendance/components/pin_code/pin_code";

/**
 * Kiosk check-out picture.
 *
 * Core only shows the camera on these screens when the employee is about to
 * check in. Once the employee is known, use the setting matching the next
 * action: "Take Pictures on Check-In" or "Take Pictures on Check-Out" (both
 * flags come with the employee data, see controllers/main.py). The snapshot is
 * sent as usual; the server stores it as check-in or check-out picture.
 */
function showCameraFor(employeeData, checkedIn, streamAvailable) {
    const enabled = checkedIn
        ? employeeData.capture_check_out_image
        : employeeData.capture_check_in_image;
    return Boolean(enabled) && streamAvailable !== false;
}

patch(KioskConfirmation.prototype, {
    get showVideoStream() {
        return showCameraFor(this.props.employeeData, this.isCheckedIn, this.state.streamAvailable);
    },
});

patch(KioskPinCode.prototype, {
    get showVideoStream() {
        return showCameraFor(this.props.employeeData, this.checkedIn, this.state.streamAvailable);
    },
});
