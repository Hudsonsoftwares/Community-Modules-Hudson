/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export const wfhTrackingService = {
    dependencies: ["notification"],
    start(env, { notification }) {
        let trackingIntervalId = null;

        async function sendLocationPing() {
            if (!navigator.geolocation) {
                return;
            }

            navigator.geolocation.getCurrentPosition(
                async (position) => {
                    try {
                        const latitude = position.coords.latitude;
                        const longitude = position.coords.longitude;
                        const accuracy = position.coords.accuracy || 0.0;

                        await rpc("/hudson_attendance/wfh_heartbeat", {
                            latitude,
                            longitude,
                            accuracy,
                        });
                    } catch (err) {
                        console.warn("[WFH Tracking] Heartbeat ping failed:", err);
                    }
                },
                (err) => {
                    console.warn("[WFH Tracking] Geolocation error:", err.message);
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 60000,
                }
            );
        }

        async function checkAndScheduleTracking() {
            try {
                const userData = await rpc("/hr_attendance/attendance_user_data");
                if (userData && userData.wfh_enabled && userData.attendance_state === "checked_in") {
                    // Send an initial ping immediately
                    sendLocationPing();

                    // Clear previous timer if any
                    if (trackingIntervalId) {
                        clearInterval(trackingIntervalId);
                    }

                    const minutes = Math.max(userData.wfh_interval || 10, 1);
                    const ms = minutes * 60 * 1000;
                    trackingIntervalId = setInterval(sendLocationPing, ms);
                } else {
                    if (trackingIntervalId) {
                        clearInterval(trackingIntervalId);
                        trackingIntervalId = null;
                    }
                }
            } catch (e) {
                // Not logged in or attendance user data endpoint unavailable
            }
        }

        // Initialize tracking check on startup
        setTimeout(checkAndScheduleTracking, 5000);

        // Also check periodically in case of attendance state changes
        setInterval(checkAndScheduleTracking, 60000);

        return {
            triggerPingNow: sendLocationPing,
        };
    },
};

registry.category("services").add("wfh_tracking", wfhTrackingService);
