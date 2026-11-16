/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, onWillUnmount, proxy } from "@odoo/owl";

const REFRESH_MS = 8000;
const ANNOUNCE_MS = 12000;

export class WaitingQueueBoard extends Component {
    static template = "dental_core.WaitingQueueBoard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = proxy({
            loading: true,
            busyId: null,
            canStartConsultation: false,
            clinic_name: "",
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
            sound_enabled: false, // true only while the speaker button is calling a token
            callingKey: null, // "all" (header speaker) or a doctor_id (card speaker) while calling
            currentTimeStr: "",
            currentDateStr: "",
            lastSyncStr: "",
            announcement: null, // { token, patient_name, doctor_name, operatory_name, accent_color }
        });

        // Last "now serving" token per doctor, used to announce newly called patients
        this.servingTokens = null;

        this.updateClock();

        onWillStart(async () => {
            await this.loadQueueData();
        });

        onMounted(() => {
            this.clockInterval = setInterval(() => this.updateClock(), 1000);
            this.refreshInterval = setInterval(() => {
                if (this.state.auto_refresh) {
                    this.loadQueueData(false);
                }
            }, REFRESH_MS);
            this.onFullscreenChange = () => {
                this.state.is_tv_mode = !!document.fullscreenElement;
            };
            document.addEventListener("fullscreenchange", this.onFullscreenChange);
        });

        onWillUnmount(() => {
            clearInterval(this.clockInterval);
            clearInterval(this.refreshInterval);
            this.stopCalling();
            clearTimeout(this.announceTimeout);
            document.removeEventListener("fullscreenchange", this.onFullscreenChange);
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    updateClock() {
        const now = new Date();
        this.state.currentTimeStr = now.toLocaleTimeString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: true,
        });
        this.state.currentDateStr = now.toLocaleDateString("en-US", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
        });
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
                if (data.doctors) {
                    this.detectNewCalls(data.doctors);
                    this.state.doctors = data.doctors;
                    this.state.canStartConsultation = Boolean(data.can_start_consultation);
                    this.state.canCheckIn = Boolean(data.can_check_in);
                }
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

    /** Announce (banner + chime) any token that started being served since the last refresh. */
    detectNewCalls(doctors) {
        const current = {};
        for (const doc of doctors) {
            current[doc.doctor_id] = doc.now_serving ? doc.now_serving.token : null;
        }
        if (this.servingTokens) {
            const called = doctors.find(
                (doc) => doc.now_serving && this.servingTokens[doc.doctor_id] !== doc.now_serving.token
            );
            if (called) {
                this.announce(called, called.now_serving);
            }
        }
        this.servingTokens = current;
    }

    announce(doc, appt) {
        this.state.announcement = {
            token: appt.token,
            patient_name: appt.patient_name,
            doctor_name: doc.doctor_name,
            operatory_name: doc.operatory_name,
            accent_color: doc.accent_color,
        };
        this.playChime();
        clearTimeout(this.announceTimeout);
        this.announceTimeout = setTimeout(() => {
            this.state.announcement = null;
        }, ANNOUNCE_MS);
    }

    dismissAnnouncement() {
        clearTimeout(this.announceTimeout);
        this.state.announcement = null;
    }

    // ------------------------------------------------------------------
    // Display helpers
    // ------------------------------------------------------------------

    /** On the public TV screen only first name + last initial is shown (patient privacy). */
    displayName(name) {
        if (!this.state.is_tv_mode || !name) {
            return name;
        }
        const parts = name.trim().split(/\s+/);
        return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : parts[0];
    }

    initials(name) {
        return (name || "")
            .replace(/^dr\.?\s+/i, "")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((p) => p[0].toUpperCase())
            .join("");
    }

    formatWait(mins) {
        if (!mins) {
            return "Just arrived";
        }
        return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
    }

    waitLevel(mins) {
        if (mins >= 45) {
            return "is-critical";
        }
        return mins >= 25 ? "is-long" : "";
    }

    get boardLayoutClass() {
        const count = this.state.doctors.length;
        return count === 1 ? "layout-single" : count === 2 ? "layout-double" : "layout-multi";
    }

    // ------------------------------------------------------------------
    // Sound / modes
    // ------------------------------------------------------------------

    // Polite 2-tone clinic chime using Web Audio API
    playChime() {
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
        } catch {
            // AudioContext restricted before user gesture
        }
    }

    /** "A05" -> "A 0 5" so the engine reads each character instead of a word/number. */
    spellToken(token) {
        return String(token || "")
            .replace(/[-_]/g, " ")
            .split("")
            .join(" ")
            .replace(/\s+/g, " ")
            .trim();
    }

    /** Speak the text once; turns the speaker back off when finished. */
    speak(text) {
        if (!text || !("speechSynthesis" in window)) {
            this.state.sound_enabled = false;
            return;
        }
        try {
            const utter = new SpeechSynthesisUtterance(text);
            const voices = window.speechSynthesis.getVoices();
            const voice =
                voices.find((v) => v.lang === "en-IN") ||
                voices.find((v) => v.lang && v.lang.startsWith("en"));
            if (voice) utter.voice = voice;
            utter.lang = voice ? voice.lang : "en-IN";
            utter.rate = 0.9;
            utter.pitch = 1;
            utter.volume = 1;
            const done = () => {
                if (this.currentUtterance === utter) {
                    this.stopCalling();
                }
            };
            utter.onend = done;
            utter.onerror = done;
            this.currentUtterance = utter;
            window.speechSynthesis.speak(utter);
            // Safety net: some browsers never fire onend
            clearTimeout(this.speakSafetyTimeout);
            this.speakSafetyTimeout = setTimeout(done, 4000 + text.length * 120);
        } catch {
            this.stopCalling();
        }
    }

    /** Stop any announcement in progress and switch the speaker back off. */
    stopCalling() {
        clearTimeout(this.speakTimeout);
        clearTimeout(this.speakSafetyTimeout);
        this.currentUtterance = null;
        this.state.sound_enabled = false;
        this.state.callingKey = null;
        try {
            if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        } catch {
            // ignore
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

    /**
     * Speaker button (on/off):
     *  - Off -> On: says the token number once (patient in consultation per doctor,
     *    or that doctor's next waiting patient), then switches itself back off.
     *  - On -> Off: stops the announcement immediately.
     *
     * @param {Object} [onlyDoc] when given, call only this doctor's token (card speaker);
     *                           otherwise call every doctor's token (header speaker).
     */
    callPatients(onlyDoc = null) {
        const key = onlyDoc ? onlyDoc.doctor_id : "all";
        const wasCallingThis = this.state.sound_enabled && this.state.callingKey === key;
        if (this.state.sound_enabled) {
            this.stopCalling();
        }
        if (wasCallingThis) {
            return; // second click on the same button = stop
        }
        const calls = [];
        for (const doc of onlyDoc ? [onlyDoc] : this.state.doctors || []) {
            const appt = doc.now_serving || (doc.waiting_queue && doc.waiting_queue[0]);
            if (appt && appt.token) {
                calls.push({ doc, appt });
            }
        }
        if (!calls.length) {
            const who = onlyDoc ? `${onlyDoc.doctor_name} has no` : "No";
            this.notification.add(`${who} patient waiting or in consultation to call.`, { type: "info" });
            return;
        }
        this.state.sound_enabled = true;
        this.state.callingKey = key;
        this.announce(calls[0].doc, calls[0].appt);
        const text = calls.map(({ appt }) => `Token number ${this.spellToken(appt.token)}`).join(". ");
        // Speak once, right after the chime
        clearTimeout(this.speakTimeout);
        this.speakTimeout = setTimeout(() => this.speak(text), 900);
    }

    // ------------------------------------------------------------------
    // Reception actions
    // ------------------------------------------------------------------

    async _run(appt, method, message, type = "success") {
        if (!appt || !appt.id || this.state.busyId) return;
        this.state.busyId = appt.id;
        try {
            await this.orm.call("dental.appointment", method, [[appt.id]]);
            this.notification.add(message, { type });
            await this.loadQueueData(false);
        } finally {
            this.state.busyId = null;
        }
    }

    callNextPatient(appt) {
        return this._run(appt, "action_start_consultation", `Token ${appt.token} (${appt.patient_name}) called in.`);
    }

    checkInPatient(appt) {
        return this._run(appt, "action_check_in", `${appt.patient_name} checked in to the queue.`, "info");
    }

    completeVisit(appt) {
        return this._run(appt, "action_complete", `Visit completed for ${appt.patient_name}.`);
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
