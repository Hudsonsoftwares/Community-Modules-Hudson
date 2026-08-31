/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";

export class KnowledgeListMockup extends Component {
    setup() {
        this.state = useState({
            items: [],
            searchQuery: "",
            isAddingItem: false,
            newItemTitle: "",
        });
    }

    onAddItem() {
        this.state.isAddingItem = true;
        this.state.newItemTitle = "";
    }

    saveNewItem() {
        if (this.state.newItemTitle.trim()) {
            this.state.items.unshift({
                id: Date.now(),
                title: this.state.newItemTitle.trim()
            });
        }
        this.state.isAddingItem = false;
        this.state.newItemTitle = "";
    }
}

KnowledgeListMockup.template = xml`
    <div class="km_pro_list_view" style="display: flex; flex-direction: column; height: 100%; background: #1c1d21; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        
        <!-- Header -->
        <div class="km_pro_list_header" style="display: flex; align-items: center; padding: 16px 24px; border-bottom: 1px solid #36363a; gap: 16px;">
            <button class="btn" style="background: #7f4a7c; color: #fff; border: none; padding: 6px 12px; border-radius: 4px; font-weight: 600; font-size: 0.9rem; cursor: pointer;" t-on-click="onAddItem">New</button>
            <h3 style="margin: 0; font-size: 1.1rem; font-weight: 500; display: flex; align-items: center; gap: 8px;">
                List of <t t-esc="props.itemName"/>
                <i class="fa fa-cog" style="color: #a0a0a0; font-size: 0.95rem; cursor: pointer;"></i>
            </h3>
            <div style="flex: 1; display: flex; justify-content: center;">
                <div style="position: relative; width: 300px;">
                    <i class="fa fa-search" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #a0a0a0;"></i>
                    <input type="text" placeholder="Search..." t-model="state.searchQuery" style="width: 100%; background: #161719; border: 1px solid #36363a; color: #fff; padding: 6px 12px 6px 36px; border-radius: 4px; outline: none; font-size: 0.9rem;" />
                    <i class="fa fa-caret-down" style="position: absolute; right: 12px; top: 50%; transform: translateY(-50%); color: #a0a0a0; cursor: pointer;"></i>
                </div>
            </div>
            <div style="flex: 1;"></div>
        </div>

        <!-- Table Header -->
        <div class="km_pro_list_table_header" style="display: flex; align-items: center; padding: 12px 24px; border-bottom: 1px solid #36363a; font-weight: 600; font-size: 0.9rem;">
            <div style="width: 40px; display: flex; justify-content: center;">
                <div style="width: 16px; height: 16px; border: 1px solid #5c5c5e; border-radius: 3px;"></div>
            </div>
            <div style="flex: 2; padding-left: 8px;">Name</div>
            <div style="flex: 1; text-align: center;">Created by</div>
            <div style="flex: 1; text-align: right; padding-right: 24px;">Created on</div>
            <div style="width: 32px; display: flex; justify-content: center;">
                <i class="fa fa-sliders" style="color: #a0a0a0; cursor: pointer;"></i>
            </div>
        </div>

        <!-- Body / Empty State -->
        <div class="km_pro_list_body" style="flex: 1; display: flex; flex-direction: column; overflow-y: auto;">
            <t t-if="state.items.length === 0 and !state.isAddingItem">
                <div style="text-align: center; max-width: 500px; margin: 60px auto 0 auto;">
                    <div style="background: #e9e3eb; width: 100px; height: 100px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 24px auto; position: relative;">
                        <!-- Mockup for the document icon with smile -->
                        <div style="background: white; border: 2px solid #a0a0a0; border-radius: 4px; width: 50px; height: 65px; position: relative; border-top-right-radius: 12px;">
                            <div style="position: absolute; top: -2px; right: -2px; border-bottom: 12px solid #a0a0a0; border-right: 12px solid transparent;"></div>
                            <div style="display: flex; justify-content: space-between; padding: 16px 8px 0;">
                                <div style="width: 4px; height: 4px; background: #a0a0a0; border-radius: 50%;"></div>
                                <div style="width: 4px; height: 4px; background: #a0a0a0; border-radius: 50%;"></div>
                            </div>
                            <div style="border-bottom: 2px solid #a0a0a0; width: 20px; margin: 6px auto 0; border-radius: 50%; height: 4px;"></div>
                            <div style="margin-top: 12px; display: flex; flex-direction: column; gap: 4px; align-items: center;">
                                <div style="width: 30px; height: 2px; background: #e0e0e0;"></div>
                                <div style="width: 20px; height: 2px; background: #e0e0e0;"></div>
                            </div>
                        </div>
                        <!-- Sparkles -->
                        <div style="position: absolute; top: -10px; left: 10px; color: #fff; font-size: 1.2rem;">✨</div>
                    </div>
                    <h5 style="margin: 0 0 12px 0; font-size: 1.25rem; font-weight: 700; color: #fff;">Create an Article Item</h5>
                    <p style="margin: 0; font-size: 0.95rem; color: #a0a0a0; line-height: 1.5; text-align: center;">
                        Article items are articles that exist inside their parents but are not displayed in the menu. They can be used to handle lists (Buildings, Tasks, ...).
                    </p>
                </div>
            </t>
            <t t-else="">
                <t t-if="state.isAddingItem">
                    <div style="display: flex; align-items: center; padding: 12px 24px; border-bottom: 1px solid #36363a; background: #242426;">
                        <div style="width: 40px; display: flex; justify-content: center;">
                            <div style="width: 16px; height: 16px; border: 1px solid #5c5c5e; border-radius: 3px;"></div>
                        </div>
                        <div style="flex: 2; padding-left: 8px;">
                            <input type="text" t-model="state.newItemTitle" placeholder="My New Item" style="width: 100%; background: transparent; border: none; border-bottom: 1px solid #00a09d; color: #fff; outline: none; font-size: 0.95rem; padding-bottom: 4px;" t-on-keydown="(ev) => ev.key === 'Enter' and this.saveNewItem()" autofocus="autofocus" />
                        </div>
                        <div style="flex: 1; text-align: center;"></div>
                        <div style="flex: 1; text-align: right; padding-right: 24px;"></div>
                        <div style="width: 32px; display: flex; justify-content: center;">
                            <button t-on-click="saveNewItem" style="background: #7f4a7c; color: #fff; border: none; padding: 4px 8px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.8rem;">Save</button>
                        </div>
                    </div>
                </t>
                
                <t t-foreach="state.items" t-as="item" t-key="item.id">
                    <div style="display: flex; align-items: center; padding: 12px 24px; border-bottom: 1px solid #36363a; cursor: pointer;" onmouseover="this.style.backgroundColor='#242426'" onmouseout="this.style.backgroundColor='transparent'">
                        <div style="width: 40px; display: flex; justify-content: center;">
                            <div style="width: 16px; height: 16px; border: 1px solid #5c5c5e; border-radius: 3px;"></div>
                        </div>
                        <div style="flex: 2; padding-left: 8px; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 1.1rem;">📄</span>
                            <span style="font-weight: 500; font-size: 0.95rem;"><t t-esc="item.title"/></span>
                        </div>
                        <div style="flex: 1; text-align: center; display: flex; align-items: center; justify-content: center; gap: 8px;">
                            <div style="width: 24px; height: 24px; background: #d84b4b; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: bold;">M</div>
                            <span style="color: #a0a0a0; font-size: 0.85rem;">Mitchell Admin</span>
                        </div>
                        <div style="flex: 1; text-align: right; padding-right: 24px; color: #a0a0a0; font-size: 0.85rem;">
                            Just now
                        </div>
                        <div style="width: 32px; display: flex; justify-content: center;">
                             <i class="fa fa-ellipsis-v" style="color: #5c5c5e;"></i>
                        </div>
                    </div>
                </t>
            </t>
        </div>
    </div>
`;
