/** @odoo-module **/
/**
 * Branding Remover – Backend user-menu patch
 * ==========================================
 * Removes the "My Odoo.com Account" entry from the user-profile dropdown
 * menu in the Odoo web client backend.
 *
 * The entry is registered in the "user_menuitems" registry under the key
 * "odoo_account" (see web/static/src/webclient/user_menu/user_menu_items.js).
 * We simply remove that key from the registry after the registry has been
 * populated, which is the safe, officially-supported approach for Odoo 17+.
 *
 * NOTE: This patch does NOT remove any copyright or licence notices from
 * source files. Only the visible UI menu item is affected.
 */

import { registry } from "@web/core/registry";

// Use an "after" hook on the registry so we run once it is fully populated.
// registry.category() returns the sub-registry for user_menuitems.
const userMenuRegistry = registry.category("user_menuitems");

// Remove "My Odoo.com Account" menu item if it exists.
if (userMenuRegistry.contains("odoo_account")) {
    userMenuRegistry.remove("odoo_account");
}
