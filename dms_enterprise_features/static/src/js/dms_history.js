/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount } from "@odoo/owl";
import { SearchModel } from "@web/search/search_model";
import { router, routerBus } from "@web/core/browser/router";
import { FileKanbanController } from "@dms/js/views/file_kanban_controller.esm";
import { FileListController } from "@dms/js/views/file_list_controller.esm";

// Lock and hide DMS navigation keys so Odoo router preserves them and keeps URLs clean
if (router && typeof router.addLockedKey === "function") {
    router.addLockedKey("dmsDirectoryId");
    router.addLockedKey("skipRouteChange");
}
if (router && typeof router.hideKeyFromUrl === "function") {
    router.hideKeyFromUrl("dmsDirectoryId");
    router.hideKeyFromUrl("skipRouteChange");
}

let activeDmsSearchModel = null;
let currentDmsDirId = null;
let isPopStateNavigating = false;
let cleanupTimeout = null;

function initDmsHistory(searchModel) {
    if (!searchModel || searchModel.resModel !== "dms.file") {
        return;
    }

    const category = searchModel.getSections().find((s) => s.fieldName === "directory_id");
    const currentDir = category ? category.activeValueId || false : false;

    const existingDir =
        window.history.state?.dmsDirectoryId ?? window.history.state?.nextState?.dmsDirectoryId;

    if (typeof existingDir !== "undefined") {
        currentDmsDirId = existingDir || false;
        if (category && (category.activeValueId || false) !== (existingDir || false)) {
            isPopStateNavigating = true;
            try {
                searchModel.toggleCategoryValue(category.id, existingDir || false);
            } finally {
                isPopStateNavigating = false;
            }
        }
    } else {
        currentDmsDirId = currentDir || false;
        window.history.replaceState(
            {
                ...window.history.state,
                nextState: {
                    ...(router.current || {}),
                    dmsDirectoryId: currentDmsDirId,
                    skipRouteChange: true,
                },
                skipRouteChange: true,
                dmsDirectoryId: currentDmsDirId,
            },
            ""
        );
    }
}

function setActiveDmsSearchModel(searchModel) {
    if (cleanupTimeout) {
        clearTimeout(cleanupTimeout);
        cleanupTimeout = null;
    }
    activeDmsSearchModel = searchModel;
    initDmsHistory(searchModel);
}

function unregisterDmsSearchModel(searchModel) {
    if (activeDmsSearchModel === searchModel) {
        cleanupTimeout = setTimeout(() => {
            if (activeDmsSearchModel === searchModel) {
                activeDmsSearchModel = null;
            }
        }, 100);
    }
}

function handleDirectoryNavigation(newDirId) {
    newDirId = newDirId || false;
    if (newDirId === currentDmsDirId) {
        return;
    }
    currentDmsDirId = newDirId;

    window.history.pushState(
        {
            ...window.history.state,
            nextState: {
                ...(router.current || {}),
                dmsDirectoryId: newDirId,
                skipRouteChange: true,
            },
            skipRouteChange: true,
            dmsDirectoryId: newDirId,
        },
        ""
    );
}

// Intercept directory selection in SearchModel for dms.file
patch(SearchModel.prototype, {
    toggleCategoryValue(sectionId, valueId) {
        super.toggleCategoryValue(...arguments);
        if (this.resModel === "dms.file" && !isPopStateNavigating) {
            const section = this.sections.get(sectionId);
            if (section && section.fieldName === "directory_id") {
                handleDirectoryNavigation(valueId || false);
            }
        }
    },

    clearSections(sectionIds) {
        super.clearSections(...arguments);
        if (this.resModel === "dms.file" && !isPopStateNavigating) {
            for (const sectionId of sectionIds) {
                const section = this.sections.get(sectionId);
                if (section && section.fieldName === "directory_id") {
                    handleDirectoryNavigation(false);
                    break;
                }
            }
        }
    },
});

// Hook into DMS Kanban and List controllers to track active SearchModel
patch(FileKanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            setActiveDmsSearchModel(this.env.searchModel);
        });
        onWillUnmount(() => {
            unregisterDmsSearchModel(this.env.searchModel);
        });
    },
});

patch(FileListController.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            setActiveDmsSearchModel(this.env.searchModel);
        });
        onWillUnmount(() => {
            unregisterDmsSearchModel(this.env.searchModel);
        });
    },
});

// Handle native browser back and forward buttons
window.addEventListener("popstate", (ev) => {
    const targetDir = ev.state?.dmsDirectoryId ?? ev.state?.nextState?.dmsDirectoryId;
    if (typeof targetDir === "undefined") {
        currentDmsDirId = null;
        return;
    }

    const targetAction = ev.state?.nextState?.action || ev.state?.action;
    const currentAction = router.current?.action;

    if (activeDmsSearchModel && (!targetAction || !currentAction || targetAction === currentAction)) {
        const category = activeDmsSearchModel.getSections().find((s) => s.fieldName === "directory_id");
        if (category) {
            const targetId = targetDir || false;
            if ((category.activeValueId || false) !== targetId) {
                isPopStateNavigating = true;
                currentDmsDirId = targetId;
                try {
                    activeDmsSearchModel.toggleCategoryValue(category.id, targetId);
                } finally {
                    isPopStateNavigating = false;
                }
            }
        }
    } else {
        routerBus.trigger("ROUTE_CHANGE");
    }
});
