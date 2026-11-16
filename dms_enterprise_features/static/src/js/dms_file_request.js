/** @odoo-module **/
/**
 * "Request" and "Link" entries of the DMS New menu, and the kanban card
 * behaviour of link documents (open the URL) and requested files (upload
 * the missing file).
 */

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { FileKanbanController } from "@dms/js/views/file_kanban_controller.esm";
import { FileListController } from "@dms/js/views/file_list_controller.esm";
import { FileKanbanRecord } from "@dms/js/views/file_kanban_record.esm";

function currentDirectoryId(env) {
    const sm = env.searchModel;
    const section = sm?.getSections?.()?.find((s) => s.fieldName === "directory_id");
    if (section?.activeValueId) {
        return section.activeValueId;
    }
    const domain = [
        ...(sm?.domain || []),
        ...(typeof sm?.getGlobalDomain === "function" ? sm.getGlobalDomain() : []),
    ];
    for (const d of domain) {
        if (Array.isArray(d) && d[0] === "directory_id" && ["=", "child_of"].includes(d[1])) {
            const val = Array.isArray(d[2]) ? d[2][0] : d[2];
            if (val) {
                return val;
            }
        }
    }
    return sm?.context?.default_directory_id || false;
}

const dmsNewMenuMethods = {
    _dmsOpenNewWizard(resModel, name) {
        const directoryId = currentDirectoryId(this.env);
        const action = this.actionService || this.env.services.action;
        return action.doAction(
            {
                name,
                type: "ir.actions.act_window",
                res_model: resModel,
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_directory_id: directoryId || false,
                    dialog_size: "lg",
                },
            },
            {
                onClose: async () => {
                    await this.model?.root?.load();
                },
            }
        );
    },

    requestDocument() {
        return this._dmsOpenNewWizard("dms.file.request.wizard", _t("Request a file"));
    },

    addDocumentUrl() {
        return this._dmsOpenNewWizard("dms.file.url.wizard", _t("Add Url"));
    },
};

patch(FileKanbanController.prototype, dmsNewMenuMethods);
patch(FileListController.prototype, dmsNewMenuMethods);

function readAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

patch(FileKanbanRecord.prototype, {
    onGlobalClick(ev) {
        const data = this.props.record.data;
        const kind = data.file_kind;
        const inPreview = ev.target.closest(".o_kanban_dms_file_preview");
        const onUploadIcon = ev.target.closest(".o_dms_request_upload");
        if (
            (kind === "url" || kind === "request") &&
            (inPreview || onUploadIcon) &&
            !ev.target.closest(".o_field_boolean_favorite, .o_dropdown_menu, button, a[type]")
        ) {
            ev.preventDefault();
            ev.stopPropagation();
            if (kind === "url") {
                if (data.url) {
                    window.open(data.url, "_blank", "noopener");
                }
            } else if (data.can_upload_request) {
                this._dmsPickRequestedFile();
            } else {
                this.env.services.notification.add(
                    _t("Waiting for %s to upload this document.", data.request_partner_id?.display_name || _t("the requested person")),
                    { type: "info" }
                );
            }
            return;
        }
        return super.onGlobalClick(ev);
    },

    _dmsPickRequestedFile() {
        const input = document.createElement("input");
        input.type = "file";
        input.className = "d-none";
        input.addEventListener("change", async () => {
            const file = input.files && input.files[0];
            input.remove();
            if (!file) {
                return;
            }
            const notification = this.env.services.notification;
            try {
                const content = await readAsBase64(file);
                await this.env.services.orm.call("dms.file", "action_dms_request_upload", [
                    [this.props.record.resId],
                    file.name,
                    content,
                ]);
                notification.add(_t("Document uploaded."), { type: "success" });
            } catch (err) {
                notification.add(
                    err?.data?.message || err?.message || _t("The upload failed."),
                    { type: "danger" }
                );
            }
            await this.props.record.model.root.load();
        });
        document.body.appendChild(input);
        input.click();
    },
});
