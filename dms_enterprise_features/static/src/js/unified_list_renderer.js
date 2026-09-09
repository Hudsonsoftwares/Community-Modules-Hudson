/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { FileListRenderer } from "@dms/js/views/file_list_renderer.esm";

patch(FileListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.action = useService("action");
        this.dmsDirectoriesState = useState({ data: [], currentDir: false });
        
        onWillStart(async () => {
            await this.fetchDirectories(this.props);
        });
        
        onWillUpdateProps(async (nextProps) => {
            await this.fetchDirectories(nextProps);
        });
    },

    async fetchDirectories(props) {
        if (this.env.searchModel?.resModel !== "dms.file") {
            return;
        }

        const domain = (typeof this.env.searchModel.getGlobalDomain === 'function' ? this.env.searchModel.getGlobalDomain() : this.env.searchModel.domain) || [];
        let directoryId = false;
        let isTrashAction = false;

        for (const d of domain) {
            if (Array.isArray(d)) {
                if (d[0] === 'directory_id' && d[1] === '=') {
                    directoryId = d[2];
                }
                if (d[0] === 'is_trashed' && d[2] === true) {
                    isTrashAction = true;
                }
            }
        }
        
        if (isTrashAction) {
            this.dmsDirectoriesState.data = [];
            return;
        }

        let dirDomain = [['is_trashed', '=', false]];
        if (directoryId) {
            dirDomain.push(['parent_id', '=', directoryId]);
            const currentDir = await this.orm.read("dms.directory", [directoryId], ["parent_id", "name"]);
            if (currentDir && currentDir.length > 0) {
                this.dmsDirectoriesState.currentDir = currentDir[0];
            }
        } else {
            dirDomain.push(['is_root_directory', '=', true]);
            this.dmsDirectoriesState.currentDir = false;
        }

        this.dmsDirectoriesState.data = await this.orm.searchRead(
            "dms.directory",
            dirDomain,
            ["name", "display_name", "color", "count_files", "count_directories", "icon_url", "permission_download", "permission_write", "permission_unlink", "permission_move"]
        );
    },

    openDirectory(dirId) {
        if (this.env.searchModel) {
            const category = this.env.searchModel.getSections().find(s => s.fieldName === 'directory_id');
            if (category) {
                this.env.searchModel.toggleCategoryValue(category.id, dirId || false);
            }
        }
    },

    async setColor(dirId, colorIdx) {
        await this.orm.write("dms.directory", [dirId], { color: colorIdx });
        await this.fetchDirectories(this.props);
    },

    navigateUp() {
        if (this.dmsDirectoriesState.currentDir) {
            const parentId = this.dmsDirectoriesState.currentDir.parent_id ? this.dmsDirectoriesState.currentDir.parent_id[0] : false;
            this.openDirectory(parentId);
        }
    },

    editDirectory(dirId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dms.directory",
            res_id: dirId,
            views: [[false, "form"]],
            target: "new",
        }, {
            onClose: () => {
                this.fetchDirectories(this.props);
            }
        });
    },

    async trashDirectory(dirId) {
        await this.orm.call("dms.directory", "action_send_to_trash", [[dirId]]);
        await this.fetchDirectories(this.props);
    },

    async downloadDirectory(dirId) {
        const action = await this.orm.call("dms.directory", "action_download_directory_zip", [[dirId]]);
        if (action) {
            this.action.doAction(action);
        }
    }
});
