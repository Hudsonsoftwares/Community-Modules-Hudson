/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, proxy } from "@odoo/owl";

export class WaitingQueueBoard extends Component {
    static template = "dental_core.WaitingQueueBoard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = proxy({
            loading: true,
            clinic_name: "DenBell Multi-Speciality Dental Hospital",
            clinic_address: "Main Clinic & Dental Surgery",
            stats: {
                total_patients_today: 0,
                now_serving_count: 0,
                waiting_count: 0,
                completed_count: 0,
            },
            doctors: [],
            is_tv_mode: false,
            auto_refresh: true,
            sound_enabled: true,
            currentTimeStr: "",
            currentDateStr: "",
            lastSyncStr: "Just now",
        });

        this.updateClock();

        onWillStart(async () => {
            await this.loadQueueData();
        });

        onMounted(() => {
            // Live clock ticker every second
            this.clockInterval = setInterval(() => this.updateClock(), 1000);

            // Auto-refresh queue data every 8 seconds
            this.refreshInterval = setInterval(() => {
                if (this.state.auto_refresh) {
                    this.loadQueueData(false);
                }
            }, 8000);

            // Fullscreen change listener
            this.onFullscreenChange = () => {
                this.state.is_tv_mode = !!document.fullscreenElement;
            };
            document.addEventListener("fullscreenchange", this.onFullscreenChange);
        });

        onWillUnmount(() => {
            if (this.clockInterval) clearInterval(this.clockInterval);
            if (this.refreshInterval) clearInterval(this.refreshInterval);
            document.removeEventListener("fullscreenchange", this.onFullscreenChange);
        });
    }

    updateClock() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: true,
        });
        const dateStr = now.toLocaleDateString("en-US", {
            weekday: "short",
            day: "numeric",
            month: "short",
            year: "numeric",
        });
        this.state.currentTimeStr = timeStr;
        this.state.currentDateStr = dateStr;
    }

    async loadQueueData(showLoader = true) {
        if (showLoader) {
            this.state.loading = true;
        }
        try {
            const data = await this.orm.call("dental.appointment", "get_waiting_queue_board_data", []);
            if (data) {
                if (data.clinic_name) this.state.clinic_name = data.clinic_name;
                if (data.clinic_address) this.state.clinic_address = data.clinic_address;
                if (data.stats) Object.assign(this.state.stats, data.stats);
                if (data.doctors) this.state.doctors = data.doctors;
                this.state.lastSyncStr = new Date().toLocaleTimeString("en-US", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                });
            }
        } catch (err) {
            console.error("Failed to load queue board data:", err);
        } finally {
            if (showLoader) {
                this.state.loading = false;
            }
        }
    }

    // Play polite 2-tone clinic chime using Web Audio API
    playChime() {
        if (!this.state.sound_enabled) return;
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const ctx = new AudioContext();

            const playTone = (freq, start, duration) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.setValueAtTime(freq, ctx.currentTime + start);

                gain.gain.setValueAtTime(0.001, ctx.currentTime + start);
                gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + start + 0.05);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + duration);

                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(ctx.currentTime + start);
                osc.stop(ctx.currentTime + start + duration);
            };

            // Two pleasant harmonics: C5 (523.25Hz) then E5 (659.25Hz)
            playTone(523.25, 0, 0.4);
            playTone(659.25, 0.25, 0.6);
        } catch (e) {
            // AudioContext restricted before user gesture
        }
    }

    toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch((err) => {
                console.warn(`Error attempting to enable fullscreen: ${err.message}`);
            });
            this.state.is_tv_mode = true;
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            }
            this.state.is_tv_mode = false;
        }
    }

    toggleAutoRefresh() {
        this.state.auto_refresh = !this.state.auto_refresh;
    }

    toggleSound() {
        this.state.sound_enabled = !this.state.sound_enabled;
        if (this.state.sound_enabled) {
            this.playChime();
        }
    }

    async callNextPatient(appt) {
        if (!appt || !appt.id) return;
        try {
            await this.orm.call("dental.appointment", "action_start_consultation", [[appt.id]]);
            this.playChime();
            if (this.notification) {
                this.notification.add(`Token ${appt.token} (${appt.patient_name}) called into operatory!`, {
                    title: "Patient Called",
                    type: "success",
                });
            }
            await this.loadQueueData(false);
        } catch (err) {
            console.error("Failed to call patient:", err);
        }
    }

    async checkInPatient(appt) {
        if (!appt || !appt.id) return;
        try {
            await this.orm.call("dental.appointment", "action_check_in", [[appt.id]]);
            if (this.notification) {
                this.notification.add(`Patient ${appt.patient_name} checked in to queue!`, {
                    type: "info",
                });
            }
            await this.loadQueueData(false);
        } catch (err) {
            console.error("Failed to check in patient:", err);
        }
    }

    async completeVisit(appt) {
        if (!appt || !appt.id) return;
        try {
            await this.orm.call("dental.appointment", "action_complete", [[appt.id]]);
            if (this.notification) {
                this.notification.add(`Appointment for ${appt.patient_name} marked Completed.`, {
                    type: "success",
                });
            }
            await this.loadQueueData(false);
        } catch (err) {
            console.error("Failed to complete appointment:", err);
        }
    }

    openAppointment(apptId) {
        if (!apptId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dental.appointment",
            res_id: apptId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPatient(patientId) {
        if (!patientId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: patientId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    switchToList() {
        this.action.doAction("dental_core.action_reception_checked_in");
    }
}

registry.category("actions").add("dental_core.waiting_queue_board", WaitingQueueBoard);
