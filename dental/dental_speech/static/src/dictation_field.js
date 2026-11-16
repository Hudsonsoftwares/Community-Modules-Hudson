/** @odoo-module **/

import { onWillStart, onWillUnmount, proxy } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { TextField, textField } from "@web/views/fields/text/text_field";

// Auto-stop: 2 minutes transcribes in about 50 s on CPU, well within Odoo's 120 s request limit
const MAX_RECORDING_SECONDS = 120;
const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

/**
 * Clinical notes text field with local voice dictation.
 * The audio goes only to this Odoo server (faster-whisper); the doctor reviews and edits the
 * transcription before it is added to the notes, which are then saved with the form as usual.
 */
export class DentalDictationField extends TextField {
    static template = "dental_speech.DictationField";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dictation = proxy({
            allowed: false,
            supported: Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder),
            recording: false,
            transcribing: false,
            seconds: 0,
            transcript: null,
            languageNote: "",
            error: "",
        });
        this.mediaRecorder = null;
        this.mediaStream = null;
        this.chunks = [];
        this.timer = null;

        onWillStart(async () => {
            const [dentist, manager] = await Promise.all([
                user.hasGroup("dental_base.group_dental_dentist"),
                user.hasGroup("dental_base.group_dental_manager"),
            ]);
            this.dictation.allowed = dentist || manager;
        });
        onWillUnmount(() => this.releaseMicrophone());
    }

    get showDictation() {
        return this.dictation.allowed && !this.props.readonly;
    }

    get elapsedLabel() {
        const s = this.dictation.seconds;
        return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }

    async startRecording() {
        this.dictation.error = "";
        if (!window.isSecureContext) {
            this.dictation.error = _t(
                "The browser only allows the microphone on HTTPS or localhost. Open Odoo over HTTPS to dictate."
            );
            return;
        }
        if (!this.dictation.supported) {
            this.dictation.error = _t("This browser does not support audio recording.");
            return;
        }
        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
            this.dictation.error =
                err?.name === "NotAllowedError"
                    ? _t("Microphone access was denied. Allow the microphone for this site and try again.")
                    : _t("No microphone could be opened: %s", err?.message || err);
            return;
        }
        const mimeType = PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
        this.chunks = [];
        this.mediaRecorder = new MediaRecorder(this.mediaStream, mimeType ? { mimeType } : undefined);
        this.mediaRecorder.ondataavailable = (ev) => ev.data?.size && this.chunks.push(ev.data);
        this.mediaRecorder.onstop = () => this.onRecordingStopped();
        this.mediaRecorder.start(1000);
        this.dictation.recording = true;
        this.dictation.seconds = 0;
        this.timer = setInterval(() => {
            this.dictation.seconds++;
            if (this.dictation.seconds >= MAX_RECORDING_SECONDS) {
                this.stopRecording();
            }
        }, 1000);
    }

    stopRecording() {
        if (this.mediaRecorder?.state === "recording") {
            this.mediaRecorder.stop(); // continues in onRecordingStopped
        }
        this.dictation.recording = false;
        clearInterval(this.timer);
    }

    releaseMicrophone() {
        clearInterval(this.timer);
        if (this.mediaRecorder?.state === "recording") {
            this.mediaRecorder.onstop = null;
            this.mediaRecorder.stop();
        }
        this.mediaStream?.getTracks().forEach((track) => track.stop());
        this.mediaStream = null;
        this.mediaRecorder = null;
        this.chunks = [];
    }

    async onRecordingStopped() {
        const mimeType = this.mediaRecorder?.mimeType || "audio/webm";
        const blob = new Blob(this.chunks, { type: mimeType });
        this.releaseMicrophone(); // turns the browser's microphone indicator off
        if (!blob.size) {
            this.dictation.error = _t("Nothing was recorded. Please try again.");
            return;
        }
        this.dictation.transcribing = true;
        try {
            const audioB64 = await this.blobToBase64(blob);
            const resId = this.props.record.resId;
            const result = await this.orm.call(
                "dental.case",
                "dental_transcribe_audio",
                [resId ? [resId] : []],
                { audio_b64: audioB64, mime_type: mimeType }
            );
            if (!result.text) {
                this.dictation.error = _t("No speech was recognised. Please speak closer to the microphone.");
            } else {
                this.dictation.transcript = result.text;
                this.dictation.languageNote = this.languageNote(result);
            }
        } catch (err) {
            this.dictation.error = err?.data?.message || err?.message || _t("Transcription failed.");
        } finally {
            this.dictation.transcribing = false;
        }
    }

    languageNote(result) {
        if (!result.language_name) {
            return "";
        }
        return result.translated && result.language !== "en"
            ? _t("Spoken in %s, written in English", result.language_name)
            : _t("Language: %s", result.language_name);
    }

    blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
        });
    }

    onTranscriptInput(ev) {
        this.dictation.transcript = ev.target.value;
    }

    async insertTranscript() {
        const text = (this.dictation.transcript || "").trim();
        if (!text) {
            this.discardTranscript();
            return;
        }
        // Start from what is in the box (it may hold typing not yet committed to the record)
        const current = (this.textareaRef()?.value ?? this.value).trimEnd();
        const value = current ? `${current}\n\n${text}` : text;
        await this.props.record.update({ [this.props.name]: value });
        this.dictation.transcript = null;
        this.notification.add(_t("Dictation added to the clinical notes. Save the consultation to keep it."), {
            type: "success",
        });
    }

    discardTranscript() {
        this.dictation.transcript = null;
    }
}

export const dentalDictationField = {
    ...textField,
    component: DentalDictationField,
    displayName: _t("Clinical Notes with Voice Dictation"),
    supportedTypes: ["text"],
};

registry.category("fields").add("dental_dictation", dentalDictationField);
