/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";

export class KnowledgeKanbanMockup extends Component {
    setup() {
        this.state = useState({
            columns: [
                { id: "new", title: "New", items: [] },
                { id: "ongoing", title: "Ongoing", items: [] },
                { id: "done", title: "Done", items: [] }
            ],
            newItemTitle: "",
            addingToCol: null,
            searchQuery: "",
            draggedItemId: null,
            editingItemId: null,
            editItemTitle: ""
        });
    }

    onAddItem(colId) {
        this.state.addingToCol = colId;
        this.state.newItemTitle = "";
    }

    saveNewItem(colId) {
        if (this.state.newItemTitle.trim()) {
            const col = this.state.columns.find(c => c.id === colId);
            if (col) {
                col.items.push({
                    id: Date.now(),
                    title: this.state.newItemTitle.trim()
                });
            }
        }
        this.state.addingToCol = null;
        this.state.newItemTitle = "";
    }

    onDragStart(ev, itemId) {
        this.state.draggedItemId = itemId;
        ev.dataTransfer.effectAllowed = "move";
    }

    onDragOver(ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
    }

    onDrop(ev, targetColId) {
        ev.preventDefault();
        const itemId = this.state.draggedItemId;
        if (!itemId) return;

        let itemToMove = null;
        let sourceCol = null;
        for (const col of this.state.columns) {
            const item = col.items.find(i => i.id === itemId);
            if (item) {
                itemToMove = item;
                sourceCol = col;
                break;
            }
        }

        if (itemToMove && sourceCol.id !== targetColId) {
            sourceCol.items = sourceCol.items.filter(i => i.id !== itemId);
            const targetCol = this.state.columns.find(c => c.id === targetColId);
            if (targetCol) {
                targetCol.items.push(itemToMove);
            }
        }
        this.state.draggedItemId = null;
    }

    openEdit(item) {
        this.state.editingItemId = item.id;
        this.state.editItemTitle = item.title;
    }

    saveEdit(colId, itemId) {
        if (this.state.editItemTitle.trim()) {
            const col = this.state.columns.find(c => c.id === colId);
            if (col) {
                const item = col.items.find(i => i.id === itemId);
                if (item) {
                    item.title = this.state.editItemTitle.trim();
                }
            }
        }
        this.state.editingItemId = null;
    }

    deleteItem(colId, itemId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            col.items = col.items.filter(i => i.id !== itemId);
        }
        this.state.editingItemId = null;
    }
}

KnowledgeKanbanMockup.template = xml`
    <div class="km_pro_kanban_view" style="display: flex; flex-direction: column; height: 100%; background: #1c1d21; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        
        <!-- Header -->
        <div class="km_pro_kanban_header" style="display: flex; align-items: center; padding: 16px 24px; border-bottom: 1px solid #36363a; gap: 16px;">
            <button class="btn" style="background: #7f4a7c; color: #fff; border: none; padding: 6px 12px; border-radius: 4px; font-weight: 600; font-size: 0.9rem; cursor: pointer;" t-on-click="() => this.onAddItem('new')">New</button>
            <h3 style="margin: 0; font-size: 1.1rem; font-weight: 500; display: flex; align-items: center; gap: 8px;">
                Kanban of <t t-esc="props.itemName"/>
                <i class="fa fa-cog" style="color: #a0a0a0; font-size: 0.95rem; cursor: pointer;"></i>
            </h3>
            <div style="flex: 1;"></div>
            <div style="position: relative; width: 300px;">
                <i class="fa fa-search" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #a0a0a0;"></i>
                <input type="text" placeholder="Search..." t-model="state.searchQuery" style="width: 100%; background: #242426; border: 1px solid #36363a; color: #fff; padding: 6px 12px 6px 36px; border-radius: 4px; outline: none; font-size: 0.9rem;" />
                <i class="fa fa-caret-down" style="position: absolute; right: 12px; top: 50%; transform: translateY(-50%); color: #a0a0a0; cursor: pointer;"></i>
            </div>
        </div>

        <!-- Columns -->
        <div class="km_pro_kanban_columns" style="display: flex; flex: 1; padding: 24px; gap: 24px; overflow-x: auto; align-items: flex-start;">
            
            <!-- Column Loop -->
            <t t-foreach="state.columns" t-as="col" t-key="col.id">
                <div class="km_pro_kanban_col" t-att-style="col.id === 'done' ? 'width: 40px; display: flex; flex-direction: column; align-items: center; gap: 16px;' : 'width: 320px; flex-shrink: 0;'">
                    
                    <t t-if="col.id !== 'done'">
                        <!-- Normal Column Header -->
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                            <h4 style="margin: 0; font-size: 1rem; font-weight: 600;"><t t-esc="col.title"/> (<t t-esc="col.items.length"/>)</h4>
                            <i class="fa fa-plus" style="color: #a0a0a0; cursor: pointer;" t-on-click="() => this.onAddItem(col.id)"></i>
                        </div>
                        
                        <!-- Items -->
                        <div style="display: flex; flex-direction: column; gap: 8px; min-height: 200px;" t-on-dragover="onDragOver" t-on-drop="(ev) => this.onDrop(ev, col.id)">
                            
                            <!-- Adding Item Input -->
                            <t t-if="state.addingToCol === col.id">
                                <div style="background: #242426; border: 1px solid #36363a; padding: 16px; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); margin-bottom: 8px;">
                                    <div style="display: flex; align-items: center; margin-bottom: 16px;">
                                        <i class="fa fa-plus-circle" style="color: #5c5c5e; font-size: 1.1rem; margin-right: 12px;"></i>
                                        <input type="text" t-model="state.newItemTitle" placeholder="My New Item" style="flex: 1; background: transparent; border: none; border-bottom: 1px solid #00a09d; color: #a0a0a0; outline: none; font-size: 1rem; padding-bottom: 4px;" t-on-keydown="(ev) => ev.key === 'Enter' and this.saveNewItem(col.id)" autofocus="autofocus"/>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <div style="display: flex; gap: 8px;">
                                            <button t-on-click="() => this.saveNewItem(col.id)" style="background: #7f4a7c; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.9rem;">Add</button>
                                            <button t-on-click="() => this.state.addingToCol = null" style="background: #3f3f46; color: #e0e0e0; border: none; padding: 6px 14px; border-radius: 4px; font-weight: 500; cursor: pointer; font-size: 0.9rem;">Edit</button>
                                        </div>
                                        <button t-on-click="() => this.state.addingToCol = null" style="background: #3f3f46; color: #e0e0e0; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.9rem;"><i class="fa fa-trash-o"></i></button>
                                    </div>
                                </div>
                            </t>

                            <!-- Existing Items -->
                            <t t-foreach="col.items" t-as="item" t-key="item.id">
                                <t t-if="state.editingItemId === item.id">
                                    <div style="background: #242426; border: 1px solid #36363a; padding: 16px; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; margin-bottom: 16px;">
                                            <i class="fa fa-pencil" style="color: #5c5c5e; font-size: 1.1rem; margin-right: 12px;"></i>
                                            <input type="text" t-model="state.editItemTitle" style="flex: 1; background: transparent; border: none; border-bottom: 1px solid #00a09d; color: #a0a0a0; outline: none; font-size: 1rem; padding-bottom: 4px;" t-on-keydown="(ev) => ev.key === 'Enter' and this.saveEdit(col.id, item.id)" autofocus="autofocus"/>
                                        </div>
                                        <div style="display: flex; justify-content: space-between; align-items: center;">
                                            <div style="display: flex; gap: 8px;">
                                                <button t-on-click="() => this.saveEdit(col.id, item.id)" style="background: #7f4a7c; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.9rem;">Save</button>
                                                <button t-on-click="() => this.state.editingItemId = null" style="background: #3f3f46; color: #e0e0e0; border: none; padding: 6px 14px; border-radius: 4px; font-weight: 500; cursor: pointer; font-size: 0.9rem;">Cancel</button>
                                            </div>
                                            <button t-on-click="() => this.deleteItem(col.id, item.id)" style="background: #3f3f46; color: #e0e0e0; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.9rem;"><i class="fa fa-trash-o"></i></button>
                                        </div>
                                    </div>
                                </t>
                                <t t-else="">
                                    <div style="background: #242426; border: 1px solid #36363a; padding: 12px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.2); cursor: pointer; margin-bottom: 8px; position: relative;" draggable="true" t-on-dragstart="(ev) => this.onDragStart(ev, item.id)" t-on-click="() => this.openEdit(item)">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <span style="font-size: 1.1rem;">🌴</span>
                                                <span style="font-size: 0.95rem; font-weight: 600; color: #fff;"><t t-esc="item.title"/></span>
                                            </div>
                                            <i class="fa fa-star-o" style="color: #5c5c5e; font-size: 0.9rem;"></i>
                                        </div>
                                        <div style="display: flex; justify-content: space-between; align-items: center;">
                                            <i class="fa fa-clock-o" style="color: #5c5c5e; font-size: 0.9rem;"></i>
                                            <div style="width: 20px; height: 20px; background: #d84b4b; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.7rem; font-weight: bold;">D</div>
                                        </div>
                                    </div>
                                </t>
                            </t>

                            <!-- Empty State for Ongoing -->
                            <t t-if="col.id === 'ongoing' and col.items.length === 0 and state.addingToCol !== col.id">
                                <div style="text-align: center; margin-top: 40px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
                                    <div style="background: #7f4a7c; width: 100px; height: 100px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-bottom: 20px;">
                                        <i class="fa fa-file-text-o" style="font-size: 3rem; color: #fff;"></i>
                                    </div>
                                    <h5 style="margin: 0 0 12px 0; font-size: 1.15rem; font-weight: 700; color: #fff;">Create an Article Item</h5>
                                    <p style="margin: 0; font-size: 0.9rem; color: #a0a0a0; line-height: 1.5; text-align: center;">
                                        Article items are articles that exist inside their parents but are not displayed in the menu. They can be used to handle lists (Buildings, Tasks, ...).
                                    </p>
                                </div>
                            </t>
                        </div>
                    </t>
                    
                    <t t-else="">
                        <!-- Collapsed Column -->
                        <i class="fa fa-plus" style="color: #a0a0a0; cursor: pointer; margin-bottom: 16px;"></i>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <i class="fa fa-arrows-h" style="color: #a0a0a0;"></i>
                            <i class="fa fa-angle-double-right" style="color: #a0a0a0;"></i>
                        </div>
                        <div style="transform: rotate(90deg); transform-origin: left top; margin-top: 16px; white-space: nowrap; font-weight: 500; color: #a0a0a0; letter-spacing: 1px;">
                            <t t-esc="col.title"/>
                        </div>
                    </t>
                </div>
            </t>
            
        </div>
    </div>
`;
