/** @odoo-module **/

/**
 * Folder breadcrumbs that survive opening another screen on top of the
 * documents browser.
 *
 * The documents browser (dms.file kanban / list / activity) shows its folder
 * path as breadcrumbs: "My Documents / Sales / Quotes". Those extra crumbs
 * only live in that controller's own breadcrumb list. When something is
 * opened on top of it (a file form, a folder form, ...), Odoo rebuilds the
 * trail from the controller stack, one crumb per controller, so the path
 * collapsed to "My Documents / quote_001.txt".
 *
 * - publishDmsTrail(): the browser publishes its current trail (crumbs that
 *   carry a `dmsNav` = {dirId, trash} target) under its controller jsId.
 * - ControlPanel patch: in any later screen, the crumb of that controller is
 *   expanded back into the published trail. Clicking one of them restores
 *   the browser (Odoo's own crumb handler) and opens that folder.
 * - takeDmsPendingNav(): read by the restored browser once mounted.
 */

import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";

const trails = new Map(); // controller jsId -> [{ key, name, dmsNav }]
const pendingNav = new Map(); // controller jsId -> { dirId, trash }

/**
 * @param {Object} controller DMS view controller (has _initialBreadcrumbs)
 * @param {Object[]} breadcrumbs the trail it just put in its control panel
 */
export function publishDmsTrail(controller, breadcrumbs) {
    const jsId = controller._initialBreadcrumbs?.at(-1)?.jsId;
    if (!jsId) {
        return;
    }
    trails.set(
        jsId,
        breadcrumbs
            .filter((crumb) => crumb?.dmsNav)
            .map((crumb) => ({ key: crumb.jsId, name: crumb.name, dmsNav: crumb.dmsNav }))
    );
}

/** Folder to open after the browser was restored from a breadcrumb. */
export function takeDmsPendingNav(controller) {
    const jsId = controller._initialBreadcrumbs?.at(-1)?.jsId;
    if (!jsId || !pendingNav.has(jsId)) {
        return null;
    }
    const nav = pendingNav.get(jsId);
    pendingNav.delete(jsId);
    return nav;
}

function expand(breadcrumbs) {
    if (!breadcrumbs?.some((crumb) => crumb && !crumb.dmsNav && trails.get(crumb.jsId)?.length)) {
        return breadcrumbs;
    }
    const result = [];
    for (const crumb of breadcrumbs) {
        const trail = crumb && !crumb.dmsNav ? trails.get(crumb.jsId) : null;
        if (!trail?.length) {
            result.push(crumb);
            continue;
        }
        for (const item of trail) {
            result.push({
                jsId: `${crumb.jsId}/${item.key}`,
                name: item.name,
                isFormView: false,
                url: crumb.url,
                onSelected: () => {
                    pendingNav.set(crumb.jsId, item.dmsNav);
                    return crumb.onSelected();
                },
            });
        }
    }
    return result;
}

patch(ControlPanel.prototype, {
    setup() {
        super.setup(...arguments);
        const own = this.breadcrumbs;
        if (own) {
            Object.defineProperty(this, "breadcrumbs", {
                configurable: true,
                get: () => expand(own),
            });
        }
    },
});
