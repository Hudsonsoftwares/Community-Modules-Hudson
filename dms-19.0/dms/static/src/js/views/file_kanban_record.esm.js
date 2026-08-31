// /** ********************************************************************************
//     Copyright 2024 Subteno - Timothée Vannier (https://www.subteno.com).
//     License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
//  **********************************************************************************/
import {KanbanRecord} from "@web/views/kanban/kanban_record";
import {useFileViewer} from "@web/core/file_viewer/file_viewer_hook";
import {useService} from "@web/core/utils/hooks";
import {loadPDFJSAssets} from "@web/core/utils/pdfjs";

const { onMounted } = owl;
const videoReadableTypes = ["x-matroska", "mp4", "webm"];
const audioReadableTypes = ["mp3", "ogg", "wav", "aac", "mpa", "flac", "m4a"];

export class FileKanbanRecord extends KanbanRecord {
    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.fileViewer = useFileViewer();

        onMounted(() => {
            if (this.props.record.data.mimetype === "application/pdf") {
                this.renderPdfThumbnail();
            }
        });
    }

    async renderPdfThumbnail() {
        if (!this.rootRef?.el) return;
        const canvas = this.rootRef.el.querySelector("canvas.dms_pdf_thumbnail_canvas");
        if (!canvas) return;

        try {
            await loadPDFJSAssets();
            const loadingTask = window.pdfjsLib.getDocument({
                url: `/web/content/dms.file/${this.props.record.resId}/content`,
                cMapUrl: '/web/static/lib/pdfjs/build/pdf.js/web/cmaps/',
                cMapPacked: true,
                standardFontDataUrl: '/web/static/lib/pdfjs/build/pdf.js/web/standard_fonts/',
                renderInteractiveForms: true,
            });
            const pdf = await loadingTask.promise;
            const page = await pdf.getPage(1);

            const viewport = page.getViewport({ scale: 1.0 });
            const scale = Math.min(1.5, 200 / viewport.width);
            const scaledViewport = page.getViewport({ scale: scale });

            const context = canvas.getContext("2d");
            canvas.height = scaledViewport.height;
            canvas.width = scaledViewport.width;

            await page.render({ 
                canvasContext: context, 
                viewport: scaledViewport,
                intent: 'print',
                annotationMode: 2 // ENABLE_FORMS
            }).promise;
        } catch (e) {
            console.error("Failed to render PDF thumbnail", e);
        }
    }

    isVideo(mimetype) {
        return videoReadableTypes.includes(mimetype);
    }

    isAudio(mimetype) {
        return audioReadableTypes.includes(mimetype);
    }

    /**
     * @override
     *
     * Top half (preview thumbnail): Opens previewer.
     * Bottom half (name / metadata): Toggles document selection natively.
     */
    onGlobalClick(ev) {
        if (
            ev.target.closest(".o_kanban_manage_toggle_button") ||
            ev.target.closest(".o_dropdown_menu") ||
            ev.target.closest("button") ||
            ev.target.closest("a[type]")
        ) {
            return super.onGlobalClick(ev);
        }

        // 1. Top half: Document preview
        if (ev.target.closest(".o_kanban_dms_file_preview")) {
            const self = this;
            let file_type = "";
            if (self.props.record.data.name) {
                const parts = self.props.record.data.name.split(".");
                if (parts.length > 1) {
                    file_type = parts[parts.length - 1];
                }
            }
            let mimetype = "";

            if (self.isVideo(file_type)) {
                mimetype = `video/${file_type}`;
            } else if (self.isAudio(file_type)) {
                mimetype = "audio/mpeg";
            } else {
                mimetype = self.props.record.data.mimetype;
            }

            const data = {
                id: self.props.record.resId,
                filename: self.props.record.data.name,
                name: self.props.record.data.name,
                mimetype: mimetype,
                model_name: self.props.record.resModel,
            };

            let attachment;
            if (this.store && this.store["ir.attachment"]) {
                attachment = this.store["ir.attachment"].insert(data);
            } else if (this.store && this.store.Attachment) {
                attachment = this.store.Attachment.insert(data);
            } else if (this.store && this.store.models && this.store.models.Attachment) {
                attachment = this.store.models.Attachment.insert(data);
            } else {
                attachment = data;
            }

            this.fileViewer.open(attachment);
            return;
        }

        // 2. Bottom half: Native record selection toggle
        this.props.record.toggleSelection();
    }
}
