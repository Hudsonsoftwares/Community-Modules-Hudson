/** @odoo-module **/

import { onWillUnmount, proxy } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { TextField, textField } from "@web/views/fields/text/text_field";

// Each part is a complete recording of its own, transcribed while the next part is being recorded.
// 60 s parts transcribe in about 25 s on CPU, so the transcript keeps up with the conversation.
const SEGMENT_SECONDS = 60;
const MAX_CONVERSATION_SECONDS = 30 * 60;
const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

/**
 * Transcript field of the conversation summary wizard, with consent-gated continuous recording.
 * Audio goes only to this Odoo server (faster-whisper); the text is added to the editable transcript.
 */
export class DentalConversationRecorderField extends TextField {
    static template = "dental_speech.ConversationRecorderField";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.conversation = proxy({
            supported: Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder),
            recording: false,
            pending: 0,
            seconds: 0,
            error: "",
        });
        this.mediaStream = null;
        this.mediaRecorder = null;
        this.mimeType = "";
        this.segmentSeconds = 0;
        this.timer = null;
        this.queue = [];
        this.processing = false;
        onWillUnmount(() => this.releaseMicrophone());
    }

    get record() {
        return this.props.record;
    }

    get showRecorder() {
        return !this.props.readonly && this.record.data.state === "record";
    }

    get hasConsent() {
        return Boolean(this.record.data.patient_consent);
    }

    get elapsedLabel() {
        const s = this.conversation.seconds;
        return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }

    async startRecording() {
        this.conversation.error = "";
        if (!this.hasConsent) {
            this.conversation.error = _t("Confirm the patient's consent before recording.");
            return;
        }
        if (!window.isSecureContext) {
            this.conversation.error = _t(
                "The browser only allows the microphone on HTTPS or localhost. Open Odoo over HTTPS to record."
            );
            return;
        }
        if (!this.conversation.supported) {
            this.conversation.error = _t("This browser does not support audio recording.");
            return;
        }
        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
            this.conversation.error =
                err?.name === "NotAllowedError"
                    ? _t("Microphone access was denied. Allow the microphone for this site and try again.")
                    : _t("No microphone could be opened: %s", err?.message || err);
            return;
        }
        this.mimeType = PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
        this.conversation.recording = true;
        this.conversation.seconds = 0;
        this.startSegment();
        this.timer = setInterval(() => {
            this.conversation.seconds++;
            this.segmentSeconds++;
            if (this.conversation.seconds >= MAX_CONVERSATION_SECONDS) {
                this.stopRecording();
            } else if (this.segmentSeconds >= SEGMENT_SECONDS) {
                this.rotateSegment();
            }
        }, 1000);
    }

    startSegment() {
        const chunks = [];
        const recorder = new MediaRecorder(this.mediaStream, this.mimeType ? { mimeType: this.mimeType } : undefined);
        recorder.ondataavailable = (ev) => ev.data?.size && chunks.push(ev.data);
        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
            if (blob.size) {
                this.queue.push(blob);
                this.conversation.pending = this.queue.length + (this.processing ? 1 : 0);
                this.processQueue();
            }
            if (!this.conversation.recording && this.mediaRecorder === recorder) {
                this.releaseStream(); // last part finished: turn the browser's microphone indicator off
            }
        };
        recorder.start(1000);
        this.mediaRecorder = recorder;
        this.segmentSeconds = 0;
    }

    rotateSegment() {
        const previous = this.mediaRecorder;
        this.startSegment(); // start the next part first so the gap between parts stays minimal
        if (previous?.state === "recording") {
            previous.stop();
        }
    }

    stopRecording() {
        clearInterval(this.timer);
        this.conversation.recording = false;
        if (this.mediaRecorder?.state === "recording") {
            this.mediaRecorder.stop(); // continues in onstop, which also releases the microphone
        } else {
            this.releaseStream();
        }
    }

    releaseStream() {
        this.mediaStream?.getTracks().forEach((track) => track.stop());
        this.mediaStream = null;
    }

    releaseMicrophone() {
        clearInterval(this.timer);
        this.conversation.recording = false;
        if (this.mediaRecorder?.state === "recording") {
            this.mediaRecorder.onstop = null; // closing the dialog drops the unfinished part
            this.mediaRecorder.stop();
        }
        this.mediaRecorder = null;
        this.releaseStream();
        this.queue = [];
    }

    async processQueue() {
        if (this.processing) {
            return;
        }
        this.processing = true;
        try {
            while (this.queue.length) {
                const blob = this.queue.shift();
                this.conversation.pending = this.queue.length + 1;
                await this.transcribe(blob);
            }
        } finally {
            this.processing = false;
            this.conversation.pending = 0;
        }
    }

    async transcribe(blob) {
        try {
            // The server checks the saved consent, so the wizard must be saved first
            if (!(await this.record.save())) {
                this.conversation.error = _t("The conversation could not be saved for transcription.");
                return;
            }
            const result = await this.orm.call(
                "dental.conversation.summary.wizard",
                "action_transcribe_chunk",
                [[this.record.resId]],
                { audio_b64: await this.blobToBase64(blob), mime_type: blob.type }
            );
            if (result.text) {
                await this.appendText(result.text);
            }
        } catch (err) {
            this.conversation.error = err?.data?.message || err?.message || _t("Transcription failed.");
        }
    }

    async appendText(text) {
        // Start from what is in the box: it may hold edits not yet committed to the record
        const current = (this.textareaRef()?.value ?? this.value).trimEnd();
        await this.record.update({ [this.props.name]: current ? `${current}\n${text}` : text });
        await this.record.save();
    }

    blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
        });
    }
}

export const dentalConversationRecorderField = {
    ...textField,
    component: DentalConversationRecorderField,
    displayName: _t("Conversation Transcript with Recording"),
    supportedTypes: ["text"],
    fieldDependencies: [
        { name: "state", type: "selection" },
        { name: "patient_consent", type: "boolean" },
    ],
};

registry.category("fields").add("dental_conversation_recorder", dentalConversationRecorderField);
