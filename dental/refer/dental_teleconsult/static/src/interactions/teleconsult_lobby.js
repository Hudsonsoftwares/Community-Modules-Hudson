import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * Online consultation waiting room: device test, and status polling so the page follows the
 * visit (payment received, room opened, admitted by the doctor) without manual refresh.
 */
export class DentalTeleconsultLobby extends Interaction {
    static selector = ".o_dental_teleconsult_lobby";
    dynamicContent = {
        ".o_dental_tc_test_devices": { "t-on-click": this.onTestDevices },
    };

    setup() {
        this.stage = this.el.dataset.stage;
        this.statusUrl = this.el.dataset.statusUrl;
        this.stream = null;
        this.registerCleanup(() => this.stopStream());
    }

    start() {
        if (!window.isSecureContext) {
            this.el.querySelector(".o_dental_tc_insecure")?.classList.remove("d-none");
        }
        if (this.stage === "in_call") {
            const join = this.el.querySelector(".o_dental_tc_join");
            if (join) {
                this.waitForTimeout(() => (window.location.href = join.href), 800);
            }
            return;
        }
        const interval = parseInt(this.el.dataset.pollInterval || "0", 10);
        if (interval > 0) {
            this.setSafeInterval(() => this.poll(), interval);
        }
    }

    async poll() {
        let data;
        try {
            const response = await this.waitFor(fetch(this.statusUrl, { credentials: "same-origin" }));
            if (!response.ok) {
                return;
            }
            data = await this.waitFor(response.json());
        } catch {
            return; // offline for a moment: try again on the next tick
        }
        if (!data || data.stage === this.stage) {
            return;
        }
        if (data.stage === "in_call" && data.room_url) {
            this.stopStream();
            window.location.href = data.room_url;
        } else {
            window.location.reload();
        }
    }

    async onTestDevices() {
        const status = this.el.querySelector(".o_dental_tc_device_status");
        if (!navigator.mediaDevices?.getUserMedia) {
            status.textContent = "This browser cannot access a camera. Please use a recent browser over https.";
            status.className = "small mt-2 o_dental_tc_device_status text-danger";
            return;
        }
        try {
            this.stopStream();
            this.stream = await this.waitFor(
                navigator.mediaDevices.getUserMedia({ video: true, audio: true })
            );
            const video = this.el.querySelector(".o_dental_tc_preview");
            video.srcObject = this.stream;
            this.el.querySelector(".o_dental_tc_preview_wrap").classList.remove("d-none");
            const hasAudio = this.stream.getAudioTracks().length > 0;
            status.textContent = hasAudio
                ? "Camera and microphone are working."
                : "Camera works, but no microphone was found.";
            status.className = `small mt-2 o_dental_tc_device_status ${hasAudio ? "text-success" : "text-warning"}`;
        } catch (error) {
            status.textContent =
                error?.name === "NotAllowedError"
                    ? "Camera/microphone access was blocked. Allow it in your browser settings and try again."
                    : "No camera or microphone could be started on this device.";
            status.className = "small mt-2 o_dental_tc_device_status text-danger";
        }
    }

    stopStream() {
        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
    }
}

registry.category("public.interactions").add("dental_teleconsult.lobby", DentalTeleconsultLobby);
