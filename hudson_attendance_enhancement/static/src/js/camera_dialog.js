/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class CameraDialog extends Component {
    static template = "hudson_attendance_enhancement.CameraDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onConfirm: Function,
        onClose: { type: Function, optional: true },
    };

    setup() {
        this.videoRef = useRef("videoElement");
        this.canvasRef = useRef("canvasElement");
        this.fileInputRef = useRef("fileInputElement");
        this.stream = null;

        this.state = useState({
            isStarting: true,
            isReady: false,
            hasError: false,
            errorMessage: "",
            photoCaptured: null,
            isProcessing: false,
        });

        onMounted(() => {
            this.startCamera();
        });

        onWillUnmount(() => {
            this.stopCamera();
        });
    }

    async startCamera() {
        this.state.isStarting = true;
        this.state.isReady = false;
        this.state.hasError = false;
        this.state.errorMessage = "";

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.state.isStarting = false;
            this.state.hasError = true;
            this.state.errorMessage = _t("Camera API is not supported in this browser. Please use photo upload instead.");
            return;
        }

        try {
            let stream = null;
            try {
                // First try ideal mobile/front camera facing user
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
                    audio: false,
                });
            } catch (constraintErr) {
                // Fallback to any available video input device (desktop webcam / USB cam)
                stream = await navigator.mediaDevices.getUserMedia({
                    video: true,
                    audio: false,
                });
            }

            this.stream = stream;
            const video = this.videoRef.el;
            if (video) {
                video.srcObject = stream;
                video.muted = true;
                video.playsInline = true;

                await new Promise((resolve) => {
                    video.onloadedmetadata = () => {
                        video.play()
                            .then(() => resolve())
                            .catch((err) => {
                                console.warn("Video play error:", err);
                                resolve();
                            });
                    };
                    // Timeout safety
                    setTimeout(resolve, 2000);
                });

                this.state.isReady = true;
                this.state.isStarting = false;
            }
        } catch (err) {
            console.error("Camera access error:", err);
            this.state.isStarting = false;
            this.state.hasError = true;
            if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
                this.state.errorMessage = _t("Camera permission was denied. Please allow camera access in your browser settings, or upload a photo below.");
            } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
                this.state.errorMessage = _t("No camera hardware detected on this device. You can upload a photo instead.");
            } else {
                this.state.errorMessage = _t("Unable to open camera: ") + (err.message || _t("Unknown error"));
            }
        }
    }

    stopCamera() {
        if (this.stream) {
            try {
                this.stream.getTracks().forEach((track) => track.stop());
            } catch (e) {
                console.warn("Error stopping media tracks:", e);
            }
            this.stream = null;
        }
    }

    capturePhoto() {
        const video = this.videoRef.el;
        const canvas = this.canvasRef.el;
        if (!video || !canvas) {
            return;
        }

        const width = video.videoWidth || video.clientWidth || 640;
        const height = video.videoHeight || video.clientHeight || 480;

        canvas.width = width;
        canvas.height = height;

        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, width, height);

        try {
            const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
            const base64Data = dataUrl.split(",")[1];
            this.state.photoCaptured = base64Data;
            this.stopCamera();
        } catch (err) {
            console.error("Failed to capture frame:", err);
        }
    }

    retakePhoto() {
        this.state.photoCaptured = null;
        this.startCamera();
    }

    triggerFileInput() {
        if (this.fileInputRef.el) {
            this.fileInputRef.el.click();
        }
    }

    onFileUpload(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            return;
        }
        this.state.isProcessing = true;

        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = this.canvasRef.el;
                if (!canvas) {
                    this.state.isProcessing = false;
                    return;
                }
                // Scale down if image is too large
                let width = img.width;
                let height = img.height;
                const maxDim = 800;
                if (width > maxDim || height > maxDim) {
                    if (width > height) {
                        height = Math.round((height * maxDim) / width);
                        width = maxDim;
                    } else {
                        width = Math.round((width * maxDim) / height);
                        height = maxDim;
                    }
                }
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext("2d");
                ctx.drawImage(img, 0, 0, width, height);

                const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
                this.state.photoCaptured = dataUrl.split(",")[1];
                this.stopCamera();
                this.state.isProcessing = false;
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    confirmPhoto() {
        if (!this.state.photoCaptured) {
            return;
        }
        const photo = this.state.photoCaptured;
        this.stopCamera();
        if (this.props.onConfirm) {
            this.props.onConfirm(photo);
        }
        if (this.props.close) {
            this.props.close();
        }
    }

    cancelDialog() {
        this.stopCamera();
        if (this.props.onClose) {
            this.props.onClose();
        }
        if (this.props.close) {
            this.props.close();
        }
    }
}
