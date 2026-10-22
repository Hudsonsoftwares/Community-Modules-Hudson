/** @odoo-module **/
/*
 * Face enrolment widget for the HR-admin enrolment wizard.
 *
 * OWL component that renders inside the eh.hr.face.enrolment form,
 * bound to the samples_json field. Captures three to five face
 * embeddings using face-api.js (loaded on demand) and stores them
 * as a JSON array in the bound field.
 *
 * The widget runs only when the wizard is opened by an HR admin from
 * an employee record, so face-api.js may not be loaded yet (the
 * backend bundle excludes it). The widget injects a script tag on
 * first use.
 */
import { Component, onMounted, onWillUnmount, proxy, signal, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

// Local copies first (vendored by the operator per
// static/lib/face-api/README.md), then the pinned immutable CDN build
// as a fallback so the wizard still works out of the box. The setup
// message names the fetch script when both fail.
const FACE_API_URL = "/eh_hr_face_kiosk/static/lib/face-api/face-api.min.js";
const MODEL_URL = "/eh_hr_face_kiosk/static/lib/face-api/models";
const CDN_FACE_API_URL = "https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/dist/face-api.min.js";
const CDN_MODEL_URL = "https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/weights";
const SETUP_HINT =
    "face-api.js could not be loaded from this server or the CDN. " +
    "Run eh_hr_face_kiosk/tools/fetch_face_api.sh on the Odoo server " +
    "(see static/lib/face-api/README.md), then reopen this wizard.";
const TARGET_SAMPLES = 5;

function injectScript(src) {
    return new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = src;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error(`script failed to load: ${src}`));
        document.head.appendChild(s);
    });
}

async function loadFaceApi() {
    if (window.faceapi) return;
    try {
        await injectScript(FACE_API_URL);
    } catch {
        await injectScript(CDN_FACE_API_URL).catch(() => {
            throw new Error(SETUP_HINT);
        });
    }
    if (!window.faceapi) {
        throw new Error(SETUP_HINT);
    }
}

async function loadNetsFrom(url) {
    await Promise.all([
        window.faceapi.nets.tinyFaceDetector.loadFromUri(url),
        window.faceapi.nets.faceLandmark68Net.loadFromUri(url),
        window.faceapi.nets.faceRecognitionNet.loadFromUri(url),
    ]);
}

async function loadModels() {
    try {
        await loadNetsFrom(MODEL_URL);
    } catch {
        await loadNetsFrom(CDN_MODEL_URL).catch(() => {
            throw new Error(SETUP_HINT);
        });
    }
}

function l2norm(arr) {
    let s = 0;
    for (const v of arr) s += v * v;
    const n = Math.sqrt(s);
    if (n === 0) return Array.from(arr);
    return Array.from(arr, (v) => v / n);
}

class FaceEnrolWidget extends Component {
    static template = "eh_hr_face_kiosk.FaceEnrolWidget";
    props = useProps(standardFieldProps);
    videoRef = signal.ref();

    get isStartDisabled() {
        return this.state.running || !this.state.ready;
    }

    setup() {
        this.state = proxy({
            ready: false,
            error: "",
            status: _t("Click Start to begin"),
            samples: [],
            running: false,
            stream: null,
        });

        onMounted(async () => {
            try {
                await loadFaceApi();
                await loadModels();
                this.state.ready = true;
                this.state.status = _t("Ready. Click Start.");
            } catch (e) {
                this.state.error = e.message;
            }
        });

        onWillUnmount(() => this._stopCamera());
    }

    async _startCamera() {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
            audio: false,
        });
        this.state.stream = stream;
        this.videoRef().srcObject = stream;
        await new Promise((r) => (this.videoRef().onloadedmetadata = r));
    }
    _stopCamera() {
        if (this.state.stream) {
            this.state.stream.getTracks().forEach((t) => t.stop());
            this.state.stream = null;
        }
        if (this.videoRef()) this.videoRef().srcObject = null;
    }

    async onStart() {
        if (this.state.running) return;
        this.state.error = "";
        this.state.samples = [];
        this.state.running = true;
        try {
            await this._startCamera();
            const opts = new window.faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 });
            for (let i = 0; i < TARGET_SAMPLES; i++) {
                this.state.status = _t("Capturing sample %s of %s...").replace("%s", i + 1).replace("%s", TARGET_SAMPLES);
                let result = null;
                const deadline = Date.now() + 4000;
                while (Date.now() < deadline) {
                    result = await window.faceapi
                        .detectSingleFace(this.videoRef(), opts)
                        .withFaceLandmarks()
                        .withFaceDescriptor();
                    if (result && result.descriptor) break;
                    await new Promise((r) => setTimeout(r, 200));
                }
                if (!result || !result.descriptor) {
                    this.state.status = _t("Sample %s timed out, retrying").replace("%s", i + 1);
                    i--;
                    continue;
                }
                this.state.samples.push({
                    embedding: l2norm(Array.from(result.descriptor)),
                    quality: result.detection ? result.detection.score : null,
                });
                this._writeBack();
                await new Promise((r) => setTimeout(r, 800));
            }
            this.state.status = _t("Captured %s samples. Save the wizard to enrol.").replace("%s", this.state.samples.length);
        } catch (e) {
            this.state.error = e.message;
        } finally {
            this._stopCamera();
            this.state.running = false;
        }
    }

    _writeBack() {
        this.props.record.update({ [this.props.name]: JSON.stringify(this.state.samples) });
    }
}

registry.category("fields").add("eh_face_enrol_widget", { component: FaceEnrolWidget });
