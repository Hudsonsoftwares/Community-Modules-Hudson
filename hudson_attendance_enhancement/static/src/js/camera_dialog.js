/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";

export class CameraDialog extends Component {
    static template = "hudson_attendance_enhancement.CameraDialog";

    setup() {
        this.videoRef = useRef("videoElement");
        this.canvasRef = useRef("canvasElement");
        this.stream = null;

        onMounted(async () => {
            try {
                this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
                if (this.videoRef.el) {
                    this.videoRef.el.srcObject = this.stream;
                }
            } catch (err) {
                console.error("Error accessing camera:", err);
                // Can fallback to normal confirm here if needed, but for now we throw error or close
            }
        });

        onWillUnmount(() => {
            this.stopCamera();
        });
    }

    stopCamera() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
    }

    capturePhoto() {
        const video = this.videoRef.el;
        const canvas = this.canvasRef.el;
        if (!video || !canvas) return;

        // Set canvas size to match video feed
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        
        // Draw frame to canvas
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        
        // Convert to base64
        const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
        const base64Data = dataUrl.split(",")[1]; // Remove prefix 'data:image/jpeg;base64,'

        this.stopCamera();
        
        // Call the parent confirm method with the photo
        this.props.onConfirm(base64Data);
    }
}
