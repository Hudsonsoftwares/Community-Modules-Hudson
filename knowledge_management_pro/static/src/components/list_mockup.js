/** @odoo-module **/
import { Component, useState, xml, onWillStart } from "@odoo/owl";
import { session } from "@web/session";

export class KnowledgeListMockup extends Component {
    static template = xml`
        <div class="km_pro_list_board" t-on-click="closeMenus">
            <!-- Header Toolbar -->
            <div class="km_pro_list_header">
                <div class="km_pro_list_header_left">
                    <button class="km_pro_list_btn_new" t-on-click="addNewItem">New</button>
                    <div class="km_pro_list_title_wrap">
                        <span>List of <t t-esc="props.itemName || 'Items'"/></span>
                    </div>
                </div>
                <div class="km_pro_list_header_right">
                    <div class="km_pro_list_search_box">
                        <i class="fa fa-search km_pro_list_search_icon"></i>
                        <input type="text" class="km_pro_list_search_input" placeholder="Search..." t-model="state.searchQuery" />
                        <i t-if="state.searchQuery" class="fa fa-times km_pro_list_search_clear" t-on-click="clearSearch"></i>
                        <i class="fa fa-caret-down km_pro_list_search_caret"></i>
                    </div>
                    <div class="km_pro_list_pagination">
                        <span class="km_pro_list_page_info">
                            <t t-esc="filteredItems.length"/> / <t t-esc="state.items.length"/>
                        </span>
                        <button class="km_pro_list_page_btn" disabled="1"><i class="fa fa-angle-left"></i></button>
                        <button class="km_pro_list_page_btn" disabled="1"><i class="fa fa-angle-right"></i></button>
                    </div>
                </div>
            </div>

            <!-- List Table -->
            <div class="km_pro_list_body">
                <table class="km_pro_list_table">
                    <thead>
                        <tr>
                            <th class="col-checkbox"><input type="checkbox" /></th>
                            <th class="col-name">Name</th>
                            <th class="col-star"></th>
                            <th class="col-created-by" t-if="state.visibleColumns.createdBy">Created by</th>
                            <th class="col-created-on" t-if="state.visibleColumns.createdOn">Created on</th>
                            <th class="col-section" t-if="state.visibleColumns.section">Section</th>
                            <th class="col-menu-article" t-if="state.visibleColumns.menuArticle">Menu Article</th>
                            <th class="col-last-edited-by" t-if="state.visibleColumns.lastEditedBy">Last Edited by</th>
                            <th class="col-last-edit-date" t-if="state.visibleColumns.lastEditDate">Last Edit Date</th>
                            <!-- Column toggle icon in last header cell -->
                            <th class="col-col-toggle" style="position: relative;">
                                <span class="km_pro_col_toggle_btn" t-on-click.stop="toggleSettingsMenu" title="Toggle Columns">
                                    <i class="fa fa-exchange"></i>
                                </span>
                                <t t-if="state.showSettingsMenu">
                                    <div class="km_pro_list_settings_menu shadow" t-on-click.stop="">
                                        <div class="km_pro_list_settings_item" t-on-click="() => this.toggleColumn('createdBy')">
                                            <i t-attf-class="fa {{ state.visibleColumns.createdBy ? 'fa-check-square text-primary' : 'fa-square-o' }}"></i> Created by
                                        </div>
                                        <div class="km_pro_list_settings_item" t-on-click="() => this.toggleColumn('createdOn')">
                                            <i t-attf-class="fa {{ state.visibleColumns.createdOn ? 'fa-check-square text-primary' : 'fa-square-o' }}"></i> Created on
                                        </div>
                                        <div class="km_pro_list_settings_item" t-on-click="() => this.toggleColumn('section')">
                                            <i t-attf-class="fa {{ state.visibleColumns.section ? 'fa-check-square text-primary' : 'fa-square-o' }}"></i> Section
                                        </div>
                                        <div class="km_pro_list_settings_item" t-on-click="() => this.toggleColumn('menuArticle')">
                                            <i t-attf-class="fa {{ state.visibleColumns.menuArticle ? 'fa-check-square text-primary' : 'fa-square-o' }}"></i> Menu Article
                                        </div>
                                        <div class="km_pro_list_settings_item" t-on-click="() => this.toggleColumn('lastEditedBy')">
                                            <i t-attf-class="fa {{ state.visibleColumns.lastEditedBy ? 'fa-check-square text-primary' : 'fa-square-o' }}"></i> Last Edited by
                                        </div>
                                        <div class="km_pro_list_settings_item" t-on-click="() => this.toggleColumn('lastEditDate')">
                                            <i t-attf-class="fa {{ state.visibleColumns.lastEditDate ? 'fa-check-square text-primary' : 'fa-square-o' }}"></i> Last Edit Date
                                        </div>
                                    </div>
                                </t>
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <t t-foreach="filteredItems" t-as="item" t-key="item.id">
                            <tr class="km_pro_list_row" t-on-click="() => this.openItem(item)">
                                <td class="col-checkbox" t-on-click.stop=""><input type="checkbox" /></td>
                                <td class="col-name">
                                    <span class="km_pro_list_name_inner">
                                        <i class="fa fa-bars km_pro_drag_handle"></i>
                                        <i class="fa fa-file-text-o km_pro_item_icon"></i>
                                        <span class="km_pro_item_name"><t t-esc="item.name || 'Untitled'"/></span>
                                    </span>
                                </td>
                                <td class="col-star" t-on-click.stop="() => this.toggleFavorite(item)">
                                    <i t-attf-class="fa {{ item.isFavorite ? 'fa-star km_pro_star_on' : 'fa-star-o km_pro_star_off' }}"></i>
                                </td>
                                <td class="col-created-by" t-if="state.visibleColumns.createdBy">
                                    <div class="km_pro_avatar_label">
                                        <div class="km_pro_list_avatar" t-attf-style="background-color: {{ this.getAvatarColor(item.createdBy) }}">
                                            <t t-esc="item.createdBy ? item.createdBy.charAt(0).toUpperCase() : 'U'"/>
                                        </div>
                                        <span t-esc="item.createdBy || 'Unknown'"/>
                                    </div>
                                </td>
                                <td class="col-created-on" t-if="state.visibleColumns.createdOn"><t t-esc="item.createdOn || ''"/></td>
                                <td class="col-section" t-if="state.visibleColumns.section"><t t-esc="item.section || ''"/></td>
                                <td class="col-menu-article" t-if="state.visibleColumns.menuArticle"><t t-esc="item.menuArticle || ''"/></td>
                                <td class="col-last-edited-by" t-if="state.visibleColumns.lastEditedBy">
                                    <t t-if="item.lastEditedBy">
                                        <div class="km_pro_avatar_label">
                                            <div class="km_pro_list_avatar" t-attf-style="background-color: {{ this.getAvatarColor(item.lastEditedBy) }}">
                                                <t t-esc="item.lastEditedBy.charAt(0).toUpperCase()"/>
                                            </div>
                                            <span t-esc="item.lastEditedBy"/>
                                        </div>
                                    </t>
                                </td>
                                <td class="col-last-edit-date" t-if="state.visibleColumns.lastEditDate"><t t-esc="item.lastEditDate || ''"/></td>
                                <td class="col-col-toggle" t-on-click.stop=""></td>
                            </tr>
                        </t>
                        <tr t-if="filteredItems.length === 0" class="km_pro_list_empty_row">
                            <td colspan="10">
                                <div class="km_pro_list_empty_state">
                                    <i class="fa fa-list-ul"></i>
                                    <span>No items. Click <strong>New</strong> to create one.</span>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `;

    static props = {
        itemName: { type: String, optional: true },
        initialData: { type: String, optional: true },
        onChange: { type: Function, optional: true },
        onNewItem: { type: Function, optional: true }
    };

    setup() {
        this.state = useState({
            items: [],
            visibleColumns: {
                createdBy: true,
                createdOn: true,
                section: false,
                menuArticle: false,
                lastEditedBy: false,
                lastEditDate: false
            },
            showSettingsMenu: false,
            searchQuery: ""
        });

        onWillStart(() => {
            this.parseInitialData();
        });
    }

    parseInitialData() {
        if (this.props.initialData) {
            try {
                const parsed = JSON.parse(this.props.initialData);
                if (parsed && Array.isArray(parsed.items)) {
                    this.state.items = parsed.items;
                }
                if (parsed && parsed.visibleColumns) {
                    Object.assign(this.state.visibleColumns, parsed.visibleColumns);
                }
            } catch (e) {
                console.warn("Failed to parse list data", e);
            }
        }
    }

    get filteredItems() {
        if (!this.state.searchQuery) return this.state.items;
        const q = this.state.searchQuery.toLowerCase();
        return this.state.items.filter(item =>
            (item.name || '').toLowerCase().includes(q) ||
            (item.createdBy || '').toLowerCase().includes(q)
        );
    }

    getCurrentDateStr() {
        const d = new Date();
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec'];
        let hours = d.getHours();
        const ampm = hours >= 12 ? 'pm' : 'am';
        hours = hours % 12;
        hours = hours ? hours : 12;
        const minutes = d.getMinutes().toString().padStart(2, '0');
        return `${d.getDate()} ${months[d.getMonth()]}, ${hours}:${minutes} ${ampm}`;
    }

    addNewItem() {
        // Delegate to parent editor which will create a real Odoo article
        if (this.props.onNewItem) {
            this.props.onNewItem();
        }
    }

    openItem(item) {
        // Navigate to the article: item.articleId is the real Odoo article ID
        if (item.articleId && this.props.onNewItem) {
            // We reuse onNewItem with the articleId to navigate
            this.props.onNewItem(item.articleId);
        }
    }

    toggleFavorite(item) {
        item.isFavorite = !item.isFavorite;
        this.notifyChange();
    }

    toggleSettingsMenu() {
        this.state.showSettingsMenu = !this.state.showSettingsMenu;
    }

    closeMenus() {
        this.state.showSettingsMenu = false;
    }

    toggleColumn(colName) {
        this.state.visibleColumns[colName] = !this.state.visibleColumns[colName];
        this.notifyChange();
    }

    clearSearch() {
        this.state.searchQuery = "";
    }

    notifyChange() {
        if (this.props.onChange) {
            this.props.onChange(JSON.stringify({
                items: this.state.items,
                visibleColumns: this.state.visibleColumns
            }));
        }
    }

    getAvatarColor(name) {
        const colors = ['#714B67', '#017E84', '#e65100', '#2e7d32', '#1565c0'];
        if (!name) return colors[0];
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }
        return colors[Math.abs(hash) % colors.length];
    }
}
