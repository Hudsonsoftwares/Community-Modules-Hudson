/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { FileKanbanRenderer } from "@dms/js/views/file_kanban_renderer.esm";
import { FileKanbanController } from "@dms/js/views/file_kanban_controller.esm";
import { SearchPanel } from "@web/search/search_panel/search_panel";

patch(FileKanbanRenderer.prototype, {
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
        // Only run for dms.file kanban
        if (this.env.searchModel?.resModel !== "dms.file") {
            return;
        }

        // Get global domain to find current directory filter
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
        
        // Don't show directories in the Trash view
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
            ["name", "color", "count_files", "count_directories", "icon_url", "permission_download", "permission_write", "permission_unlink", "permission_move"]
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

    moveDirectory(dirId) {
        this.action.doAction({
            name: "Move Folder",
            type: "ir.actions.act_window",
            res_model: "dms.move.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                active_model: "dms.directory",
                active_ids: [dirId],
            },
        }, {
            onClose: () => {
                this.fetchDirectories(this.props);
            }
        });
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

patch(FileKanbanController.prototype, {
    onShare() {
        const selectedIds = this.model.root.selection.map((r) => r.resId);
        if (!selectedIds.length) return;
        return this.actionService.doAction({
            name: "Share",
            type: "ir.actions.act_window",
            res_model: "dms.file.share.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_file_id: selectedIds[0],
                active_id: selectedIds[0],
                active_ids: selectedIds,
            },
        });
    },

    createDirectory() {
        const domain = (typeof this.env.searchModel?.getGlobalDomain === 'function' ? this.env.searchModel.getGlobalDomain() : this.env.searchModel?.domain) || [];
        let directoryId = false;

        for (const d of domain) {
            if (Array.isArray(d)) {
                if (d[0] === 'directory_id' && (d[1] === '=' || d[1] === 'child_of')) {
                    directoryId = d[2];
                }
            }
        }

        const context = {};
        if (directoryId) {
            context.default_parent_id = directoryId;
        }

        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "dms.directory",
            views: [[false, "form"]],
            target: "new",
            context: context,
        }, {
            onClose: () => {
                if (this.model && this.model.root) {
                    this.model.root.load();
                }
            }
        });
    }
});

patch(SearchPanel.prototype, {
    moveSidebarDirectory(dirId) {
        this.env.services.action.doAction({
            name: "Move Folder",
            type: "ir.actions.act_window",
            res_model: "dms.move.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                active_model: "dms.directory",
                active_ids: [dirId],
            },
        }, {
            onClose: () => {
                if (this.env.searchModel && this.env.searchModel.root) {
                    this.env.searchModel.root.load();
                }
            }
        });
    },

    async editSidebarDirectory(dirId) {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dms.directory",
            res_id: dirId,
            views: [[false, "form"]],
            target: "new",
        }, {
            onClose: () => {
                if (this.env.searchModel && this.env.searchModel.root) {
                    this.env.searchModel.root.load();
                }
            }
        });
    },

    async trashSidebarDirectory(dirId) {
        await this.env.services.orm.call("dms.directory", "action_send_to_trash", [[dirId]]);
        if (this.env.searchModel && this.env.searchModel.root) {
            this.env.searchModel.root.load();
        }
    },

    async downloadSidebarDirectory(dirId) {
        const action = await this.env.services.orm.call("dms.directory", "action_download_directory_zip", [[dirId]]);
        if (action) {
            this.env.services.action.doAction(action);
        }
    }
});



