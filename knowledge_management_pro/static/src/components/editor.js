/** @odoo-module **/

import { Component, xml, useState, onWillUpdateProps, useEffect, useRef, onWillStart, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { session } from "@web/session";
import { KnowledgeCalendarBoard } from "./calendar_board";
import { KnowledgeListMockup } from "./list_mockup";

export class KnowledgeKanbanBoard extends Component {
    static template = xml`
        <div class="km_pro_kanban_board" t-on-click="closeMenus">
            <!-- Header Toolbar -->
            <div class="km_pro_kanban_header">
                <div class="km_pro_kanban_header_left">
                    <button class="km_pro_kanban_btn_new" t-on-click="addCardToFirstColumn">New</button>
                    <div class="km_pro_kanban_title_wrap">
                        <span>Kanban of <t t-esc="props.title || 'Items'"/></span>
                        <i class="fa fa-cog km_pro_kanban_gear_btn" t-on-click.stop="toggleSettingsMenu" title="Kanban Settings"></i>
                        <t t-if="state.showSettingsMenu">
                            <div class="km_pro_kanban_settings_menu shadow" t-on-click.stop="">
                                <div class="km_pro_kanban_settings_item" t-on-click="() => { this.addColumn(); state.showSettingsMenu = false; }">
                                    <i class="fa fa-plus"></i> Add a Column
                                </div>
                                <div class="km_pro_kanban_settings_item" t-on-click="() => { this.resetStages(); state.showSettingsMenu = false; }">
                                    <i class="fa fa-refresh"></i> Reset Default Stages
                                </div>
                            </div>
                        </t>
                    </div>
                </div>
                <div class="km_pro_kanban_header_right">
                    <div class="km_pro_kanban_search_box">
                        <i class="fa fa-search km_pro_kanban_search_icon"></i>
                        <input type="text" class="km_pro_kanban_search_input" placeholder="Search..." t-model="state.searchQuery"/>
                        <i t-if="state.searchQuery" class="fa fa-times km_pro_kanban_search_clear" t-on-click="() => state.searchQuery = ''" title="Clear search"></i>
                        <i class="fa fa-caret-down km_pro_kanban_search_caret"></i>
                    </div>
                </div>
            </div>

            <!-- Columns Body -->
            <div class="km_pro_kanban_body">

                <!-- Background Empty State (only shown when no columns exist) -->
                <t t-if="!state.columns or state.columns.length === 0">
                    <div class="km_pro_kanban_empty_state">
                        <div class="km_pro_kanban_empty_circle" t-on-click="addColumn" title="Click to add a stage">
                            <svg width="60" height="70" viewBox="0 0 60 70" fill="none" xmlns="http://www.w3.org/2000/svg" style="position: absolute; top: 25px;">
                                <path d="M0 5C0 2.23858 2.23858 0 5 0H40L60 20V65C60 67.7614 57.7614 70 55 70H5C2.23858 70 0 67.7614 0 65V5Z" fill="white"/>
                                <path d="M40 0V15C40 17.7614 42.2385 20 45 20H60" fill="#E0E0E0"/>
                                <circle cx="20" cy="30" r="3" fill="#879199"/>
                                <circle cx="40" cy="30" r="3" fill="#879199"/>
                                <path d="M22 36C22 36 28 42 38 36" stroke="#879199" stroke-width="2.5" stroke-linecap="round"/>
                                <rect x="15" y="48" width="30" height="3" rx="1.5" fill="#E0E0E0"/>
                                <rect x="15" y="55" width="20" height="3" rx="1.5" fill="#E0E0E0"/>
                            </svg>
                            <svg width="120" height="120" style="position: absolute; top: 0; left: 0;" fill="none">
                                <line x1="45" y1="15" x2="48" y2="23" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
                                <line x1="28" y1="23" x2="36" y2="28" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
                                <line x1="36" y1="12" x2="41" y2="19" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
                            </svg>
                        </div>
                        <h3 class="km_pro_kanban_empty_title">Create an Article Item</h3>
                        <p class="km_pro_kanban_empty_desc">
                            Article items are articles that exist inside their parents but are not displayed in the menu. They can be used to handle lists (Buildings, Tasks, ...).
                        </p>
                    </div>
                </t>

                <t t-foreach="state.columns" t-as="column" t-key="column.id">
                    <t t-if="column.isCollapsed">
                        <!-- Folded Column: Enterprise-style vertical strip -->
                        <div class="km_pro_kanban_col_collapsed" t-on-dragover="onDragOver" t-on-drop="(ev) => this.onDrop(ev, column.id)">
                            <div class="km_pro_kanban_col_collapsed_inner">
                                <i class="fa fa-chevron-right km_pro_col_unfold_icon" t-on-click.stop="() => this.toggleCollapse(column.id)" t-att-title="'Unfold ' + column.title"></i>
                                <div class="km_pro_kanban_collapsed_title" t-on-click="() => this.toggleCollapse(column.id)">
                                    <t t-esc="column.title"/> (<t t-esc="column.cards ? column.cards.length : 0"/>)
                                </div>
                            </div>
                        </div>
                    </t>
                    <t t-else="">
                        <!-- Expanded Column -->
                        <div class="km_pro_kanban_column" t-att-class="{'drag-over': state.dragOverColId === column.id}" t-on-dragover="(ev) => this.onColumnDragOver(ev, column.id)" t-on-dragleave="() => state.dragOverColId = null" t-on-drop="(ev) => this.onDrop(ev, column.id)">
                            <div class="km_pro_kanban_col_header">
                                <div class="km_pro_kanban_col_title_group">
                                    <t t-if="state.editingColId === column.id">
                                        <input class="km_pro_kanban_col_title_input" 
                                               t-att-value="column.title" 
                                               t-on-blur="(ev) => this.finishRenameColumn(column.id, ev.target.value)" 
                                               t-on-keydown="(ev) => ev.key === 'Enter' and this.finishRenameColumn(column.id, ev.target.value)" 
                                               autofocus="autofocus"/>
                                    </t>
                                    <t t-else="">
                                        <span class="km_pro_kanban_col_title" t-on-dblclick="() => state.editingColId = column.id" title="Double click to rename"><t t-esc="column.title"/></span>
                                    </t>
                                    <span class="km_pro_kanban_col_count">(<t t-esc="this.getFilteredCards(column).length"/>)</span>
                                </div>
                                <div class="km_pro_kanban_col_actions">
                                    <i class="fa fa-plus km_pro_kanban_col_btn" t-on-click.stop="() => this.addCard(column.id)" title="Add card"></i>
                                    <i class="fa fa-ellipsis-h km_pro_kanban_col_btn" t-on-click.stop="() => this.toggleColMenu(column.id)" title="Column options"></i>
                                    <!-- Per-column dropdown menu -->
                                    <t t-if="state.openColMenu === column.id">
                                        <div class="km_pro_kanban_col_menu shadow" t-on-click.stop="">
                                            <div class="km_pro_kanban_col_menu_item" t-on-click="() => { this.toggleCollapse(column.id); state.openColMenu = null; }">
                                                <i class="fa fa-compress"></i> Fold
                                            </div>
                                            <div class="km_pro_kanban_col_menu_item" t-on-click="() => { state.editingColId = column.id; state.openColMenu = null; }">
                                                <i class="fa fa-pencil"></i> Rename
                                            </div>
                                            <div class="km_pro_kanban_col_menu_item km_pro_col_menu_danger" t-on-click="() => { this.deleteColumn(column.id); state.openColMenu = null; }">
                                                <i class="fa fa-trash"></i> Delete
                                            </div>
                                        </div>
                                    </t>
                                </div>
                            </div>
                            
                            <!-- Cards Container -->
                            <div class="km_pro_kanban_cards">
                                <t t-foreach="this.getFilteredCards(column)" t-as="card" t-key="card.id">
                                    <t t-if="card.isCreating">
                                        <!-- Inline Creation Card -->
                                        <div class="km_pro_kanban_create_box">
                                            <input type="text" class="km_pro_kanban_create_input" t-model="card.content" placeholder="My New Item" t-on-keydown="(ev) => this.onCardKeydown(ev, column.id, card.id)" autofocus="autofocus"/>
                                            <div class="km_pro_kanban_create_actions">
                                                <button class="km_pro_kanban_btn_add" t-on-click="() => this.saveCard(column.id, card.id)">Add</button>
                                                <button class="km_pro_kanban_btn_discard" t-on-click="() => this.cancelCard(column.id, card.id)">Discard</button>
                                            </div>
                                        </div>
                                    </t>
                                    <t t-else="">
                                        <div class="km_pro_kanban_card" draggable="true" t-on-dragstart="(ev) => this.onDragStart(ev, card.id, column.id)" t-on-click="() => this.props.onCardClick and this.props.onCardClick(card, column.id, () => this.triggerChange())">
                                            <div class="km_pro_card_top_row">
                                                <span class="km_pro_kanban_card_title"><t t-esc="card.content || 'Untitled'"/></span>
                                                <span class="km_pro_card_star_btn" t-on-click.stop="() => this.toggleCardStar(column.id, card.id)" t-att-title="card.isFavorite ? 'Remove star' : 'Star'">
                                                    <i t-attf-class="fa {{ card.isFavorite ? 'fa-star text-warning' : 'fa-star-o' }}"></i>
                                                </span>
                                            </div>
                                            <div class="km_pro_card_bottom_row">
                                                <div class="km_pro_card_activity_btn" title="Activity">
                                                    <i t-attf-class="fa fa-clock-o km_pro_activity_clock"></i>
                                                </div>
                                                <div class="km_pro_card_user_avatar" t-att-title="this.getCardUserName(card)">
                                                    <t t-esc="this.getCardUserInitial(card)"/>
                                                </div>
                                            </div>
                                        </div>
                                    </t>
                                </t>
                            </div>
                        </div>
                    </t>
                </t>

                <!-- Add Item Stage (Enterprise-style: vertical folded strip) -->
                <div class="km_pro_kanban_add_stage_btn" t-on-click="addColumn" title="Add a new stage">
                    <div class="km_pro_kanban_add_stage_inner">
                        <i class="fa fa-chevron-right km_pro_add_stage_chevron"></i>
                        <span class="km_pro_add_stage_label">Add an Item Stage</span>
                    </div>
                </div>
            </div>
        </div>
    `;

    static props = ["title", "initialData", "onChange", "onCardClick"];

    

    setup() {
        this.state = useState({
            columns: [],
            activeColumnMenu: null,
            openColMenu: null,
            showSettingsMenu: false,
            searchQuery: "",
            dragOverColId: null,
            editingColId: null,
        });

        this.loadData(this.props.initialData);

        onWillUpdateProps((nextProps) => {
            if (nextProps.initialData !== this.props.initialData) {
                this.loadData(nextProps.initialData);
            }
        });
    }

    loadData(rawData) {
        let initialData = { columns: [] };
        if (rawData) {
            try {
                initialData = typeof rawData === 'string' ? JSON.parse(rawData) : rawData;
            } catch (e) {
                console.error("Failed to parse Kanban initial data", e);
            }
        }
        if (!initialData.columns || initialData.columns.length === 0) {
            initialData.columns = [
                { id: this.generateId(), title: 'New', cards: [], isCollapsed: false },
                { id: this.generateId(), title: 'Ongoing', cards: [], isCollapsed: false },
                { id: this.generateId(), title: 'Done', cards: [], isCollapsed: true }
            ];
        }
        
        initialData.columns.forEach(col => {
            if (col.isCollapsed === undefined) col.isCollapsed = false;
            if (!col.cards) col.cards = [];
        });

        this.state.columns = initialData.columns;
    }

    get totalCardsCount() {
        return this.state.columns.reduce((sum, col) => sum + (col.cards ? col.cards.length : 0), 0);
    }

    getFilteredCards(column) {
        if (!this.state.searchQuery || !this.state.searchQuery.trim()) {
            return column.cards || [];
        }
        const q = this.state.searchQuery.trim().toLowerCase();
        return (column.cards || []).filter(c => (c.content || '').toLowerCase().includes(q));
    }

    closeMenus() {
        this.state.activeColumnMenu = null;
        this.state.showSettingsMenu = false;
        this.state.openColMenu = null;
    }

    toggleColMenu(colId) {
        this.state.openColMenu = this.state.openColMenu === colId ? null : colId;
    }

    toggleSettingsMenu() {
        this.state.showSettingsMenu = !this.state.showSettingsMenu;
        this.state.activeColumnMenu = null;
    }

    toggleColumnMenu(colId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        this.state.showSettingsMenu = false;
        if (this.state.activeColumnMenu === colId) {
            this.state.activeColumnMenu = null;
        } else {
            this.state.activeColumnMenu = colId;
        }
    }

    generateId() {
        return Math.random().toString(36).substring(2, 9);
    }

    triggerChange() {
        if (this.props.onChange) {
            this.props.onChange(JSON.stringify({ columns: this.state.columns }));
        }
    }

    addCardToFirstColumn() {
        if (this.state.columns.length > 0) {
            const firstCol = this.state.columns[0];
            const initial = session && session.partner_display_name ? session.partner_display_name.charAt(0).toUpperCase() : 'D';
            const name = session && session.partner_display_name ? session.partner_display_name : 'User';
            firstCol.cards.push({ 
                id: this.generateId(), 
                content: '', 
                isCreating: true, 
                article_content: '',
                isFavorite: false,
                hasActivity: false,
                userInitial: initial,
                userName: name
            });
            firstCol.isCollapsed = false;
            this.triggerChange();
        }
    }

    toggleCardStar(colId, cardId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            const card = col.cards.find(c => c.id === cardId);
            if (card) {
                card.isFavorite = !card.isFavorite;
                this.triggerChange();
            }
        }
    }

    toggleCardActivity(colId, cardId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            const card = col.cards.find(c => c.id === cardId);
            if (card) {
                card.hasActivity = !card.hasActivity;
                this.triggerChange();
            }
        }
    }

    getCardUserInitial(card) {
        if (card.userInitial) return card.userInitial;
        if (session && session.partner_display_name) {
            return session.partner_display_name.charAt(0).toUpperCase();
        }
        return 'D';
    }

    getCardUserName(card) {
        if (card.userName) return card.userName;
        if (session && session.partner_display_name) {
            return session.partner_display_name;
        }
        return 'User';
    }

    toggleCollapse(colId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            col.isCollapsed = !col.isCollapsed;
            this.triggerChange();
        }
    }

    addColumn() {
        this.state.columns.push({ id: this.generateId(), title: 'New Column', cards: [], isCollapsed: false });
        this.triggerChange();
    }

    resetStages() {
        if (confirm("Reset columns to default stages (New, Ongoing, Done)? Cards will be kept in the first column.")) {
            const allCards = [];
            this.state.columns.forEach(c => (c.cards || []).forEach(card => allCards.push(card)));
            this.state.columns = [
                { id: this.generateId(), title: 'New', cards: allCards, isCollapsed: false },
                { id: this.generateId(), title: 'Ongoing', cards: [], isCollapsed: false },
                { id: this.generateId(), title: 'Done', cards: [], isCollapsed: true }
            ];
            this.triggerChange();
        }
    }

    deleteColumn(colId) {
        this.state.activeColumnMenu = null;
        if (confirm("Are you sure you want to delete this column and all its cards?")) {
            this.state.columns = this.state.columns.filter(c => c.id !== colId);
            this.triggerChange();
        }
    }

    finishRenameColumn(colId, newTitle) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col && newTitle && newTitle.trim()) {
            col.title = newTitle.trim();
            this.triggerChange();
        }
        this.state.editingColId = null;
    }

    addCard(colId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            const initial = session && session.partner_display_name ? session.partner_display_name.charAt(0).toUpperCase() : 'D';
            const name = session && session.partner_display_name ? session.partner_display_name : 'User';
            col.cards.push({ 
                id: this.generateId(), 
                content: '', 
                isCreating: true, 
                article_content: '',
                isFavorite: false,
                hasActivity: false,
                userInitial: initial,
                userName: name
            });
            col.isCollapsed = false;
            this.triggerChange();
        }
    }
    
    saveCard(colId, cardId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            const card = col.cards.find(c => c.id === cardId);
            if (card) {
                card.content = (card.content || '').trim() || 'Untitled';
                card.isCreating = false;
                this.triggerChange();
            }
        }
    }

    cancelCard(colId, cardId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            col.cards = col.cards.filter(c => c.id !== cardId);
            this.triggerChange();
        }
    }

    onCardKeydown(ev, colId, cardId) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            this.saveCard(colId, cardId);
        } else if (ev.key === 'Escape') {
            ev.preventDefault();
            this.cancelCard(colId, cardId);
        }
    }

    deleteCard(colId, cardId) {
        const col = this.state.columns.find(c => c.id === colId);
        if (col) {
            col.cards = col.cards.filter(c => c.id !== cardId);
            this.triggerChange();
        }
    }

    onDragStart(ev, cardId, colId) {
        ev.dataTransfer.setData('cardId', cardId);
        ev.dataTransfer.setData('colId', colId);
    }

    onColumnDragOver(ev, colId) {
        ev.preventDefault();
        this.state.dragOverColId = colId;
    }

    onDragOver(ev) {
        ev.preventDefault();
    }

    onDrop(ev, targetColId) {
        ev.preventDefault();
        this.state.dragOverColId = null;
        const cardId = ev.dataTransfer.getData('cardId');
        const sourceColId = ev.dataTransfer.getData('colId');
        
        if (!cardId || !sourceColId) return;

        const sourceCol = this.state.columns.find(c => c.id === sourceColId);
        const targetCol = this.state.columns.find(c => c.id === targetColId);
        
        if (sourceCol && targetCol) {
            const cardIndex = sourceCol.cards.findIndex(c => c.id === cardId);
            if (cardIndex > -1) {
                const [card] = sourceCol.cards.splice(cardIndex, 1);
                targetCol.cards.push(card);
                targetCol.isCollapsed = false;
                this.triggerChange();
            }
        }
    }
}

export class KnowledgeManagementEditor extends Component {
    static props = {
        activeArticleId: { type: Number, optional: true },
        isFavorite: { type: Boolean, optional: true },
        toggleFavorite: { type: Function, optional: true },
        duplicateArticle: { type: Function, optional: true },
        deleteArticle: { type: Function, optional: true },
        moveArticle: { type: Function, optional: true },
        toggleLock: { type: Function, optional: true },
        openTemplatesModal: { type: Function, optional: true },
        onTitleChange: { type: Function, optional: true },
        createNewArticle: { type: Function, optional: true },
        setActiveArticle: { type: Function, optional: true },
    };

    

    getActiveEditorEl() {
        if (this.state.activeCard && this.cardContentRef && this.cardContentRef.el) {
            return this.cardContentRef.el;
        }
        return this.contentRef ? this.contentRef.el : null;
    }
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.session = session;
        this.state = useState({
            article: null,
            isLoading: false,
            showKanbanDialog: false,
            kanbanItemName: "",
            isSearchModalOpen: false,
            searchQuery: "",
            isMoveModalOpen: false,
            moveSearchQuery: "",
            articleToMove: null,
            isHistoryModalOpen: false,
            historyVersions: [],
            selectedHistoryVersion: null,
            compareVersion: null,
            showHistoryComparison: false,
            isKanbanMode: false,
            activeCard: null,
            activeCardColId: null,
            articleTags: [],
            allTags: [],
            isTagMenuOpen: false,
            tagSearchQuery: "",
            kanbanTitle: "",
            kanbanData: null,
            kanbanBelowHasContent: false,
            isHeadingLinkVisible: false,
            headingLinkTop: 0,
            headingLinkLeft: 0,
            activeHeadingNode: null,
            showListDialog: false,
            listItemName: "",
            isListMode: false,
            listTitle: "",
            listData: null,
            showCalendarDialog: false,
            calendarItemName: "",
            isCalendarMode: false,
            calendarTitle: "",
            calendarData: null,
            isShareMenuOpen: false,
            shareToWeb: false,
            generalAccess: "Members only",
            isGeneralAccessDropdownOpen: false,
            isInviteModalOpen: false,
            invitePermission: "Edit",
            isCommentModalOpen: false,
            commentModalTop: 0,
            commentModalLeft: 0,
            commentContent: "",
            activeCommentAnchorId: null,
            articleComments: [],
            toolbarRange: null,
            isInvitePermissionDropdownOpen: false,
            allUsers: [],
            inviteSearchQuery: "",
            selectedUsersToInvite: [],
            currentShares: [],
            isChatterOpen: false,
            isMoreMenuOpen: false,
            isFullWidth: false,
            isEmojiPickerOpen: false,
            isRepositioning: false,
            isDraggingCover: false,
            coverStartY: 0,
            isCoverModalOpen: false,
            coverModalTab: 'unsplash',
            unsplashQuery: '',
            unsplashImages: [],
            isUnsplashLoading: false,
            coverUrl: '',
            isCoverDownloading: false,
            isToolbarVisible: false,
            toolbarTop: 0,
            toolbarLeft: 0,
            isMoreFormatMenuOpen: false,
            selectedImage: null,
            imageToolbarTop: 0,
            imageToolbarLeft: 0,
            isSlashMenuOpen: false,
            slashMenuTop: 0,
            slashMenuLeft: 0,
            slashMenuSelectedIndex: 0,
            isLineEmptyVisible: false,
            lineEmptyTop: 0,
            lineEmptyLeft: 0,
            selectedTable: null,
            tableToolbarTop: 0,
            tableToolbarLeft: 0,
            isCropModalOpen: false,
            cropAspectRatio: NaN,
            imageSizeLabel: '100%',
        });

        this.cropperInstance = null;

        this.slashMenuItems = [
            { id: 'h1', title: 'Heading 1', description: 'Big section heading.', icon: 'fa-header', command: 'formatBlock', value: 'H1' },
            { id: 'h2', title: 'Heading 2', description: 'Medium section heading.', icon: 'fa-header', command: 'formatBlock', value: 'H2' },
            { id: 'h3', title: 'Heading 3', description: 'Small section heading.', icon: 'fa-header', command: 'formatBlock', value: 'H3' },
            { id: 'p', title: 'Text', description: 'Just start writing with plain text.', icon: 'fa-font', command: 'formatBlock', value: 'P' },
            { id: 'bullet', title: 'Bulleted List', description: 'Create a simple bulleted list.', icon: 'fa-list-ul', command: 'insertUnorderedList' },
            { id: 'number', title: 'Numbered List', description: 'Create a list with numbering.', icon: 'fa-list-ol', command: 'insertOrderedList' },
            { id: 'checkbox', title: 'To-do List', description: 'Track tasks with a to-do list.', icon: 'fa-check-square-o', action: 'insertCheckbox' },
            { id: 'image', title: 'Image', description: 'Upload or embed with a link.', icon: 'fa-image', action: 'triggerImageUpload' },
            { id: 'video', title: 'Video', description: 'Embed a video from URL.', icon: 'fa-video-camera', action: 'insertVideo' },
            { id: 'document', title: 'Document', description: 'Upload a document or file.', icon: 'fa-upload', action: 'triggerDocumentUpload' },
            { id: 'table', title: 'Table', description: 'Add simple tabular content.', icon: 'fa-table', action: 'insertTable' },
            { id: 'kanban', title: 'Kanban', description: 'Build an Item Kanban.', icon: 'fa-th-large', action: 'onQuickActionKanban' },
            { id: 'list', title: 'List', description: 'Build an Item List.', icon: 'fa-list', action: 'onQuickActionList' },
            { id: 'calendar', title: 'Calendar', description: 'Build an Item Calendar.', icon: 'fa-calendar', action: 'onQuickActionCalendar' },
            { id: 'columns', title: 'Columns', description: 'Add 2 columns layout.', icon: 'fa-columns', action: 'insertColumns' },
            { id: 'link', title: 'Button Link', description: 'Add a clickable button.', icon: 'fa-link', action: 'insertLink' },
            { id: 'code', title: 'Code Block', description: 'Insert a code snippet.', icon: 'fa-code', command: 'formatBlock', value: 'PRE' },
            { id: 'divider', title: 'Divider', description: 'Insert a horizontal rule.', icon: 'fa-minus', command: 'insertHorizontalRule' },
            { id: 'strikethrough', title: 'Strikethrough', description: 'Cross out text.', icon: 'fa-strikethrough', command: 'strikeThrough' },
        ];
        
        this.contentRef = useRef("content");
        this.rootRef = useRef("root");
        this.fileInputRef = useRef("fileInput");
        this.imageInputRef = useRef("imageInput");
        this.documentInputRef = useRef("documentInput");
        this.saveTimeout = null;

        onWillStart(async () => {
            if (this.props.activeArticleId) {
                await this.loadArticle(this.props.activeArticleId);
            }
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.activeArticleId !== this.props.activeArticleId) {
                await this.loadArticle(nextProps.activeArticleId);
            }
        });

        onMounted(() => {
            if (this.state.article) {
                this.updateDOMContent(this.state.article);
            }
        });

        useEffect(() => {
            if (this.state.article && this.getActiveEditorEl()) {
                if (this.getActiveEditorEl().innerHTML !== this.state.article.content && this.state.article.content !== undefined) {
                    this.updateDOMContent(this.state.article);
                }
            }
        }, () => [this.props.activeArticleId]);

        this.closeMenus = (ev) => {
            if (this.state.isShareMenuOpen && !ev.target.closest('.km_pro_share_menu') && !ev.target.closest('.km_pro_share_btn')) {
                this.state.isShareMenuOpen = false;
            }
            if (this.state.isMoreMenuOpen && !ev.target.closest('.km_pro_more_menu') && !ev.target.closest('.km_pro_more_btn')) {
                this.state.isMoreMenuOpen = false;
            }
            if (this.state.isMoreFormatMenuOpen && !ev.target.closest('.km_pro_more_format_menu') && !ev.target.closest('.km_pro_more_format_btn')) {
                this.state.isMoreFormatMenuOpen = false;
            }
            if (this.state.isEmojiPickerOpen && !ev.target.closest('.km_pro_emoji_picker') && !ev.target.closest('.km_pro_icon_display')) {
                this.state.isEmojiPickerOpen = false;
            }
            if (!ev.target.closest('.general-access-trigger') && !ev.target.closest('.km_pro_nested_dropdown')) {
                this.state.isGeneralAccessDropdownOpen = false;
            }
            
            if (!ev.target.closest('.invite-permission-trigger') && !ev.target.closest('.km_pro_nested_dropdown')) {
                this.state.isInvitePermissionDropdownOpen = false;
            }
            if (this.state.selectedImage && !ev.target.closest('.km_pro_image_toolbar') && ev.target !== this.state.selectedImage) {
                this.state.selectedImage.style.outline = '2px solid transparent';
                this.state.selectedImage = null;
            }
            if (this.state.selectedTable && !ev.target.closest('.km_pro_table_toolbar') && !ev.target.closest('.km_pro_table')) {
                this.state.selectedTable.style.outline = 'none';
                this.state.selectedTable = null;
            }
            if (this.state.isSlashMenuOpen && !ev.target.closest('.km_pro_slash_menu') && !ev.target.closest('.fa-ellipsis-v')) {
                this.state.isSlashMenuOpen = false;
            }
        };

        this.handleScroll = () => {
            if (this.state.isSlashMenuOpen || this.state.isLineEmptyVisible) {
                this.state.isSlashMenuOpen = false;
                this.state.isLineEmptyVisible = false;
                this.render();
            }
        };

        this.handleSelection = () => {
            const selection = window.getSelection();
            if (!selection.anchorNode) return;
            
            const inContent = this.getActiveEditorEl() && this.getActiveEditorEl().contains(selection.anchorNode);
            
            if (!inContent) {
                if (this.state.isToolbarVisible) {
                    this.state.isToolbarVisible = false;
                }
                return;
            }
            if (inContent && selection.rangeCount > 0) {
                this.state.savedRange = selection.getRangeAt(0).cloneRange();
            }
            
            if (!selection.isCollapsed && selection.toString().trim().length > 0) {
                const range = selection.getRangeAt(0);
                this.state.toolbarRange = range.cloneRange();
                const rect = range.getBoundingClientRect();
                this.state.toolbarTop = rect.top - 45;
                this.state.toolbarLeft = rect.left + (rect.width / 2);
                this.state.isToolbarVisible = true;
            } else {
                this.state.toolbarRange = null;
                if (this.state.isToolbarVisible) {
                    this.state.isToolbarVisible = false;
                }
            }

        };

        useEffect(() => {
            document.addEventListener("click", this.closeMenus);
            document.addEventListener("selectionchange", this.handleSelection);
            if (this.rootRef.el) this.rootRef.el.addEventListener("scroll", this.handleScroll);
            return () => {
                document.removeEventListener("click", this.closeMenus);
                document.removeEventListener("selectionchange", this.handleSelection);
            if (this.rootRef.el) this.rootRef.el.removeEventListener("scroll", this.handleScroll);
            };
        });
    }

    async copyLink() {
        try {
            await navigator.clipboard.writeText(window.location.href);
            window.alert("Link copied to clipboard!");
        } catch (err) {
            console.error("Failed to copy link", err);
        }
        this.state.searchQuery = "";
    }

    stripHtml(html) {
        if (!html) return 'Untitled';
        const tmp = document.createElement("DIV");
        tmp.innerHTML = html;
        return tmp.textContent || tmp.innerText || "Untitled";
    }

    async loadArticle(articleId) {
        if (!articleId) {
            this.state.article = null;
            return;
        }
        
        this.state.isLoading = true;
        try {
            const result = await this.orm.read("knowledge.management.article", [articleId], ["name", "content", "write_date", "write_uid", "icon", "cover_image", "cover_position", "is_locked", "shared_partner_ids", "is_full_width", "tag_ids"]);
            if (result.length > 0) {
                this.state.article = result[0];
                this.state.articleTags = [];
                if (this.state.article.tag_ids && this.state.article.tag_ids.length > 0) {
                    this.state.articleTags = await this.orm.searchRead("knowledge.management.tag", [["id", "in", this.state.article.tag_ids]], ["name", "color"]);
                }
                this.updateDOMContent(this.state.article);
                await this.loadComments();
            }
        } catch (error) {
            console.error("Failed to load article", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    updateDOMContent(article) {
        this.state.isFullWidth = article.is_full_width || false;
        
        if (article.content && article.content.includes('data-kanban="true"')) {
            this.state.isKanbanMode = true;
            const matchTitle = article.content.match(/data-kanban-title="([^"]*)"/);
            this.state.kanbanTitle = matchTitle ? matchTitle[1] : 'Items';
            
            const matchData = article.content.match(/data-kanban-data='([^']*)'/);
            this.state.kanbanData = matchData ? matchData[1] : null;
            
            const kanbanEnd = article.content.indexOf('</div>');
            const savedHtml = kanbanEnd !== -1 ? article.content.substring(kanbanEnd + 6) : '';
            if (this.getActiveEditorEl()) {
                this.getActiveEditorEl().innerHTML = savedHtml;
            }
        } else if (article.content && article.content.includes('data-list="true"')) {
            this.state.isKanbanMode = false;
            this.state.isListMode = true;
            this.state.isCalendarMode = false;
            const match = article.content.match(/data-list-title="([^"]*)"/);
            this.state.listTitle = match ? match[1] : 'Items';
            const matchListData = article.content.match(/data-list-data='([^']*)'/);
            this.state.listData = matchListData ? matchListData[1] : null;
            const listEnd = article.content.indexOf('</div>');
            const savedListHtml = listEnd !== -1 ? article.content.substring(listEnd + 6) : '';
            if (this.contentRef && this.contentRef.el) {
                this.contentRef.el.innerHTML = savedListHtml;
            }
        } else if (article.content && article.content.includes('data-calendar="true"')) {
            this.state.isKanbanMode = false;
            this.state.isListMode = false;
            this.state.isCalendarMode = true;
            const match = article.content.match(/data-calendar-title="([^"]*)"/);
            this.state.calendarTitle = match ? match[1] : 'Items';
            const matchData = article.content.match(/data-calendar-data='([^']*)'/);
            this.state.calendarData = matchData ? matchData[1] : null;
        } else {
            this.state.isKanbanMode = false;
            this.state.isListMode = false;
            this.state.isCalendarMode = false;
            if (this.getActiveEditorEl()) {
                this.getActiveEditorEl().innerHTML = article.content || '';
            }
        }
    }



    onEditorKeydown(ev) {
        setTimeout(() => this.checkLineEmpty(), 10);
        if (this.state.isSlashMenuOpen) {
            if (ev.key === 'ArrowDown') {
                ev.preventDefault();
                this.state.slashMenuSelectedIndex = (this.state.slashMenuSelectedIndex + 1) % this.slashMenuItems.length;
                return;
            } else if (ev.key === 'ArrowUp') {
                ev.preventDefault();
                this.state.slashMenuSelectedIndex = (this.state.slashMenuSelectedIndex - 1 + this.slashMenuItems.length) % this.slashMenuItems.length;
                return;
            } else if (ev.key === 'Enter') {
                ev.preventDefault();
                const selectedItem = this.slashMenuItems[this.state.slashMenuSelectedIndex];
                if (selectedItem) {
                    this.executeSlashCommand(selectedItem);
                }
                return;
            } else if (ev.key === 'Escape') {
                this.state.isSlashMenuOpen = false;
                return;
            } else if (ev.key !== '/') {
                this.state.isSlashMenuOpen = false;
            }
        }

        if (ev.key === 'Enter') {
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                
                let container = range.startContainer;
                let offset = range.startOffset;
                
                if (container.nodeType === Node.ELEMENT_NODE && offset > 0) {
                    const prevNode = container.childNodes[offset - 1];
                    if (prevNode && prevNode.tagName === 'IMG') {
                        const zws = document.createTextNode('\u200B');
                        prevNode.parentNode.insertBefore(zws, prevNode.nextSibling);
                        range.setStart(zws, 1);
                        range.setEnd(zws, 1);
                        selection.removeAllRanges();
                        selection.addRange(range);
                    }
                }

                let node = range.startContainer;
                while (node && node !== this.getActiveEditorEl()) {
                    if (node.tagName === 'PRE') {
                        ev.preventDefault();
                        const br = document.createTextNode('\\n');
                        range.deleteContents();
                        range.insertNode(br);
                        range.setStartAfter(br);
                        range.setEndAfter(br);
                        selection.removeAllRanges();
                        selection.addRange(range);
                        this.onInput();
                        return;
                    }
                    node = node.parentNode;
                }
            }
        }

        if (ev.key === 'Backspace') {
            const selection = window.getSelection();
            if (selection.rangeCount > 0 && selection.isCollapsed) {
                const range = selection.getRangeAt(0);
                let blockNode = range.startContainer;
                
                while (blockNode && blockNode !== this.getActiveEditorEl() && !this.isBlockElement(blockNode)) {
                    blockNode = blockNode.parentNode;
                }

                if (blockNode && this.isBlockElement(blockNode)) {
                    const preCaretRange = range.cloneRange();
                    preCaretRange.selectNodeContents(blockNode);
                    preCaretRange.setEnd(range.startContainer, range.startOffset);
                    
                    if (preCaretRange.toString().length === 0) {
                        const prevSibling = blockNode.previousElementSibling;
                        const textTags = ['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'BLOCKQUOTE'];
                        
                        if (prevSibling && textTags.includes(prevSibling.tagName.toUpperCase()) && textTags.includes(blockNode.tagName.toUpperCase())) {
                            ev.preventDefault();
                            
                            const cursorNode = document.createTextNode('');
                            prevSibling.appendChild(cursorNode);
                            
                            while(blockNode.firstChild) {
                                prevSibling.appendChild(blockNode.firstChild);
                            }
                            blockNode.remove();
                            
                            const newRange = document.createRange();
                            newRange.setStart(cursorNode, 0);
                            newRange.setEnd(cursorNode, 0);
                            selection.removeAllRanges();
                            selection.addRange(newRange);
                            
                            const inputEvent = new Event('input', { bubbles: true });
                            if (this.contentRef && this.getActiveEditorEl()) {
                                this.getActiveEditorEl().dispatchEvent(inputEvent);
                            } else {
                                ev.target.dispatchEvent(inputEvent);
                            }
                            return;
                        } else if (!prevSibling && ['H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(blockNode.tagName.toUpperCase())) {
                            // If it's a heading at the very beginning of the document, convert it to a paragraph
                            ev.preventDefault();
                            const p = document.createElement('P');
                            while(blockNode.firstChild) {
                                p.appendChild(blockNode.firstChild);
                            }
                            if (p.childNodes.length === 0) {
                                p.innerHTML = '<br>';
                            }
                            
                            const parentNode = blockNode.parentNode;
                            if (parentNode) {
                                parentNode.replaceChild(p, blockNode);
                            }
                            
                            const newRange = document.createRange();
                            newRange.setStart(p, 0);
                            newRange.setEnd(p, 0);
                            selection.removeAllRanges();
                            selection.addRange(newRange);
                            
                            const inputEvent = new Event('input', { bubbles: true });
                            if (this.contentRef && this.getActiveEditorEl()) {
                                this.getActiveEditorEl().dispatchEvent(inputEvent);
                            } else {
                                (parentNode || ev.target).dispatchEvent(inputEvent);
                            }
                            return;
                        }
                    }
                }
            }
        }

        if (ev.key === '/') {
            ev.preventDefault();
            document.execCommand('insertText', false, '/');
            
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                
                let dummy = document.createElement('span');
                dummy.appendChild(document.createTextNode('\u200b'));
                range.insertNode(dummy);
                let rect = dummy.getBoundingClientRect();
                
                const parent = dummy.parentNode;
                parent.removeChild(dummy);
                
                const menuHeight = 300;
                let topPos = rect.bottom + 10;
                if (rect.bottom + menuHeight > window.innerHeight) {
                    topPos = rect.top - menuHeight - 10;
                }
                
                this.state.slashMenuTop = topPos;
                this.state.slashMenuLeft = rect.left;
                this.state.isSlashMenuOpen = true;
                this.state.slashMenuSelectedIndex = 0;
            }
            return;
        }
    }

    checkLineEmpty() {
        if (!this.contentRef || !this.getActiveEditorEl()) return;
        
        if (this.state.selectedImage || this.state.selectedTable) {
            this.state.isLineEmptyVisible = false;
            return;
        }
        
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) {
            this.state.isLineEmptyVisible = false;
            return;
        }

        const range = selection.getRangeAt(0);
        
        if (!this.getActiveEditorEl().contains(range.startContainer)) {
            this.state.isLineEmptyVisible = false;
            return;
        }

        if (this.getActiveEditorEl().innerText.trim() === '') {
            const rect = this.getActiveEditorEl().getBoundingClientRect();
            this.state.lineEmptyTop = rect.top;
            this.state.lineEmptyLeft = rect.left;
            this.state.isLineEmptyVisible = true;
            return;
        }

        let node = range.startContainer;
        while (node && node !== this.getActiveEditorEl() && !this.isBlockElement(node)) {
            node = node.parentNode;
        }

        let isEmpty = false;
        if (node === this.getActiveEditorEl()) {
            if (node.innerText.trim() === '') {
                isEmpty = true;
            } else {
                const offset = range.startOffset;
                if (offset > 0) {
                    const prevNode = node.childNodes[offset - 1];
                    if (prevNode && prevNode.tagName === 'BR') {
                        const nextNode = node.childNodes[offset];
                        if (!nextNode || nextNode.tagName === 'BR') {
                            isEmpty = true;
                        }
                    }
                } else if (offset === 0) {
                    const nextNode = node.childNodes[0];
                    if (nextNode && nextNode.tagName === 'BR') isEmpty = true;
                }
            }
        } else if (node) {
            const text = node.innerText || node.textContent;
            isEmpty = (text.trim() === '' || text === '\n');
        }

        if (isEmpty) {
            let rectTop = 0;
            let rectLeft = 0;
            const rangeRects = range.getClientRects();
            if (rangeRects.length > 0) {
                rectTop = rangeRects[0].top;
                rectLeft = rangeRects[0].left;
            } else {
                let targetElement = node;
                if (node === this.getActiveEditorEl()) {
                    const offset = range.startOffset;
                    if (offset < node.childNodes.length) {
                        targetElement = node.childNodes[offset];
                    }
                }
                
                if (targetElement && targetElement.nodeType === Node.ELEMENT_NODE) {
                    const nodeRect = targetElement.getBoundingClientRect();
                    rectTop = nodeRect.top;
                    rectLeft = nodeRect.left;
                }
            }
            
            if (rectTop === 0 && rectLeft === 0) {
                this.state.isLineEmptyVisible = false;
            } else {
                this.state.lineEmptyTop = rectTop;
                this.state.lineEmptyLeft = rectLeft;
                this.state.isLineEmptyVisible = true;
            }
        } else {
            this.state.isLineEmptyVisible = false;
        }
    }

    isBlockElement(node) {
        if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
        const blockTags = ['P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'BLOCKQUOTE', 'PRE', 'TABLE'];
        return blockTags.includes(node.tagName.toUpperCase());
    }

    onEditorMouseMove(ev) {
        if (!this.contentRef || !this.getActiveEditorEl()) return;
        
        let target = ev.target;
        let isHeading = false;
        
        while (target && target !== ev.currentTarget) {
            if (target.tagName && ['H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(target.tagName.toUpperCase())) {
                isHeading = true;
                break;
            }
            target = target.parentNode;
        }

        if (isHeading) {
            if (!target.id) {
                target.id = 'heading-' + Math.random().toString(36).substr(2, 9);
            }
            const range = document.createRange();
            range.selectNodeContents(target);
            const textRects = range.getClientRects();
            
            if (textRects.length > 0) {
                const textRect = textRects[textRects.length - 1]; // last line of the text
                this.state.headingLinkTop = textRect.top + (textRect.height / 2) - 12; // 12 is half of icon height
                this.state.headingLinkLeft = textRect.right + 8;
                this.state.isHeadingLinkVisible = true;
                this.state.activeHeadingNode = target;
            } else {
                this.state.isHeadingLinkVisible = false;
            }
        } else {
            const isHoveringLink = ev.target.closest('.km_pro_heading_link');
            if (!isHoveringLink) {
                this.state.isHeadingLinkVisible = false;
            }
        }
    }

    copyHeadingLink() {
        if (this.state.activeHeadingNode && this.state.activeHeadingNode.id) {
            const headingId = this.state.activeHeadingNode.id;
            const url = new URL(window.location.href);
            url.hash = headingId;
            navigator.clipboard.writeText(url.toString()).then(() => {
                if (this.notification) {
                    this.notification.add("Link copied to clipboard", { type: "success" });
                }
                this.state.isHeadingLinkVisible = false;
            });
        }
    }

    formatTime(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        if (isNaN(d)) return dateStr;
        return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }

    async loadComments() {
        if (!this.props.activeArticleId) return;
        try {
            const comments = await this.orm.searchRead(
                "knowledge.management.comment",
                [["article_id", "=", this.props.activeArticleId], ["is_resolved", "=", false]],
                ["id", "content", "user_id", "date", "anchor_id"]
            );
            this.state.articleComments = comments;
            
            if (this.getActiveEditorEl()) {
                const existingIndicators = this.getActiveEditorEl().querySelectorAll('.km_pro_comment_indicator');
                existingIndicators.forEach(ind => ind.remove());

                comments.forEach(comment => {
                    if (comment.anchor_id) {
                        const anchor = this.getActiveEditorEl().querySelector(`#${comment.anchor_id}`);
                        if (anchor) {
                            anchor.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
                            const indicator = document.createElement('img');
                            indicator.className = 'km_pro_comment_indicator';
                            indicator.src = `/web/image?model=res.users&id=${comment.user_id[0]}&field=avatar_128`;
                            indicator.style.display = 'inline-block';
                            indicator.style.verticalAlign = 'middle';
                            indicator.style.marginLeft = '6px';
                            indicator.style.width = '24px';
                            indicator.style.height = '24px';
                            indicator.style.borderRadius = '50%';
                            indicator.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)';
                            indicator.style.cursor = 'pointer';
                            indicator.style.border = '2px solid #242426';
                            indicator.title = 'View Comment';
                            indicator.contentEditable = 'false';
                            
                            indicator.addEventListener('click', (ev) => {
                                ev.preventDefault();
                                ev.stopPropagation();
                                const rect = indicator.getBoundingClientRect();
                                this.state.commentModalTop = rect.bottom + 8;
                                this.state.commentModalLeft = rect.left > 225 ? rect.left - 225 : 10;
                                this.state.activeCommentAnchorId = comment.anchor_id;
                                this.state.commentContent = "";
                                this.state.isCommentModalOpen = true;
                            });
                            anchor.appendChild(indicator);
                        }
                    }
                });
            }
        } catch (e) {
            console.error("Error loading comments", e);
        }
    }

    async postComment() {
        if (!this.state.commentContent.trim() || !this.state.activeCommentAnchorId) return;

        try {
            await this.orm.create("knowledge.management.comment", [{
                content: this.state.commentContent,
                article_id: this.props.activeArticleId,
                anchor_id: this.state.activeCommentAnchorId,
            }]);
            
            this.state.isCommentModalOpen = false;
            this.state.commentContent = "";
            this.state.activeCommentAnchorId = null;
            this.onInput(); 
            await this.loadComments();
        } catch (e) {
            console.error("Error posting comment", e);
            this.notification.add("Failed to post comment", { type: "danger" });
        }
    }

    cancelComment() {
        if (this.state.activeCommentAnchorId) {
            const anchor = this.getActiveEditorEl().querySelector(`#${this.state.activeCommentAnchorId}`);
            if (anchor && !anchor.querySelector('.km_pro_comment_indicator')) {
                // If it's a newly created anchor without a saved comment, unwrap it
                const parent = anchor.parentNode;
                while (anchor.firstChild) {
                    parent.insertBefore(anchor.firstChild, anchor);
                }
                parent.removeChild(anchor);
            }
        }
        this.state.isCommentModalOpen = false;
        this.state.commentContent = "";
        this.state.activeCommentAnchorId = null;
        this.onInput();
    }

    addComment() {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
            this.notification.add("Please select text to comment on", { type: "warning" });
            return;
        }

        const range = selection.getRangeAt(0);
        const anchorId = 'comment_' + Math.random().toString(36).substr(2, 9);

        try {
            const span = document.createElement('span');
            span.className = 'km_pro_comment_anchor';
            span.id = anchorId;
            span.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
            range.surroundContents(span);
            
            const rect = span.getBoundingClientRect();
            this.state.commentModalTop = rect.bottom + 8;
            this.state.commentModalLeft = rect.left;
            this.state.activeCommentAnchorId = anchorId;
            this.state.commentContent = "";
            this.state.isCommentModalOpen = true;
            this.onInput();
        } catch (e) {
            // Fallback for complex ranges crossing blocks
            document.execCommand('insertHTML', false, `<span class="km_pro_comment_anchor" id="${anchorId}" style="background-color: rgba(255, 255, 0, 0.3);">${selection.toString()}</span>`);
            const span = this.getActiveEditorEl().querySelector(`#${anchorId}`);
            if (span) {
                const rect = span.getBoundingClientRect();
                this.state.commentModalTop = rect.bottom + 8;
                this.state.commentModalLeft = rect.left;
                this.state.activeCommentAnchorId = anchorId;
                this.state.commentContent = "";
                this.state.isCommentModalOpen = true;
                this.onInput();
            }
        }
    }

    translateSelectedText() {
        const selection = window.getSelection();
        if (selection && selection.toString().trim()) {
            const text = encodeURIComponent(selection.toString().trim());
            window.open(`https://translate.google.com/?sl=auto&tl=en&text=${text}&op=translate`, '_blank');
        } else {
            if (this.notification) {
                this.notification.add("Please select text to translate", { type: "warning" });
            }
        }
    }

    openMoreMenu(ev) {
        const selection = window.getSelection();
        if (selection.rangeCount > 0) {
            this.state.savedRange = selection.getRangeAt(0).cloneRange();
        }
        
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.slashMenuTop = rect.bottom + 8;
        this.state.slashMenuLeft = rect.left - 100;
        this.state.isSlashMenuOpen = true;
        this.state.slashMenuSelectedIndex = 0;
    }

    executeSlashCommand(item) {
        this.state.isSlashMenuOpen = false;
        
        const selection = window.getSelection();
        let range;
        
        if (this.state.savedRange) {
            selection.removeAllRanges();
            selection.addRange(this.state.savedRange);
            range = this.state.savedRange;
            this.state.savedRange = null;
        } else if (selection.rangeCount > 0) {
            range = selection.getRangeAt(0);
        }

        if (range) {
            // Remove the '/' character and any query text typed after it
            if (range.startContainer.nodeType === Node.TEXT_NODE) {
                const text = range.startContainer.textContent;
                const pos = range.startOffset;
                // Since lastIndexOf searches backwards from 'pos', it will find the slash if they typed '/' or '/query'
                const lastSlashIndex = text.lastIndexOf('/', pos);
                
                if (lastSlashIndex !== -1) {
                    range.startContainer.textContent = text.substring(0, lastSlashIndex) + text.substring(pos);
                    // Reposition cursor where the slash was
                    const newRange = document.createRange();
                    newRange.setStart(range.startContainer, lastSlashIndex);
                    newRange.collapse(true);
                    selection.removeAllRanges();
                    selection.addRange(newRange);
                }
            }
        }

        if (item.command) {
            this.execFormat(item.command, item.value);
        } else if (item.action && this[item.action]) {
            this[item.action]();
        }
    }

    async saveIcon(iconChar) {
        if (!this.props.activeArticleId) return;
        this.state.article.icon = iconChar;
        this.state.isEmojiPickerOpen = false;
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                icon: iconChar
            });
        } catch (error) {
            console.error("Failed to save article icon", error);
        }
    }

    triggerCoverUpload() {
        this.openCoverModal();
    }

    async openCoverModal() {
        this.state.isCoverModalOpen = true;
        this.state.isMoreMenuOpen = false;
        if (!this.unsplashKey) {
            try {
                const keys = await this.orm.call("knowledge.management.article", "get_unsplash_keys", []);
                this.unsplashKey = keys.access_key;
                this.unsplashAppId = keys.app_id;
            } catch (e) {
                console.error("Failed to get unsplash keys", e);
            }
        }
    }

    closeCoverModal() {
        this.state.isCoverModalOpen = false;
    }

    setCoverTab(tab) {
        this.state.coverModalTab = tab;
    }

    async searchUnsplash() {
        if (!this.state.unsplashQuery) return;
        if (!this.unsplashKey) {
            this.notification.add("Unsplash Access Key not configured in Settings.", { type: "danger" });
            return;
        }
        this.state.isUnsplashLoading = true;
        try {
            const response = await fetch(`https://api.unsplash.com/search/photos?query=${encodeURIComponent(this.state.unsplashQuery)}&per_page=21`, {
                headers: {
                    'Authorization': `Client-ID ${this.unsplashKey}`
                }
            });
            const data = await response.json();
            this.state.unsplashImages = data.results || [];
        } catch (e) {
            console.error("Unsplash search error", e);
            this.notification.add("Failed to search Unsplash", { type: "danger" });
        } finally {
            this.state.isUnsplashLoading = false;
        }
    }

    async applyUrlCover(url) {
        if (!url || !this.props.activeArticleId) return;
        this.state.isCoverDownloading = true;
        try {
            const success = await this.orm.call("knowledge.management.article", "action_download_cover", [this.props.activeArticleId, url]);
            if (success) {
                const result = await this.orm.read("knowledge.management.article", [this.props.activeArticleId], ["cover_image", "cover_position"]);
                if (result.length > 0) {
                    this.state.article.cover_image = result[0].cover_image;
                    this.state.article.cover_position = result[0].cover_position;
                }
                this.closeCoverModal();
            } else {
                this.notification.add("Failed to download image from URL.", { type: "danger" });
            }
        } catch (e) {
            console.error(e);
            this.notification.add("Error downloading cover", { type: "danger" });
        } finally {
            this.state.isCoverDownloading = false;
        }
    }

    onUploadBtnClick() {
        if (this.fileInputRef && this.fileInputRef.el) {
            this.fileInputRef.el.click();
        }
    }

    onCoverFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64Data = e.target.result.split(',')[1];
            this.state.article.cover_image = base64Data;
            this.state.article.cover_position = 50.0; // Reset position on new upload
            if (!this.props.activeArticleId) return;
            try {
                await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                    cover_image: base64Data,
                    cover_position: 50.0
                });
                this.closeCoverModal();
            } catch (error) {
                console.error("Failed to save cover image", error);
            }
        };
        reader.readAsDataURL(file);
    }

    async removeCover() {
        this.state.article.cover_image = false;
        if (!this.props.activeArticleId) return;
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                cover_image: false
            });
        } catch (error) {
            console.error("Failed to remove cover image", error);
        }
    }

    startRepositionMode(ev) {
        this.state.isRepositioning = true;
    }

    startDrag(ev) {
        if (!this.state.isRepositioning) return;
        this.state.isDraggingCover = true;
        this.state.coverStartY = ev.clientY;
        this.state.initialCoverPosition = this.state.article.cover_position || 50;
    }

    onCoverDrag(ev) {
        if (!this.state.isRepositioning || !this.state.isDraggingCover) return;
        if (ev.buttons !== 1) { // Mouse button released
            this.stopDrag();
            return;
        }
        const deltaY = ev.clientY - this.state.coverStartY;
        // Adjust the multiplier to change drag speed
        let newPos = this.state.initialCoverPosition - (deltaY * 0.15);
        if (newPos < 0) newPos = 0;
        if (newPos > 100) newPos = 100;
        this.state.article.cover_position = newPos;
    }

    stopDrag() {
        this.state.isDraggingCover = false;
    }

    async saveReposition() {
        this.state.isRepositioning = false;
        this.state.isDraggingCover = false;
        if (!this.props.activeArticleId) return;
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                cover_position: this.state.article.cover_position
            });
        } catch (error) {
            console.error("Failed to save cover position", error);
        }
    }

    async toggleLock() {
        if (!this.props.activeArticleId || !this.state.article) return;
        this.state.isMoreMenuOpen = false;
        
        if (this.props.toggleLock) {
            await this.props.toggleLock();
        }
        
        try {
            const result = await this.orm.read("knowledge.management.article", [this.props.activeArticleId], ["is_locked"]);
            if (result.length > 0) {
                this.state.article.is_locked = result[0].is_locked;
                if (this.contentRef && this.getActiveEditorEl()) {
                    this.getActiveEditorEl().setAttribute("contenteditable", !result[0].is_locked);
                }
            }
        } catch (error) {
            console.error("Failed to sync lock state", error);
        }
    }

    toggleEmojiPicker() {
        if (this.state.article && !this.state.article.is_locked) {
            this.state.isEmojiPickerOpen = !this.state.isEmojiPickerOpen;
        }
    }

    async openHistoryModal() {
        if (!this.props.activeArticleId) return;
        this.state.historyVersions = [];
        this.state.selectedHistoryVersion = null;
        this.state.compareVersion = null;
        this.state.showHistoryComparison = false;
        this.state.isHistoryModalOpen = true;
        this.state.isMoreMenuOpen = false;
        
        try {
            const versions = await this.orm.searchRead(
                "knowledge.management.version",
                [["article_id", "=", this.props.activeArticleId]],
                ["id", "version_number", "user_id", "date", "content_snapshot", "title_snapshot", "change_summary", "change_type"],
                { order: "version_number desc" }
            );
            this.state.historyVersions = versions;
            if (versions.length > 0) {
                this.state.selectedHistoryVersion = versions[0];
                this.state.compareVersion = versions.length > 1 ? versions[1] : null;
            }
        } catch (error) {
            console.error("Failed to load versions", error);
        }
    }

    closeHistoryModal() {
        this.state.isHistoryModalOpen = false;
        this.state.historyVersions = [];
        this.state.selectedHistoryVersion = null;
        this.state.compareVersion = null;
        this.state.showHistoryComparison = false;
    }

    selectHistoryVersion(version) {
        this.state.selectedHistoryVersion = version;
    }
    
    compareWithPrevious() {
        if (!this.state.selectedHistoryVersion || this.state.historyVersions.length < 2) return;
        const currentIndex = this.state.historyVersions.findIndex(v => v.id === this.state.selectedHistoryVersion.id);
        if (currentIndex !== -1 && currentIndex + 1 < this.state.historyVersions.length) {
            this.state.compareVersion = this.state.historyVersions[currentIndex + 1];
            this.state.showHistoryComparison = true;
        }
    }

    async restoreHistory() {
        if (!this.state.selectedHistoryVersion || !this.props.activeArticleId) return;
        
        if (!confirm(`Restore Version ${this.state.selectedHistoryVersion.version_number}?\n\nThe current article will be replaced with the content from this version.\n\nA new version will be created after restoration.`)) {
            return;
        }

        try {
            await this.orm.call(
                "knowledge.management.article",
                "restore_version",
                [[this.props.activeArticleId], this.state.selectedHistoryVersion.id]
            );
            this.closeHistoryModal();
            this.loadArticle(this.props.activeArticleId);
        } catch (error) {
            console.error("Failed to restore history", error);
        }
    }

    downloadPdf() {
        // The standard browser print dialog handles "Save as PDF" cleanly 
        // when CSS media queries (@media print) are properly configured.
        window.print();
    }

    async addToTemplates() {
        if (!this.state.article) return;
        try {
            const createVals = {
                name: this.state.article.name,
                content: this.state.article.content,
                category_id: this.state.article.category_id ? this.state.article.category_id[0] : false,
            };
            if (this.state.article.icon) createVals.icon = this.state.article.icon;
            if (this.state.article.cover_image) {
                createVals.cover_image = this.state.article.cover_image;
                createVals.cover_position = this.state.article.cover_position || 50.0;
            }
            await this.orm.create("knowledge.management.template", [createVals]);
            
            this.notification.add("Article added to the list of Templates", {
                type: "success",
            });
            this.state.isMoreMenuOpen = false;
        } catch (error) {
            console.error("Failed to add to templates", error);
            this.notification.add("Failed to add template", { type: "danger" });
        }
    }

    formatHistoryDate(dateStr) {
        if (!dateStr) return "";
        // dateStr is typical Odoo UTC string like "2026-08-06 09:38:32"
        try {
            // Very naive formatter to match the design "Aug 6 at 9:38 am"
            const d = new Date(dateStr + "Z");
            const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            const m = months[d.getMonth()];
            const day = d.getDate();
            let hours = d.getHours();
            const ampm = hours >= 12 ? 'pm' : 'am';
            hours = hours % 12;
            hours = hours ? hours : 12;
            const minutes = d.getMinutes().toString().padStart(2, '0');
            return `${m} ${day} at ${hours}:${minutes} ${ampm}`;
        } catch (e) {
            return dateStr;
        }
    }

    formatHistoryDateFull(dateStr) {
        if (!dateStr) return "";
        try {
            const d = new Date(dateStr + "Z");
            const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            const m = months[d.getMonth()];
            const day = d.getDate();
            const year = d.getFullYear();
            let hours = d.getHours();
            const ampm = hours >= 12 ? 'pm' : 'am';
            hours = hours % 12;
            hours = hours ? hours : 12;
            const minutes = d.getMinutes().toString().padStart(2, '0');
            const seconds = d.getSeconds().toString().padStart(2, '0');
            return `${m} ${day}, ${year} at ${hours}:${minutes}:${seconds} ${ampm}`;
        } catch (e) {
            return dateStr;
        }
    }



    onInput() {
        setTimeout(() => this.checkLineEmpty(), 10);
        if (!this.contentRef.el) return;
        const content = this.contentRef.el.innerHTML;

        // Update local state so empty checks work immediately
        this.state.article.content = content;

        this.debouncedSave();
    }

    focusEditor() {
        if (this.contentRef && this.getActiveEditorEl()) {
            const sel = window.getSelection();
            let currentRange = null;
            if (sel.rangeCount > 0) {
                const r = sel.getRangeAt(0);
                if (this.getActiveEditorEl().contains(r.commonAncestorContainer)) {
                    currentRange = r.cloneRange();
                }
            }

            this.getActiveEditorEl().focus();
            if (this.state.savedRange) {
                sel.removeAllRanges();
                sel.addRange(this.state.savedRange);
            } else if (this.state.toolbarRange) {
                sel.removeAllRanges();
                sel.addRange(this.state.toolbarRange);
            } else if (currentRange) {
                sel.removeAllRanges();
                sel.addRange(currentRange);
            } else if (this.getActiveEditorEl().childNodes.length === 0) {
                const range = document.createRange();
                range.selectNodeContents(this.getActiveEditorEl());
                range.collapse(true);
                sel.removeAllRanges();
                sel.addRange(range);
            }
        }
    }

    execFormat(command, value = null) {
        this.focusEditor();
        
        const isCustomDisplay = value === 'H1_DISPLAY_1';
        let tagValue = isCustomDisplay ? 'H1' : value;
        const validTags = ['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'P', 'DIV', 'BLOCKQUOTE', 'PRE'];
        
        if (command === 'formatBlock' && (isCustomDisplay || validTags.includes(tagValue?.toUpperCase()))) {
            tagValue = tagValue.toUpperCase();
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                
                const blocksToReplace = [];
                const walker = document.createTreeWalker(this.getActiveEditorEl(), NodeFilter.SHOW_ELEMENT, {
                    acceptNode: (node) => validTags.includes(node.tagName.toUpperCase()) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
                });
                
                let node = walker.nextNode();
                while (node) {
                    if (range.intersectsNode(node)) {
                        if (!blocksToReplace.some(b => b.contains(node))) {
                            blocksToReplace.push(node);
                        }
                    }
                    node = walker.nextNode();
                }

                if (blocksToReplace.length === 0) {
                    let blockNode = range.startContainer;
                    if (blockNode.nodeType !== Node.ELEMENT_NODE) {
                        blockNode = blockNode.parentNode;
                    }
                    while (blockNode && blockNode !== this.getActiveEditorEl() && blockNode.tagName && !validTags.includes(blockNode.tagName.toUpperCase())) {
                        blockNode = blockNode.parentNode;
                    }
                    if (blockNode && blockNode.tagName && validTags.includes(blockNode.tagName.toUpperCase()) && blockNode !== this.getActiveEditorEl()) {
                        blocksToReplace.push(blockNode);
                    }
                }

                if (blocksToReplace.length > 0) {
                    const newBlocks = [];
                    for (const block of blocksToReplace) {
                        const newBlock = document.createElement(tagValue);
                        for (let i = 0; i < block.attributes.length; i++) {
                            const attrName = block.attributes[i].name;
                            let attrValue = block.attributes[i].value;
                            if (attrName === 'class') {
                                let classes = attrValue.split(' ').filter(c => c !== 'display-1' && c !== 'display-1-fs');
                                if (classes.length > 0) {
                                    newBlock.setAttribute('class', classes.join(' '));
                                }
                            } else {
                                newBlock.setAttribute(attrName, attrValue);
                            }
                        }
                        if (isCustomDisplay) {
                            newBlock.classList.add('display-1-fs');
                        }
                        while (block.firstChild) {
                            newBlock.appendChild(block.firstChild);
                        }
                        let hasContent = false;
                        for (let i = 0; i < newBlock.childNodes.length; i++) {
                            const child = newBlock.childNodes[i];
                            if (child.nodeType === Node.ELEMENT_NODE && child.tagName === 'BR') {
                                hasContent = true;
                                break;
                            }
                            if (child.nodeType === Node.TEXT_NODE && child.textContent.length > 0) {
                                hasContent = true;
                                break;
                            }
                        }
                        if (!hasContent) {
                            newBlock.innerHTML = '<br>';
                        }
                        block.parentNode.replaceChild(newBlock, block);
                        newBlocks.push(newBlock);
                    }
                    
                    const newRange = document.createRange();
                    if (newBlocks.length === 1) {
                        const block = newBlocks[0];
                        if (block.childNodes.length === 1 && block.firstChild.tagName === 'BR') {
                            newRange.setStartBefore(block.firstChild);
                            newRange.collapse(true);
                        } else {
                            newRange.selectNodeContents(block);
                            newRange.collapse(false);
                        }
                    } else {
                        newRange.setStartBefore(newBlocks[0]);
                        newRange.setEndAfter(newBlocks[newBlocks.length - 1]);
                    }
                    selection.removeAllRanges();
                    selection.addRange(newRange);
                    
                    this.onInput();
                    return;
                }
            }
        }
        
        if (command === 'fontSize') {
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0 && selection.isCollapsed) {
                let node = selection.anchorNode;
                const blockTags = ['P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'BLOCKQUOTE', 'PRE', 'TD', 'TH'];
                while (node && node !== this.getActiveEditorEl() && (!node.tagName || !blockTags.includes(node.tagName.toUpperCase()))) {
                    node = node.parentNode;
                }
                if (node && node !== this.getActiveEditorEl()) {
                    node.style.setProperty('font-size', value + 'px', 'important');
                } else {
                    document.execCommand('fontSize', false, '7');
                    const fonts = this.getActiveEditorEl().querySelectorAll('font[size="7"]');
                    fonts.forEach(font => {
                        font.removeAttribute('size');
                        font.style.setProperty('font-size', value + 'px', 'important');
                    });
                }
            } else {
                document.execCommand('fontSize', false, '7');
                const fonts = this.getActiveEditorEl().querySelectorAll('font[size="7"]');
                fonts.forEach(font => {
                    font.removeAttribute('size');
                    font.style.setProperty('font-size', value + 'px', 'important');
                    
                    const innerBlocks = font.querySelectorAll('h1, h2, h3, h4, h5, h6, p, div, li, blockquote');
                    innerBlocks.forEach(b => {
                        b.style.setProperty('font-size', value + 'px', 'important');
                    });
                });
            }
            this.onInput();
            return;
        }
        
        document.execCommand(command, false, value);
        
        // Post-process styling to enforce rules over strict CSS (like in headings)
        const formattingTags = {
            'bold': 'b, strong',
            'italic': 'i, em',
            'underline': 'u',
            'strikeThrough': 'strike, s, del',
            'foreColor': 'font[color]',
            'backColor': 'span[style*="background-color"], font[style*="background-color"]',
            'fontName': 'font[face]'
        };
        
        if (formattingTags[command]) {
            const elements = this.getActiveEditorEl().querySelectorAll(formattingTags[command]);
            elements.forEach(el => {
                if (command === 'bold') el.style.setProperty('font-weight', 'bold', 'important');
                if (command === 'italic') el.style.setProperty('font-style', 'italic', 'important');
                if (command === 'underline') el.style.setProperty('text-decoration', 'underline', 'important');
                if (command === 'strikeThrough') el.style.setProperty('text-decoration', 'line-through', 'important');
                if (command === 'foreColor' && el.hasAttribute('color')) {
                    el.style.setProperty('color', el.getAttribute('color'), 'important');
                }
                if (command === 'backColor' && el.style.backgroundColor) {
                    el.style.setProperty('background-color', el.style.backgroundColor, 'important');
                }
                if (command === 'fontName' && el.hasAttribute('face')) {
                    el.style.setProperty('font-family', el.getAttribute('face'), 'important');
                }
            });
        }

        if (['justifyLeft', 'justifyCenter', 'justifyRight', 'justifyFull'].includes(command)) {
            const blocks = this.getActiveEditorEl().querySelectorAll('p, div, h1, h2, h3, h4, h5, h6, li, blockquote');
            blocks.forEach(b => {
                if (b.style.textAlign && b.style.getPropertyPriority('text-align') !== 'important') {
                    b.style.setProperty('text-align', b.style.textAlign, 'important');
                }
                if (b.hasAttribute('align')) {
                    b.style.setProperty('text-align', b.getAttribute('align'), 'important');
                }
            });
        }

        this.onInput();
    }

    insertCheckbox() {
        const id = Math.random().toString(36).substr(2, 9);
        const checkboxHtml = `<div class="km_pro_checkbox_block" style="display: flex; align-items: flex-start; margin-bottom: 4px;"><input type="checkbox" id="chk_${id}" style="margin-top: 6px; margin-right: 8px; cursor: pointer;" contenteditable="false" onchange="if(this.hasAttribute('checked')) { this.removeAttribute('checked'); } else { this.setAttribute('checked', 'checked'); } this.dispatchEvent(new Event('input', {bubbles:true}));" /> <label contenteditable="true" class="km_pro_checkbox_label" placeholder="To-do..." style="flex: 1; outline: none; margin: 0; min-width: 50px;"><br/></label></div><br/>`;
        this.focusEditor();
        document.execCommand("insertHTML", false, checkboxHtml);
        this.onInput();
    }

    insertTable() {
        const tableHtml = `
            <table class="km_pro_table" style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid var(--km-border-color, #dee2e6); padding: 8px; min-width: 60px;"><br/></td>
                        <td style="border: 1px solid var(--km-border-color, #dee2e6); padding: 8px; min-width: 60px;"><br/></td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid var(--km-border-color, #dee2e6); padding: 8px; min-width: 60px;"><br/></td>
                        <td style="border: 1px solid var(--km-border-color, #dee2e6); padding: 8px; min-width: 60px;"><br/></td>
                    </tr>
                </tbody>
            </table><br/>
        `;
        this.focusEditor();
        document.execCommand("insertHTML", false, tableHtml);
        this.onInput();
    }

    insertColumns() {
        const columnsHtml = `
            <div class="km_pro_columns" style="display: flex; gap: 16px; margin-bottom: 16px;">
                <div style="flex: 1; padding: 8px; border: 1px dashed var(--km-border-light, #e0e0e0); border-radius: 4px; min-height: 28px;" placeholder="Column 1..."><br/></div>
                <div style="flex: 1; padding: 8px; border: 1px dashed var(--km-border-light, #e0e0e0); border-radius: 4px; min-height: 28px;" placeholder="Column 2..."><br/></div>
            </div><br/>
        `;
        this.focusEditor();
        document.execCommand("insertHTML", false, columnsHtml);
        this.onInput();
    }

    triggerImageUpload() {
        if (this.imageInputRef && this.imageInputRef.el) {
            this.imageInputRef.el.click();
        }
    }

    onImageFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64Data = e.target.result.split(',')[1];
            try {
                const attachmentIds = await this.orm.create("ir.attachment", [{
                    name: file.name,
                    datas: base64Data,
                    res_model: 'knowledge.management.article',
                    res_id: this.props.activeArticleId || 0,
                    public: true
                }]);
                if (attachmentIds && attachmentIds.length > 0) {
                    const imgUrl = `/web/content/${attachmentIds[0]}?download=false`;
                    this.focusEditor();
                    document.execCommand("insertHTML", false, `<img src="${imgUrl}" style="max-width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; transition: all 0.2s ease; outline: 2px solid transparent;" alt="${file.name}" />`);
                    this.onInput();
                }
            } catch (err) {
                console.error("Image upload failed", err);
            }
        };
        reader.readAsDataURL(file);
        ev.target.value = ""; // Reset
    }

    triggerDocumentUpload() {
        if (this.documentInputRef && this.documentInputRef.el) {
            this.documentInputRef.el.click();
        }
    }

    onDocumentFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64Data = e.target.result.split(',')[1];
            try {
                const attachmentIds = await this.orm.create("ir.attachment", [{
                    name: file.name,
                    datas: base64Data,
                    res_model: 'knowledge.management.article',
                    res_id: this.props.activeArticleId || 0,
                    public: true
                }]);
                if (attachmentIds && attachmentIds.length > 0) {
                    const docUrl = `/web/content/${attachmentIds[0]}?download=true`;
                    this.focusEditor();
                    document.execCommand("insertHTML", false, `<a href="${docUrl}" class="btn btn-secondary km_pro_document_link" style="display: inline-block; padding: 6px 12px; margin: 8px 0; background: #36363a; color: #fff; text-decoration: none; border-radius: 4px; font-weight: 500;" target="_blank"><i class="fa fa-file-text-o" style="margin-right: 8px;"></i>${file.name}</a>&nbsp;`);
                    this.onInput();
                }
            } catch (err) {
                console.error("Document upload failed", err);
            }
        };
        reader.readAsDataURL(file);
        ev.target.value = ""; // Reset
    }

    insertLink() {
        const text = window.prompt("Button Text:");
        if (!text) return;
        const url = window.prompt("Button URL:");
        if (!url) return;
        const buttonHtml = `<a href="${url}" class="btn btn-primary km_pro_button_link" style="display: inline-block; padding: 8px 16px; margin: 8px 0; background: #2563eb; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600;" target="_blank">${text}</a>&nbsp;`;
        this.focusEditor();
        document.execCommand("insertHTML", false, buttonHtml);
        this.onInput();
    }

    insertVideo() {
        const url = window.prompt("Enter Video URL (YouTube, Vimeo, or MP4):");
        if (!url) return;
        
        let embedHtml = '';
        if (url.includes("youtube.com") || url.includes("youtu.be")) {
            const videoId = url.includes("youtu.be") ? url.split("/").pop() : new URL(url).searchParams.get("v");
            if (videoId) {
                embedHtml = `<iframe width="100%" height="315" src="https://www.youtube.com/embed/${videoId}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen contenteditable="false" style="border-radius: 6px; margin: 16px 0;"></iframe><br/>`;
            }
        } else if (url.includes("vimeo.com")) {
            const videoId = url.split("/").pop();
            if (videoId) {
                embedHtml = `<iframe src="https://player.vimeo.com/video/${videoId}" width="100%" height="315" frameborder="0" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen contenteditable="false" style="border-radius: 6px; margin: 16px 0;"></iframe><br/>`;
            }
        } else if (url.endsWith(".mp4")) {
            embedHtml = `<video width="100%" height="auto" controls contenteditable="false" style="border-radius: 6px; margin: 16px 0;"><source src="${url}" type="video/mp4"></video><br/>`;
        } else {
            embedHtml = `<iframe width="100%" height="315" src="${url}" frameborder="0" allowfullscreen contenteditable="false" style="border-radius: 6px; margin: 16px 0;"></iframe><br/>`;
        }
        
        if (embedHtml) {
            this.focusEditor();
            document.execCommand("insertHTML", false, embedHtml);
            this.onInput();
        }
    }

    insertTextLink() {
        if (this.state.selectedImage) {
            const currentA = this.state.selectedImage.closest('a');
            const url = window.prompt("Enter Link URL:", currentA ? currentA.href : '');
            if (url === null) return;
            if (url === '') {
                if (currentA) {
                    currentA.parentNode.insertBefore(this.state.selectedImage, currentA);
                    currentA.remove();
                }
            } else {
                if (currentA) {
                    currentA.href = url;
                } else {
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    this.state.selectedImage.parentNode.insertBefore(a, this.state.selectedImage);
                    a.appendChild(this.state.selectedImage);
                }
            }
            this.onInput();
        } else {
            const url = window.prompt("Enter Link URL:");
            if (!url) return;
            document.execCommand("createLink", false, url);
            this.onInput();
        }
    }
    
    onEditorClick(ev) {
        setTimeout(() => this.checkLineEmpty(), 10);
        if (ev.target.tagName === 'IMG') {
            this.state.isLineEmptyVisible = false;
            if (this.state.selectedImage) {
                this.state.selectedImage.style.outline = '2px solid transparent';
            }
            this.state.selectedImage = ev.target;
            this.state.selectedImage.style.outline = '2px solid #2563eb';
            
            const width = this.state.selectedImage.style.width || '100%';
            this.state.imageSizeLabel = width;
            
            const rect = ev.target.getBoundingClientRect();
            this.state.imageToolbarTop = rect.top - 50;
            this.state.imageToolbarLeft = rect.left + rect.width / 2;
        } else if (this.state.selectedImage && !ev.target.closest('.km_pro_image_toolbar')) {
            this.state.selectedImage.style.outline = '2px solid transparent';
            this.state.selectedImage = null;
        }

        const tableNode = ev.target.closest('table.km_pro_table');
        if (tableNode) {
            if (this.state.selectedTable) {
                this.state.selectedTable.style.outline = 'none';
            }
            this.state.selectedTable = tableNode;
            this.state.selectedTable.style.outline = '2px solid #2563eb';
            const rect = tableNode.getBoundingClientRect();
            this.state.tableToolbarTop = rect.top - 50;
            this.state.tableToolbarLeft = rect.left + rect.width / 2;
        } else if (this.state.selectedTable && !ev.target.closest('.km_pro_table_toolbar')) {
            this.state.selectedTable.style.outline = 'none';
            this.state.selectedTable = null;
        }
    }

    addTableRow() {
        if (this.state.selectedTable) {
            const tbody = this.state.selectedTable.querySelector('tbody');
            if (tbody) {
                const rowCount = tbody.rows.length;
                const colCount = rowCount > 0 ? tbody.rows[0].cells.length : 2;
                const tr = document.createElement('tr');
                for (let i = 0; i < colCount; i++) {
                    const td = document.createElement('td');
                    td.style.border = '1px solid #36363a';
                    td.style.padding = '8px';
                    td.style.minWidth = '50px';
                    td.innerText = 'Cell';
                    tr.appendChild(td);
                }
                tbody.appendChild(tr);
                this.onInput();
            }
        }
    }

    deleteTableRow() {
        if (this.state.selectedTable) {
            const tbody = this.state.selectedTable.querySelector('tbody');
            if (tbody && tbody.rows.length > 1) {
                const sel = window.getSelection();
                if (sel.rangeCount > 0) {
                    let node = sel.getRangeAt(0).startContainer;
                    let tr = null;
                    while (node && node !== this.state.selectedTable) {
                        if (node.tagName === 'TR') { tr = node; break; }
                        node = node.parentNode;
                    }
                    if (tr) {
                        tbody.removeChild(tr);
                    } else {
                        tbody.removeChild(tbody.rows[tbody.rows.length - 1]);
                    }
                } else {
                    tbody.removeChild(tbody.rows[tbody.rows.length - 1]);
                }
                this.onInput();
            }
        }
    }

    addTableColumn() {
        if (this.state.selectedTable) {
            const tbody = this.state.selectedTable.querySelector('tbody');
            if (tbody) {
                for (let i = 0; i < tbody.rows.length; i++) {
                    const td = document.createElement('td');
                    td.style.border = '1px solid #36363a';
                    td.style.padding = '8px';
                    td.style.minWidth = '50px';
                    td.innerText = 'Cell';
                    tbody.rows[i].appendChild(td);
                }
                this.onInput();
            }
        }
    }

    deleteTableColumn() {
        if (this.state.selectedTable) {
            const tbody = this.state.selectedTable.querySelector('tbody');
            if (tbody && tbody.rows.length > 0 && tbody.rows[0].cells.length > 1) {
                const sel = window.getSelection();
                let colIndex = -1;
                if (sel.rangeCount > 0) {
                    let node = sel.getRangeAt(0).startContainer;
                    let td = null;
                    while (node && node !== this.state.selectedTable) {
                        if (node.tagName === 'TD') { td = node; break; }
                        node = node.parentNode;
                    }
                    if (td && td.parentNode) {
                        colIndex = Array.prototype.indexOf.call(td.parentNode.children, td);
                    }
                }
                
                if (colIndex === -1) {
                    colIndex = tbody.rows[0].cells.length - 1;
                }

                for (let i = 0; i < tbody.rows.length; i++) {
                    tbody.rows[i].removeChild(tbody.rows[i].cells[colIndex]);
                }
                this.onInput();
            }
        }
    }

    deleteTable() {
        if (this.state.selectedTable) {
            this.state.selectedTable.remove();
            this.state.selectedTable = null;
            this.onInput();
        }
    }

    setImageFloat(direction) {
        if (this.state.selectedImage) {
            if (direction === 'left') {
                this.state.selectedImage.style.float = 'left';
                this.state.selectedImage.style.margin = '10px 20px 10px 0';
            } else if (direction === 'right') {
                this.state.selectedImage.style.float = 'right';
                this.state.selectedImage.style.margin = '10px 0 10px 20px';
            } else {
                this.state.selectedImage.style.float = 'none';
                this.state.selectedImage.style.margin = '10px 0';
            }
            this.onInput();
            setTimeout(() => {
                if (this.state.selectedImage) {
                    const rect = this.state.selectedImage.getBoundingClientRect();
                    this.state.imageToolbarTop = rect.top - 50;
                    this.state.imageToolbarLeft = rect.left + rect.width / 2;
                }
            }, 50);
        }
    }

    cycleImageSize() {
        if (this.state.selectedImage) {
            let nextSize = '100%';
            if (this.state.imageSizeLabel === '100%') {
                nextSize = '50%';
            } else if (this.state.imageSizeLabel === '50%') {
                nextSize = '25%';
            } else {
                nextSize = '100%';
            }
            this.state.selectedImage.style.width = nextSize;
            this.state.imageSizeLabel = nextSize;
            this.onInput();
            
            setTimeout(() => {
                if (this.state.selectedImage) {
                    const rect = this.state.selectedImage.getBoundingClientRect();
                    this.state.imageToolbarTop = rect.top - 50;
                    this.state.imageToolbarLeft = rect.left + rect.width / 2;
                }
            }, 50);
        }
    }

    previewImage() {
        if (this.state.selectedImage && this.state.selectedImage.src) {
            window.open(this.state.selectedImage.src, '_blank');
        }
    }

    removeSelectedImage() {
        if (this.state.selectedImage) {
            this.state.selectedImage.remove();
            this.state.selectedImage = null;
            this.onInput();
        }
    }

    addCaption() {
        if (this.state.selectedImage) {
            const img = this.state.selectedImage;
            if (img.parentElement.tagName !== 'FIGURE') {
                const figure = document.createElement('figure');
                figure.style.margin = '16px 0';
                figure.style.textAlign = 'center';
                const figcaption = document.createElement('figcaption');
                figcaption.contentEditable = "true";
                figcaption.innerText = "Type caption here...";
                figcaption.style.color = '#a0a0a0';
                figcaption.style.fontSize = '0.9rem';
                figcaption.style.marginTop = '8px';
                
                img.parentNode.insertBefore(figure, img);
                figure.appendChild(img);
                figure.appendChild(figcaption);
                this.onInput();
            }
        }
    }

    openCropModal() {
        if (this.state.selectedImage) {
            this.state.isCropModalOpen = true;
            this.state.cropAspectRatio = NaN;
            
            const waitForUIAndInit = () => {
                const img = document.getElementById('km_pro_cropper_image');
                if (img) {
                    this.initCropper();
                } else {
                    setTimeout(waitForUIAndInit, 10);
                }
            };
            
            if (typeof window.Cropper === 'undefined') {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = 'https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.13/cropper.min.css';
                document.head.appendChild(link);
                
                const script = document.createElement('script');
                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.13/cropper.min.js';
                script.onload = waitForUIAndInit;
                document.head.appendChild(script);
            } else {
                waitForUIAndInit();
            }
        }
    }

    initCropper() {
        const imageElement = document.getElementById('km_pro_cropper_image');
        if (imageElement && this.state.selectedImage) {
            const initialize = () => {
                if (this.cropperInstance) {
                    this.cropperInstance.destroy();
                }
                this.cropperInstance = new window.Cropper(imageElement, {
                    aspectRatio: this.state.cropAspectRatio,
                    viewMode: 1,
                });
            };
            
            if (imageElement.src === this.state.selectedImage.src && imageElement.complete) {
                initialize();
            } else {
                imageElement.onload = initialize;
                imageElement.src = this.state.selectedImage.src;
            }
        }
    }

    setCropAspectRatio(ratio) {
        this.state.cropAspectRatio = ratio;
        if (this.cropperInstance) {
            this.cropperInstance.setAspectRatio(ratio);
        }
    }

    cancelCrop() {
        if (this.cropperInstance) {
            this.cropperInstance.destroy();
            this.cropperInstance = null;
        }
        this.state.isCropModalOpen = false;
    }

    async applyCrop() {
        if (this.cropperInstance && this.state.selectedImage) {
            const canvas = this.cropperInstance.getCroppedCanvas();
            if (canvas) {
                const base64Data = canvas.toDataURL('image/jpeg').split(',')[1];
                try {
                    const attachmentIds = await this.orm.create("ir.attachment", [{
                        name: 'cropped_image.jpg',
                        datas: base64Data,
                        res_model: 'knowledge.management.article',
                        res_id: this.props.activeArticleId || 0,
                        public: true
                    }]);
                    if (attachmentIds && attachmentIds.length > 0) {
                        const imgUrl = `/web/content/${attachmentIds[0]}?download=false`;
                        this.state.selectedImage.src = imgUrl;
                        this.state.selectedImage.style.aspectRatio = 'auto';
                        this.state.selectedImage.style.objectFit = 'contain';
                        this.onInput();
                    }
                } catch (err) {
                    console.error("Cropped image upload failed", err);
                    if (this.notification) {
                        this.notification.add("Failed to upload cropped image", { type: "danger" });
                    }
                }
            }
        }
        this.cancelCrop();
    }
    
    get articleTitleValue() {
        if (!this.state.article) return "";
        const clean = this.stripHtml(this.state.article.name || "");
        return clean === "Untitled" ? "" : clean;
    }

    onTitleFocus(ev) {
        if (ev && ev.target && ev.target.value === 'Untitled') {
            ev.target.select();
        }
    }

    async renameArticle(ev) {
        if (!this.props.activeArticleId || !this.state.article) return;
        
        let newTitle = ev.target.value.trim();
        if (!newTitle) {
            newTitle = "Untitled";
        }
        if (newTitle === this.state.article.name) {
            return;
        }

        const oldTitle = this.state.article.name;
        
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                name: newTitle
            });
            this.state.article.name = newTitle;
            if (this.props.onTitleChange) {
                this.props.onTitleChange(newTitle);
            }
        } catch (error) {
            console.error("Failed to rename article", error);
            ev.target.value = oldTitle === "Untitled" ? "" : oldTitle;
            if (this.notification) {
                this.notification.add("Failed to rename article. The name must be unique.", { type: "danger" });
            }
        }
    }

    async toggleTagMenu() {
        this.state.isTagMenuOpen = !this.state.isTagMenuOpen;
        if (this.state.isTagMenuOpen) {
            this.state.tagSearchQuery = "";
            await this.loadAllTags();
        }
    }

    async loadAllTags() {
        try {
            this.state.allTags = await this.orm.searchRead("knowledge.management.tag", [], ["name", "color"]);
        } catch (error) {
            console.error("Failed to load tags", error);
        }
    }

    async addTag(tagId) {
        if (!this.props.activeArticleId || this.state.article.is_locked) return;
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                tag_ids: [[4, tagId]]
            });
            await this.loadArticle(this.props.activeArticleId);
            this.state.isTagMenuOpen = false;
        } catch (error) {
            console.error("Failed to add tag", error);
        }
    }

    async removeTag(tagId) {
        if (!this.props.activeArticleId || this.state.article.is_locked) return;
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                tag_ids: [[3, tagId]]
            });
            await this.loadArticle(this.props.activeArticleId);
        } catch (error) {
            console.error("Failed to remove tag", error);
        }
    }

    async createNewTag() {
        if (!this.state.tagSearchQuery.trim() || this.state.article.is_locked) return;
        try {
            const newTagIds = await this.orm.create("knowledge.management.tag", [{
                name: this.state.tagSearchQuery.trim()
            }]);
            if (newTagIds.length > 0) {
                await this.addTag(newTagIds[0]);
            }
        } catch (error) {
            console.error("Failed to create tag", error);
        }
    }

    openKanbanCard(card, colId, triggerChangeCallback) {
        this.state.activeCard = card;
        this.state.isLineEmptyVisible = false;
        this.state.isSlashMenuOpen = false;
        this.state.isMoreFormatMenuOpen = false;
        
        setTimeout(() => {
            if (this.cardContentRef && this.cardContentRef.el) {
                const cardContainer = this.cardContentRef.el.closest('.km_pro_card_editor_light');
                if (cardContainer) cardContainer.addEventListener("scroll", this.handleScroll);
            }
        }, 50);
        this.state.activeCardColId = colId;
        this.activeCardTriggerChange = triggerChangeCallback;
    }

    closeKanbanCard() {
        if (this.state.activeCard && this.cardContentRef && this.cardContentRef.el) {
            const cardContainer = this.cardContentRef.el.closest('.km_pro_card_editor_light');
            if (cardContainer) cardContainer.removeEventListener("scroll", this.handleScroll);
        }
        this.state.activeCard = null;
        this.state.activeCardColId = null;
        this.activeCardTriggerChange = null;
        this.debouncedSave();
    }

    onCardTitleInput(ev) {
        if (this.state.activeCard) {
            const val = ev.target.value !== undefined ? ev.target.value : (ev.target.innerText || ev.target.textContent);
            this.state.activeCard.content = val ? val.trim() : 'Untitled';
            if (this.activeCardTriggerChange) {
                this.activeCardTriggerChange();
            }
            this.debouncedSave();
        }
    }

    onCardContentInput(ev) {
        if (this.state.activeCard) {
            this.state.activeCard.article_content = ev.target.innerHTML;
            if (this.activeCardTriggerChange) {
                this.activeCardTriggerChange();
            }
            this.debouncedSave();
        }
    }

    onCardContentKeydown(ev) {
        this.onEditorKeydown(ev);
    }

    onCardQuickActionTemplate() {
        if (this.props.openTemplatesModal) {
            this.props.openTemplatesModal();
        }
    }

    onCardQuickActionKanban() {
        this.onQuickActionKanban();
    }

    onCardQuickActionList() {
        this.onQuickActionList();
    }

    onCardQuickActionCalendar() {
        this.onQuickActionCalendar();
    }

    debouncedSave() {
        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }

        let contentHtml = "";
        let contentText = "";
        
        let editorHtml = this.getActiveEditorEl() ? this.getActiveEditorEl().innerHTML : "";
        let editorText = this.getActiveEditorEl() ? this.getActiveEditorEl().innerText.trim() : "";

        if (this.state.isKanbanMode) {
            contentHtml = `<div data-kanban="true" data-kanban-title="${this.state.kanbanTitle}" data-kanban-data='${this.state.kanbanData || ""}'></div>` + editorHtml;
            contentText = (this.state.kanbanTitle || 'Kanban') + " " + editorText;
        } else if (this.state.isListMode) {
            contentHtml = `<div data-list="true" data-list-title="${this.state.listTitle}" data-list-data='${this.state.listData || ""}'></div>` + editorHtml;
            contentText = (this.state.listTitle || 'List') + " " + editorText;
        } else if (this.state.isCalendarMode) {
            contentHtml = `<div data-calendar="true" data-calendar-title="${this.state.calendarTitle}" data-calendar-data='${this.state.calendarData || ""}'></div>` + editorHtml;
            contentText = (this.state.calendarTitle || 'Calendar') + " " + editorText;
        } else {
            contentHtml = editorHtml;
            contentText = editorText;
        }
        
        this.saveTimeout = setTimeout(async () => {
            if (!this.props.activeArticleId) return;
            try {
                await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                    content: contentHtml,
                    name: this.state.article.name
                });
            } catch (error) {
                console.error("Failed to save article", error);
            }
        }, 1000);
    }

    async openInviteModal() {
        this.state.isInviteModalOpen = true;
        this.state.inviteSearchQuery = "";
        this.state.selectedUsersToInvite = [];
        this.state.allUsers = [];
        this.state.currentShares = [];
        this.state.isShareMenuOpen = false;
        
        try {
            const partners = await this.orm.searchRead(
                "res.partner",
                [["active", "=", true]],
                ["id", "name", "email"]
            );
            this.state.allUsers = partners;
            
            if (this.props.activeArticleId) {
                const shares = await this.orm.searchRead(
                    "knowledge.management.share",
                    [["article_id", "=", this.props.activeArticleId]],
                    ["id", "partner_ids", "access_level"]
                );
                
                let currentShares = [];
                for (const share of shares) {
                    for (const partnerId of share.partner_ids) {
                        const partner = this.state.allUsers.find(u => u.id === partnerId);
                        if (partner) {
                            currentShares.push({
                                share_id: share.id,
                                user: partner,
                                access_level: share.access_level
                            });
                        }
                    }
                }
                this.state.currentShares = currentShares;
            }
        } catch (error) {
            console.error("Failed to load users or shares", error);
        }
    }

    get filteredUsersToInvite() {
        if (!this.state.inviteSearchQuery) return [];
        const q = this.state.inviteSearchQuery.toLowerCase();
        return this.state.allUsers.filter(u => 
            u.name.toLowerCase().includes(q) && 
            !this.state.selectedUsersToInvite.find(s => s.id === u.id) &&
            !this.state.currentShares.find(s => s.user.id === u.id)
        );
    }
    
    selectUserToInvite(user) {
        this.state.selectedUsersToInvite.push(user);
        this.state.inviteSearchQuery = "";
    }
    
    removeSelectedUser(user) {
        this.state.selectedUsersToInvite = this.state.selectedUsersToInvite.filter(u => u.id !== user.id);
    }
    
    async removeShare(share) {
        try {
            const shareRecord = await this.orm.read("knowledge.management.share", [share.share_id], ["partner_ids"]);
            if (shareRecord.length > 0) {
                const updatedPartnerIds = shareRecord[0].partner_ids.filter(id => id !== share.user.id);
                if (updatedPartnerIds.length === 0) {
                    await this.orm.unlink("knowledge.management.share", [share.share_id]);
                } else {
                    await this.orm.write("knowledge.management.share", [share.share_id], {
                        partner_ids: [[6, 0, updatedPartnerIds]]
                    });
                }
            }
            this.state.currentShares = this.state.currentShares.filter(s => s.user.id !== share.user.id);
        } catch (error) {
            console.error("Failed to remove share", error);
        }
    }

    async submitInvite() {
        if (!this.props.activeArticleId || this.state.selectedUsersToInvite.length === 0) return;
        
        const partnerIds = this.state.selectedUsersToInvite.map(u => u.id);
        const accessLevel = this.state.invitePermission === 'Edit' ? 'write' : (this.state.invitePermission === 'No access' ? 'none' : 'read');
        
        try {
            await this.orm.create("knowledge.management.share", [{
                article_id: this.props.activeArticleId,
                partner_ids: [[6, 0, partnerIds]],
                access_level: accessLevel
            }]);
            if (this.notification) {
                this.notification.add("Successfully invited users", { type: "success" });
            }
            this.state.isInviteModalOpen = false;
        } catch (error) {
            console.error("Failed to invite users", error);
            if (this.notification) {
                this.notification.add("Failed to invite users", { type: "danger" });
            }
        }
    }

    openKanbanDialog() { // 1s debounce
    }
    
    get kanbanDisplayTitle() {
        return this.state.kanbanTitle || (this.state.article ? this.state.article.name : '') || 'Items';
    }

    // Quick Action Handlers
    onQuickActionTemplate() {
        if (this.props.openTemplatesModal) {
            this.props.openTemplatesModal();
        }
    }

    onQuickActionKanban() {
        this.state.kanbanItemName = "";
        this.state.showKanbanDialog = true;
    }

    handleKanbanChange(jsonData) {
        this.state.kanbanData = jsonData;
        this.debouncedSave();
    }

    handleListChange(jsonData) {
        this.state.listData = jsonData;
        this.debouncedSave();
    }

    /**
     * Called when "New" is clicked in the List View, or when an existing list item is clicked.
     * If articleId is provided, navigate to that article.
     * Otherwise, create a new child article under the current article and navigate to it.
     */
    async onListNewItem(articleId = null) {
        if (articleId && typeof articleId === 'number') {
            // Navigate to existing article using setActiveArticle
            if (this.props.setActiveArticle) {
                this.props.setActiveArticle(articleId);
            }
        } else {
            // Create brand new child article under current article
            if (this.props.createNewArticle) {
                await this.props.createNewArticle(
                    this.state.article ? this.state.article.id : false
                );
            }
        }
    }



    onKanbanBelowInput(ev) {
        const el = ev.target;
        this.state.kanbanBelowHasContent = !!(el && el.textContent && el.textContent.trim());
        this.debouncedSave();
    }

    onKanbanBelowKeydown(ev) {
        // Allow normal typing. Enter creates new paragraph naturally.
        // Could add slash command support here in future.
    }

    handleCalendarChange(jsonData) {
        this.state.calendarData = jsonData;
        this.debouncedSave();
    }

    insertKanban() {
        const rawName = this.state.kanbanItemName && this.state.kanbanItemName.trim();
        const itemName = rawName || (this.state.article ? this.state.article.name : '') || 'Items';
        this.state.kanbanTitle = itemName;
        const initialColumns = [
            { id: Math.random().toString(36).substring(2, 9), title: 'New', cards: [], isCollapsed: false },
            { id: Math.random().toString(36).substring(2, 9), title: 'Ongoing', cards: [], isCollapsed: false },
            { id: Math.random().toString(36).substring(2, 9), title: 'Done', cards: [], isCollapsed: true }
        ];
        this.state.kanbanData = JSON.stringify({ columns: initialColumns });
        this.state.isKanbanMode = true;
        this.state.showKanbanDialog = false;
        this.debouncedSave();
    }

    formatTimeAgo(dateStr) {
        if (!dateStr) return "Just now";
        try {
            if (typeof luxon !== 'undefined') {
                return luxon.DateTime.fromSQL(dateStr).toRelative() || "Recently";
            } else if (window.luxon) {
                return window.luxon.DateTime.fromSQL(dateStr).toRelative() || "Recently";
            }
        } catch (e) {
            console.warn("Time formatting error:", e);
        }
        return dateStr.split(" ")[0] || "Recently";
    }

    placeholderAction(actionName) {
        window.alert(`The "${actionName}" action is not fully implemented in the backend yet.`);
        this.state.isMoreMenuOpen = false;
    }

    async toggleFullWidth() {
        this.state.isFullWidth = !this.state.isFullWidth;
        if (this.props.activeArticleId) {
            try {
                await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                    is_full_width: this.state.isFullWidth
                });
            } catch (err) {
                console.error("Failed to save full width setting", err);
            }
        }
    }

    onQuickActionList() {
        this.state.listItemName = "";
        this.state.showListDialog = true;
    }

    insertList() {
        const itemName = this.state.listItemName || 'Items';
        this.state.listTitle = itemName;
        this.state.isListMode = true;
        this.state.showListDialog = false;
        
        // Also save this state so it persists
        if (this.getActiveEditorEl()) {
            this.getActiveEditorEl().innerHTML = `<div data-list="true" data-list-title="${itemName}"></div>`;
            this.onInput();
        }
    }

    onQuickActionCalendar() {
        this.state.calendarItemName = "";
        this.state.showCalendarDialog = true;
    }

    insertCalendar() {
        const itemName = this.state.calendarItemName || 'Items';
        this.state.calendarTitle = itemName;
        this.state.calendarData = null;
        this.state.isCalendarMode = true;
        this.state.showCalendarDialog = false;
        
        // Also save this state so it persists
        if (this.getActiveEditorEl()) {
            this.getActiveEditorEl().innerHTML = `<div data-calendar="true" data-calendar-title="${itemName}"></div>`;
            this.onInput();
        }
    }

    onQuickActionAI() {
        console.log("Generate with AI clicked");
        // Show AI config dialog or flow
        alert("AI Provider not configured. Please configure your AI settings first.");
    }
}

KnowledgeManagementEditor.template = xml`
    <div class="km_pro_editor_area" style="position: relative;">
        <t t-if="!props.activeArticleId">
            <div class="km_pro_no_article_selected">
                <h2>Select an article or create a new one to start writing.</h2>
            </div>
        </t>
        <t t-else="">
            <div class="km_pro_editor_toolbar">
                <div class="km_pro_editor_breadcrumb">
                    <div class="km_pro_breadcrumb">
                        <span class="breadcrumb-item active">
                            <t t-if="state.article and state.article.icon" t-esc="state.article.icon + ' '"/>
                            <input type="text" 
                                   class="km_pro_title_input" 
                                   placeholder="Untitled"
                                   t-att-value="this.articleTitleValue" 
                                   t-on-change="(ev) => this.renameArticle(ev)" 
                                   t-on-focus="onTitleFocus"
                                   t-on-keydown="(ev) => ev.key === 'Enter' and ev.target.blur()" 
                                   style="background: transparent; border: none; color: inherit; font-family: inherit; font-size: inherit; font-weight: inherit; outline: none; min-width: 80px; max-width: 400px; text-overflow: ellipsis; padding: 0;"/>
                            <i t-if="state.article and state.article.is_locked" class="fa fa-lock" style="margin-left: 8px; color: #a0a0a0;"></i>
                        </span>
                    </div><i class="fa fa-cloud" style="color: #a0a0a0; margin-left: 8px;"></i>
                    
                    <div class="km_pro_article_tags" style="display: flex; gap: 8px; flex-wrap: wrap; margin-left: 16px; margin-bottom: 0; align-items: center; position: relative;">
                        <t t-if="state.articleTags">
                            <t t-foreach="state.articleTags" t-as="tag" t-key="tag.id">
                                <span class="km_pro_tag" t-attf-style="background-color: {{ tag.color ? 'hsl(' + (tag.color * 30) + ', 70%, 25%)' : '#36363a' }}; color: #e0e0e0; padding: 2px 8px; border-radius: 12px; font-size: 0.85rem; display: flex; align-items: center; gap: 4px;">
                                    <t t-esc="tag.name" />
                                    <i class="fa fa-times" style="cursor: pointer; opacity: 0.7;" t-on-click="() => this.removeTag(tag.id)"></i>
                                </span>
                            </t>
                        </t>
                        <span class="km_pro_add_tag_btn" t-on-click="() => this.toggleTagMenu()" style="cursor: pointer; color: #a0a0a0; font-size: 0.85rem; padding: 2px 8px; border-radius: 12px; border: 1px dashed #555;">
                            <i class="fa fa-plus"></i> Add Tag
                        </span>
                        
                        <t t-if="state.isTagMenuOpen">
                            <div class="km_pro_tag_menu shadow" style="position: absolute; top: 100%; left: 0; z-index: 1050; background: var(--km-bg-dropdown); border: 1px solid var(--km-border-color); border-radius: 6px; box-shadow: var(--km-shadow-lg); width: 200px; padding: 8px; display: flex; flex-direction: column; gap: 8px;">
                                <input type="text" t-model="state.tagSearchQuery" placeholder="Search or create..." style="width: 100%; background: var(--km-bg-input); border: 1px solid var(--km-border-color); color: var(--km-text-title); padding: 4px 8px; border-radius: 4px; outline: none; font-size: 0.85rem;" />
                                <div style="max-height: 150px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px;">
                                    <t t-if="state.allTags">
                                        <t t-foreach="state.allTags.filter(t => !state.tagSearchQuery || t.name.toLowerCase().includes(state.tagSearchQuery.toLowerCase()))" t-as="tag" t-key="tag.id">
                                            <div t-on-click="() => this.addTag(tag.id)" style="padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 0.85rem; color: var(--km-text-main); display: flex; align-items: center; gap: 8px;" class="km_pro_tag_option">
                                                <div t-attf-style="width: 10px; height: 10px; border-radius: 50%; background-color: {{ tag.color ? 'hsl(' + (tag.color * 30) + ', 70%, 50%)' : '#888' }};"></div>
                                                <t t-esc="tag.name" />
                                            </div>
                                        </t>
                                    </t>
                                </div>
                                <t t-if="state.tagSearchQuery and !state.allTags.find(t => t.name.toLowerCase() === state.tagSearchQuery.toLowerCase())">
                                    <div t-on-click="() => this.createNewTag()" style="padding: 6px 8px; border-radius: 4px; cursor: pointer; font-size: 0.85rem; color: var(--km-primary); font-weight: 500; border-top: 1px solid var(--km-border-color); margin-top: 4px;">
                                        <i class="fa fa-plus"></i> Create "<t t-esc="state.tagSearchQuery" />"
                                    </div>
                                </t>
                            </div>
                        </t>
                    </div>
                </div>
                <div class="km_pro_editor_actions">
                    <div class="km_pro_share_menu_container" style="position: relative; display: flex; align-items: center; gap: 12px;">
                        <div class="km_pro_shared_avatars" t-if="state.article and state.article.shared_partner_ids and state.article.shared_partner_ids.length > 0" style="display: flex; flex-direction: row-reverse;">
                            <t t-foreach="state.article.shared_partner_ids.slice(0, 5)" t-as="partnerId" t-key="partnerId">
                                <img t-attf-src="/web/image?model=res.partner&amp;field=avatar_128&amp;id={{partnerId}}" 
                                     style="width: 32px; height: 32px; border-radius: 50%; border: 2px solid #1a1a1c; margin-left: -8px; object-fit: cover;" 
                                     title="Shared Contact" />
                            </t>
                            <div t-if="state.article.shared_partner_ids.length > 5" 
                                 style="width: 32px; height: 32px; border-radius: 50%; border: 2px solid #1a1a1c; margin-left: -8px; background: #36363a; color: #a0a0a0; display: flex; align-items: center; justify-content: center; font-size: 0.8rem; z-index: 1;">
                                +<t t-esc="state.article.shared_partner_ids.length - 5"/>
                            </div>
                        </div>
                        <span t-attf-class="km_pro_share_btn {{ state.isShareMenuOpen ? 'active' : '' }}" t-on-click="(ev) => { ev.stopPropagation(); state.isShareMenuOpen = !state.isShareMenuOpen; state.isGeneralAccessDropdownOpen = false; }">Share</span>
                        
                        <!-- Share Dropdown -->
                        <t t-if="state.isShareMenuOpen">
                            <div class="km_pro_share_menu" t-on-click="(ev) => ev.stopPropagation()">
                                <div class="share-row share-header-row">
                                    <div class="row-left">
                                        <i class="fa fa-globe" style="font-size: 1.5rem; color: var(--km-primary); margin-right: 16px;"></i>
                                        <div class="row-text">
                                            <t t-if="state.shareToWeb">
                                                <strong>Article shared to web</strong>
                                                <small>This article and its sub-articles are public</small>
                                                <span class="copy-link-btn" t-on-click="() => this.copyLink()">Copy Link</span>
                                            </t>
                                            <t t-else="">
                                                <strong>Share to web</strong>
                                                <small>Publish this article and its sub-articles</small>
                                            </t>
                                        </div>
                                    </div>
                                    <div t-attf-class="km_pro_toggle_switch {{ state.shareToWeb ? 'active' : '' }}" t-on-click="() => state.shareToWeb = !state.shareToWeb">
                                        <div class="toggle-circle"></div>
                                    </div>
                                </div>
                                <div class="share-divider"></div>
                                
                                <div class="share-row">
                                    <div class="row-left">
                                        <i class="fa fa-building-o" style="font-size: 1.2rem; color: var(--km-text-muted); margin-right: 16px;"></i>
                                        <span>General Access</span>
                                    </div>
                                    <div class="general-access-trigger" style="position: relative; cursor: pointer; color: var(--km-text-title); font-size: 0.9rem;" t-on-click="() => state.isGeneralAccessDropdownOpen = !state.isGeneralAccessDropdownOpen">
                                        <t t-esc="state.generalAccess" />
                                        <t t-if="state.isGeneralAccessDropdownOpen">
                                            <div class="km_pro_nested_dropdown">
                                                <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.generalAccess = 'Members only'; state.isGeneralAccessDropdownOpen = false; }">
                                                    <i t-attf-class="fa fa-check {{ state.generalAccess === 'Members only' ? '' : 'invisible' }}"></i> Members only
                                                </div>
                                                <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.generalAccess = 'Can Read'; state.isGeneralAccessDropdownOpen = false; }">
                                                    <i t-attf-class="fa fa-check {{ state.generalAccess === 'Can Read' ? '' : 'invisible' }}"></i> Can Read
                                                </div>
                                                <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.generalAccess = 'Can Edit'; state.isGeneralAccessDropdownOpen = false; }">
                                                    <i t-attf-class="fa fa-check {{ state.generalAccess === 'Can Edit' ? '' : 'invisible' }}"></i> Can Edit
                                                </div>
                                            </div>
                                        </t>
                                    </div>
                                </div>
                                <div class="share-divider"></div>
                                
                                <div class="share-row share-header-row" style="margin-top: 16px;">
                                    <div class="row-left">
                                        <div class="row-text">
                                            <strong>Invite people</strong>
                                            <small>Grant specific access</small>
                                        </div>
                                    </div>
                                    <button class="share-invite-btn" t-on-click="() => this.openInviteModal()">Invite</button>
                                </div>
                                
                                <div class="share-row user-row" style="margin-top: 8px;">
                                    <div class="row-left">
                                        <div class="user-avatar" style="background-color: #d8576b; color: white;">D</div>
                                        <div class="row-text">
                                            <strong>Hudson Softwares <span style="color:#a0a0a0; font-weight:normal;">(You)</span> <i class="fa fa-cog" style="color:#a0a0a0;"></i></strong>
                                            <small>hudsonsoftwareskply@gmail.com</small>
                                        </div>
                                    </div>
                                    <span style="color: #a0a0a0; font-size: 0.9rem;">Can Edit</span>
                                </div>
                            </div>
                        </t>
                    </div>
                    <div t-attf-class="km_pro_chatter_toggle {{ state.isChatterOpen ? 'active' : '' }}" title="Close chatter panel" t-on-click="() => state.isChatterOpen = !state.isChatterOpen">
                        <i class="fa fa-comments-o"></i>
                    </div>
                    <div t-attf-class="km_pro_favorite_toggle {{ props.isFavorite ? 'active' : '' }}" t-att-title="props.isFavorite ? 'Remove from favorites' : 'Add to favorites'" t-on-click="props.toggleFavorite">
                        <i t-attf-class="fa {{ props.isFavorite ? 'fa-star' : 'fa-star-o' }}"></i>
                    </div>
                    
                    <div class="km_pro_more_container" style="position: relative;">
                        <i class="fa fa-ellipsis-v km_pro_more_btn" title="More actions" t-on-click="() => state.isMoreMenuOpen = !state.isMoreMenuOpen"></i>
                        
                        <t t-if="state.isMoreMenuOpen">
                            <div class="km_pro_more_menu shadow">
                                <t t-if="!state.article.is_locked">
                                    <div class="km_pro_more_item" t-on-click="(ev) => { ev.stopPropagation(); state.isEmojiPickerOpen = true; state.isMoreMenuOpen = false; }">
                                        <i class="fa fa-smile-o"></i> Add Icon
                                    </div>
                                    <div class="km_pro_more_item" t-on-click="() => this.triggerCoverUpload()">
                                        <i class="fa fa-picture-o"></i> Add Cover
                                    </div>
                                    <div class="km_pro_more_item disabled">
                                        <i class="fa fa-commenting-o"></i> Add Discussion
                                    </div>
                                </t>
                                <div class="km_pro_more_item space-between" t-on-click="toggleFullWidth">
                                    <span><i class="fa fa-arrows-h"></i> Full Width</span>
                                    <span t-attf-class="km_pro_toggle_switch {{ state.isFullWidth ? 'active' : '' }}"></span>
                                </div>
                                
                                <div class="km_pro_more_divider"></div>
                                
                                <div class="km_pro_more_item" t-on-click="(ev) => { props.moveArticle(); state.isMoreMenuOpen = false; }">
                                    <i class="fa fa-angle-double-right"></i> Move To
                                </div>
                                <t t-if="state.article and state.article.is_locked">
                                    <div class="km_pro_more_item" t-on-click="() => this.toggleLock()">
                                        <i class="fa fa-unlock"></i> Unlock
                                    </div>
                                </t>
                                <t t-else="">
                                    <div class="km_pro_more_item" t-on-click="() => this.toggleLock()">
                                        <i class="fa fa-lock"></i> Lock Content
                                    </div>
                                </t>
                                <div class="km_pro_more_separator"></div>
                                <div class="km_pro_more_item delete" t-on-click="(ev) => { props.deleteArticle(); state.isMoreMenuOpen = false; }">
                                    <i class="fa fa-trash"></i> Delete
                                </div>
                                <div class="km_pro_more_item" t-on-click="(ev) => { props.duplicateArticle(); state.isMoreMenuOpen = false; }">
                                    <i class="fa fa-files-o"></i> Create a Copy
                                </div>
                                <div class="km_pro_more_item" t-on-click="(ev) => { props.createNewArticle(); state.isMoreMenuOpen = false; }">
                                    <i class="fa fa-level-down"></i> New Child Article
                                </div>
                                <div class="km_pro_more_item" t-on-click="() => this.openHistoryModal()">
                                    <i class="fa fa-history"></i> Open Version History
                                </div>
                                <div class="km_pro_more_item" t-on-click="(ev) => { this.downloadPdf(); state.isMoreMenuOpen = false; }">
                                    <i class="fa fa-download"></i> Download PDF
                                </div>
                                <div class="km_pro_more_item" t-on-click="() => this.addToTemplates()">
                                    <i class="fa fa-copy"></i> Add to Templates
                                </div>
                                <div class="km_pro_more_item delete" t-on-click="(ev) => { props.deleteArticle(); state.isMoreMenuOpen = false; }">
                                    <i class="fa fa-trash"></i> Move to Trash
                                </div>
                                
                                <div class="km_pro_more_divider"></div>
                                
                                <div class="km_pro_more_footer">
                                    <div class="footer-time">Last Edited · <t t-esc="this.formatTimeAgo(state.article ? state.article.write_date : false)"/></div>
                                    <div class="footer-user">
                                        <span class="user-avatar" t-esc="state.article ? (state.article.write_uid ? state.article.write_uid[1].charAt(0).toUpperCase() : 'U') : 'U'"></span>
                                        <span class="user-name" t-esc="state.article ? (state.article.write_uid ? state.article.write_uid[1] : 'User') : 'User'"></span>
                                    </div>
                                </div>
                            </div>
                        </t>
                    </div>
                </div>
            </div>
            
            <div style="display: flex; flex: 1; overflow: hidden; position: relative;">
                <div style="flex: 1; display: flex; flex-direction: column; overflow: hidden;">
                    <!-- MAIN EDITOR (Hidden when a card is active) -->
                    <div t-ref="root" t-att-style="state.activeCard ? 'display: none;' : ''" style="display: flex; flex-direction: column; flex: 1; height: 100%; overflow-y: auto; position: relative;">
                        <t t-if="state.isKanbanMode">
                            <!-- Kanban Board (scrolls with editor) -->
                            <div class="km_pro_kanban_board_wrapper" style="flex: 0 0 auto;">
                                <KnowledgeKanbanBoard title="this.kanbanDisplayTitle" initialData="state.kanbanData" onChange="(data) => this.handleKanbanChange(data)" onCardClick="(card, colId, triggerChange) => this.openKanbanCard(card, colId, triggerChange)"/>
                            </div>
                        </t>
                        <t t-elif="state.isListMode">
                            <!-- List Board (scrolls with editor) -->
                            <div class="km_pro_kanban_board_wrapper" style="flex: 0 0 auto;">
                                <KnowledgeListMockup
                                    itemName="state.listTitle"
                                    initialData="state.listData"
                                    onChange="(data) => this.handleListChange(data)"
                                    onNewItem="(articleId) => this.onListNewItem(articleId)"
                                />
                            </div>
                        </t>
                        <t t-elif="state.isCalendarMode">
                            <div style="flex: 1;">
                                <KnowledgeCalendarBoard title="state.calendarTitle" initialData="state.calendarData" onChange="(data) => this.handleCalendarChange(data)" />
                            </div>
                        </t>
                        <!-- Article content editor: always rendered. In kanban/list mode = below-editor, normal = full editor -->
                        <t t-if="!state.isCalendarMode">
                            <div t-att-class="(state.isKanbanMode or state.isListMode) ? 'km_pro_kanban_below_editor' : ''"
                                 style="flex: 1; display: flex; flex-direction: column;">
                                <input type="file" t-ref="fileInput" style="display: none;" accept="image/*" t-on-change="onCoverFileChange" />
                        <input type="file" t-ref="imageInput" style="display: none;" accept="image/*" t-on-change="onImageFileChange" />
                        <input type="file" t-ref="documentInput" style="display: none;" t-on-change="onDocumentFileChange" />
                        
                        <!-- Floating Image Menu -->
                        <t t-if="state.selectedImage">
                            <div class="km_pro_image_toolbar shadow" t-attf-style="position: fixed; top: {{ state.imageToolbarTop }}px; left: {{ state.imageToolbarLeft }}px; transform: translateX(-50%); z-index: 1060; display: flex; align-items: center; background: #212529; border-radius: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.5); overflow: hidden;">
                                <button title="Wrap text left" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.setImageFloat('left')" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-align-left"></i></button>
                                <button title="Wrap text right" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.setImageFloat('right')" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-align-right"></i></button>
                                <button title="Crop image" style="background: #343a40; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer;" t-on-click.prevent="() => this.openCropModal()"><i class="fa fa-crop"></i></button>
                                <button title="Resize" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; font-family: sans-serif; font-size: 13px; font-weight: bold; transition: background 0.1s; display: flex; align-items: center;" t-on-click.prevent="() => this.cycleImageSize()" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-arrows-alt" style="margin-right: 4px;"></i> <t t-esc="state.imageSizeLabel"/></button>
                                <button title="Link" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.insertTextLink()" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-link"></i></button>
                                <button title="Preview" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.previewImage()" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-search-plus"></i></button>
                                <button title="Description" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.addCaption()" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-file-text-o"></i></button>
                                <button title="Replace image" style="background: transparent; color: #fff; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.triggerImageUpload()" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-picture-o"></i></button>
                                <button title="Remove" style="background: transparent; color: #dc3545; border: none; border-right: 1px solid #343a40; padding: 8px 12px; cursor: pointer; transition: background 0.1s;" t-on-click.prevent="() => this.removeSelectedImage()" onmouseover="this.style.background='#c82333'; this.style.color='#fff'" onmouseout="this.style.background='transparent'; this.style.color='#dc3545'"><i class="fa fa-trash"></i></button>
                                <button title="Comment" style="background: transparent; color: #fff; border: none; padding: 8px 12px; cursor: pointer; font-family: sans-serif; font-size: 13px; transition: background 0.1s; display: flex; align-items: center;" t-on-click.prevent="() => this.addComment()" onmouseover="this.style.background='#343a40'" onmouseout="this.style.background='transparent'"><i class="fa fa-commenting-o" style="margin-right: 4px;"></i>Comment</button>
                            </div>
                        </t>

                        <!-- Floating Table Menu -->
                        <t t-if="state.selectedTable">
                            <div class="km_pro_table_toolbar shadow" t-attf-style="position: fixed; top: {{ state.tableToolbarTop }}px; left: {{ state.tableToolbarLeft }}px; transform: translateX(-50%); z-index: 1060; display: flex; gap: 8px; padding: 6px 12px; background: #2b2b30; border: 1px solid #4a4a50; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                                <button title="Add Row" t-on-click.prevent="() => this.addTableRow()" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-plus"></i> Row</button>
                                <button title="Delete Row" t-on-click.prevent="() => this.deleteTableRow()" style="background: transparent; color: #ff4d4d; border: none; cursor: pointer;"><i class="fa fa-minus"></i> Row</button>
                                <div style="width: 1px; background: #4a4a50; margin: 0 4px;"></div>
                                <button title="Add Column" t-on-click.prevent="() => this.addTableColumn()" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-plus"></i> Col</button>
                                <button title="Delete Column" t-on-click.prevent="() => this.deleteTableColumn()" style="background: transparent; color: #ff4d4d; border: none; cursor: pointer;"><i class="fa fa-minus"></i> Col</button>
                                <div style="width: 1px; background: #4a4a50; margin: 0 4px;"></div>
                                <button title="Delete Table" t-on-click.prevent="() => this.deleteTable()" style="background: transparent; color: #ff4d4d; border: none; cursor: pointer;"><i class="fa fa-trash"></i> Table</button>
                            </div>
                        </t>

                        <!-- Cover Display (Full Width) -->
                        <t t-if="!state.isKanbanMode and state.article and state.article.cover_image">
                            <div t-attf-class="km_pro_cover_container {{ state.isRepositioning ? 'repositioning' : '' }}" t-on-mousedown="startDrag" t-on-mousemove="onCoverDrag" t-on-mouseup="stopDrag" t-on-mouseleave="stopDrag">
                                <img t-attf-src="data:image/jpeg;base64,{{state.article.cover_image}}" 
                                     class="km_pro_cover_img" 
                                     t-att-style="'object-position: 50% ' + (state.article.cover_position || 50) + '%'" 
                                     draggable="false" />
                                
                                <t t-if="state.isRepositioning">
                                    <div class="km_pro_cover_reposition_instruction">
                                        <span>Click and hold to reposition</span>
                                    </div>
                                    <div class="km_pro_cover_save_controls">
                                        <button t-on-click="(ev) => { ev.stopPropagation(); this.saveReposition(); }">Save Position</button>
                                    </div>
                                </t>
                                <t t-else="">
                                    <div class="km_pro_cover_controls" t-if="!state.article.is_locked">
                                        <button t-on-click="() => this.triggerCoverUpload()"><i class="fa fa-picture-o"></i> Replace Cover</button>
                                        <button t-on-click="(ev) => { ev.stopPropagation(); this.startRepositionMode(ev); }"><i class="fa fa-arrows-v"></i> Reposition</button>
                                        <button t-on-click="() => this.removeCover()"><i class="fa fa-trash"></i> Remove</button>
                                    </div>
                                </t>
                            </div>
                        </t>

                        <div t-attf-class="km_pro_editor_content {{ state.isFullWidth ? 'full_width' : '' }}" t-on-mousemove="onEditorMouseMove">

                            <!-- Icon Display -->
                            <t t-if="!state.isKanbanMode">
                                <div class="km_pro_icon_container" style="position: relative;">
                                    <t t-if="state.article and state.article.icon">
                                        <div class="km_pro_icon_display" t-on-click="() => this.toggleEmojiPicker()">
                                            <t t-esc="state.article.icon" />
                                        </div>
                                    </t>
                                    <t t-if="state.isEmojiPickerOpen">
                                        <KnowledgeEmojiPicker onSelect="(icon) => this.saveIcon(icon)" onRemove="() => this.saveIcon(false)" />
                                    </t>
                                </div>
    

                            </t>
                        
                            <t t-if="state.article and !state.article.is_locked and state.isToolbarVisible">
                                <div class="km_pro_format_toolbar shadow" t-attf-style="position: fixed; top: {{ state.toolbarTop }}px; left: {{ state.toolbarLeft }}px; transform: translateX(-50%); z-index: 1050; display: flex; gap: 8px; padding: 4px 8px; background: var(--km-bg-dropdown); border: 1px solid var(--km-border-color); border-radius: 6px; align-items: center; box-shadow: var(--km-shadow-lg); white-space: nowrap;">
                                    <select class="km_pro_format_select" t-on-change="(ev) => this.execFormat('formatBlock', ev.target.value)" style="background: var(--km-bg-input); color: var(--km-text-title); border: 1px solid var(--km-border-color); border-radius: 4px; padding: 4px 8px; cursor: pointer; font-weight: 500;">
                                        <option value="H1_DISPLAY_1">Header 1 Display 1</option>
                                        <option value="H1">Header 1</option>
                                        <option value="H2">Header 2</option>
                                        <option value="H3">Header 3</option>
                                        <option value="H4">Header 4</option>
                                        <option value="H5">Header 5</option>
                                        <option value="H6">Header 6</option>
                                        <option value="DIV">Normal</option>
                                        <option value="P">Paragraph</option>
                                        <option value="PRE">Code</option>
                                        <option value="BLOCKQUOTE">Quote</option>
                                    </select>
                                    
                                    <select class="km_pro_format_select" t-on-change="(ev) => this.execFormat('fontName', ev.target.value)" style="background: var(--km-bg-input); color: var(--km-text-title); border: 1px solid var(--km-border-color); border-radius: 4px; padding: 4px 8px; cursor: pointer; font-weight: 500;">
                                        <option value="">Default system font</option>
                                        <option value="Arial" style="font-family: Arial, sans-serif;">Arial (sans-serif)</option>
                                        <option value="Verdana" style="font-family: Verdana, sans-serif;">Verdana (sans-serif)</option>
                                        <option value="Tahoma" style="font-family: Tahoma, sans-serif;">Tahoma (sans-serif)</option>
                                        <option value="'Trebuchet MS'" style="font-family: 'Trebuchet MS', sans-serif;">Trebuchet MS (sans-serif)</option>
                                        <option value="'Courier New'" style="font-family: 'Courier New', monospace;">Courier New (monospace)</option>
                                    </select>

                                    <select class="km_pro_format_select" t-on-change="(ev) => this.execFormat('fontSize', ev.target.value)" style="background: var(--km-bg-input); color: var(--km-text-title); border: 1px solid var(--km-border-color); border-radius: 4px; padding: 4px 8px; cursor: pointer;">
                                        <option value="13">13</option>
                                        <option value="14" selected="1">14</option>
                                        <option value="15">15</option>
                                        <option value="17">17</option>
                                        <option value="18">18</option>
                                        <option value="21">21</option>
                                        <option value="34">34</option>
                                        <option value="56">56</option>
                                        <option value="64">64</option>
                                        <option value="72">72</option>
                                        <option value="80">80</option>
                                    </select>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: var(--km-border-color); margin: 0 4px;"></div>
                                    
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('bold')" title="Bold" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-bold"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('italic')" title="Italic" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-italic"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('underline')" title="Underline" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-underline"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('strikeThrough')" title="Strikethrough" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-strikethrough"></i></button>

                                    <div class="km_pro_format_btn" style="position: relative; display: flex; align-items: center; padding: 4px 8px; cursor: pointer; border-radius: 4px;" title="Text Color">
                                        <i class="fa fa-font" style="color: var(--km-text-title); pointer-events: none;"></i>
                                        <input type="color" t-on-input="(ev) => this.execFormat('foreColor', ev.target.value)" style="opacity: 0; position: absolute; left: 0; top: 0; width: 100%; height: 100%; cursor: pointer;" />
                                    </div>

                                    <div class="km_pro_format_btn" style="position: relative; display: flex; align-items: center; padding: 4px 8px; cursor: pointer; border-radius: 4px;" title="Highlight Color">
                                        <i class="fa fa-paint-brush" style="color: var(--km-text-title); pointer-events: none;"></i>
                                        <input type="color" t-on-input="(ev) => this.execFormat('backColor', ev.target.value)" style="opacity: 0; position: absolute; left: 0; top: 0; width: 100%; height: 100%; cursor: pointer;" />
                                    </div>

                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('removeFormat')" title="Remove Format" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-eraser"></i></button>

                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: var(--km-border-color); margin: 0 4px;"></div>

                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('insertUnorderedList')" title="List" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-list-ul"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('justifyLeft')" title="Align" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-align-left"></i></button>

                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: var(--km-border-color); margin: 0 4px;"></div>

                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.insertTextLink()" title="Link" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-link"></i></button>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: var(--km-border-color); margin: 0 4px;"></div>
                                    
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.translateSelectedText()" title="Translate" style="background: transparent; border: none; color: var(--km-text-title); cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-language"></i></button>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: var(--km-border-color); margin: 0 4px;"></div>

                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.addComment()" title="Comment" style="background: transparent; border: none; color: var(--km-primary); cursor: pointer; padding: 4px 8px; border-radius: 4px; display: flex; align-items: center; gap: 6px; font-weight: 600;">
                                        <i class="fa fa-comment-o"></i> Comment
                                    </button>
                                </div>
                            </t>
                                
                            <div class="km_pro_article_content" 
                                 t-ref="content" 
                                 t-att-contenteditable="state.article and state.article.is_locked ? 'false' : 'true'" 
                                 t-on-input="onInput"
                                 t-on-click="onEditorClick"
                                 t-on-keydown="onEditorKeydown"
                                 style="min-height: 200px; outline: none; margin-top: 8px;"
                                 placeholder=""></div>

                            <t t-if="state.isSlashMenuOpen">
                                <div class="km_pro_slash_menu shadow" t-attf-style="position: fixed !important; top: {{ state.slashMenuTop }}px !important; left: {{ state.slashMenuLeft }}px !important; z-index: 1060; background: var(--km-bg-dropdown); border: 1px solid var(--km-border-color); border-radius: 6px; box-shadow: var(--km-shadow-lg); width: 250px; max-height: 300px; overflow-y: auto;">
                                    <div style="padding: 8px 12px; font-size: 0.75rem; color: var(--km-text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Format</div>
                                    <t t-foreach="slashMenuItems" t-as="item" t-key="item.id">
                                        <div class="km_pro_slash_item" 
                                             t-att-class="{'selected': state.slashMenuSelectedIndex === item_index}"
                                             t-on-mousedown.prevent="() => this.executeSlashCommand(item)"
                                             t-on-mouseenter="() => state.slashMenuSelectedIndex = item_index"
                                             style="display: flex; align-items: center; gap: 12px; padding: 8px 12px; cursor: pointer; color: var(--km-text-main); transition: background 0.1s;">
                                            <div style="width: 24px; height: 24px; border-radius: 4px; background: var(--km-bg-tertiary); color: var(--km-primary); display: flex; align-items: center; justify-content: center;">
                                                <i t-attf-class="fa {{ item.icon }}"></i>
                                            </div>
                                            <div>
                                                <div style="font-weight: 500; font-size: 0.95rem; color: var(--km-text-title);"><t t-esc="item.title"/></div>
                                                <div style="font-size: 0.8rem; color: var(--km-text-muted);"><t t-esc="item.description"/></div>
                                            </div>
                                        </div>
                                    </t>
                                </div>
                            </t>

                            <t t-if="state.article and !state.article.content">
                                <div class="km_pro_empty_state_quick_actions" style="margin-top: 0; padding-top: 0;">
                                    <p class="km_pro_hint_text">Keep writing, or choose an option below to jump right in!</p>
                                    
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionTemplate">
                                        <i class="fa fa-paint-brush"></i> Load a Template
                                    </div>
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionKanban">
                                        <i class="fa fa-th-large"></i> Build an Item Kanban
                                    </div>
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionList">
                                        <i class="fa fa-list"></i> Build an Item List
                                    </div>
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionCalendar">
                                        <i class="fa fa-calendar"></i> Build an Item Calendar
                                    </div>
                                    <div class="km_pro_quick_action km_pro_ai_action" t-on-click="onQuickActionAI">
                                        <i class="fa fa-magic"></i> Generate an Article with AI
                                    </div>
                                </div>
                            </t>
                            <!-- Floating Inline Toolbar -->
                            <t t-if="state.isLineEmptyVisible">
                                <div class="km_pro_inline_commands" t-attf-style="position: fixed !important; top: {{ state.lineEmptyTop }}px !important; left: {{ state.lineEmptyLeft }}px !important; z-index: 1040; display: flex; align-items: center; color: #a0a0a0; font-size: 1.05rem; gap: 12px; pointer-events: none;">
                                    <span style="color: #adb5bd; pointer-events: none; user-select: none;">Type "/" for commands</span>
                                    <div style="display: flex; gap: 4px; align-items: center; pointer-events: auto;">
                                        <i class="fa fa-picture-o" title="Image" t-on-mousedown.prevent="() => this.triggerImageUpload()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        <i class="fa fa-upload" title="Document" t-on-mousedown.prevent="() => this.triggerDocumentUpload()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        <i class="fa fa-square" title="Block" t-on-mousedown.prevent="() => this.execFormat('formatBlock', 'P')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        <i class="fa fa-list-ul" title="Bullet List" t-on-mousedown.prevent="() => this.execFormat('insertUnorderedList')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        <i class="fa fa-list-ol" title="Numbered List" t-on-mousedown.prevent="() => this.execFormat('insertOrderedList')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        <i class="fa fa-check-square-o" title="Checkbox" t-on-mousedown.prevent="() => this.insertCheckbox()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        <strong title="AI" t-on-mousedown.prevent="onQuickActionAI" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s; font-family: sans-serif; font-size: 0.9rem;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'">AI</strong>
                                        <i class="fa fa-ellipsis-v" title="More" t-on-mousedown.prevent="openMoreMenu" style="cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                    </div>
                                </div>
                            </t>



                                    <!-- Heading Link Icon -->
                                    <t t-if="state.isHeadingLinkVisible">
                                        <div class="km_pro_heading_link" 
                                             t-attf-style="position: fixed; top: {{ state.headingLinkTop }}px; left: {{ state.headingLinkLeft }}px; z-index: 1045; cursor: pointer; color: #a0a0a0; font-size: 1.1rem; padding: 4px; border-radius: 4px; transition: color 0.2s, background 0.2s;"
                                             title="Copy a link to this heading to the clipboard"
                                             t-on-click="copyHeadingLink"
                                             onmouseover="this.style.color='#fff'; this.style.background='rgba(255,255,255,0.1)'"
                                             onmouseout="this.style.color='#a0a0a0'; this.style.background='transparent'">
                                            <i class="fa fa-link"></i>
                                        </div>
                                    </t>
                                </div>
                            </div>
                        </t>
                    </div> <!-- END MAIN EDITOR -->

                    <!-- CARD EDITOR -->
                    <!-- CARD EDITOR (Full Article Experience for Kanban Cards) -->
                    <t t-if="state.activeCard">
                        <div class="km_pro_card_editor_light" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; background: var(--km-bg-main); position: relative;">
                            <div class="km_pro_card_editor_breadcrumb" style="display: flex; align-items: center; gap: 8px; padding: 12px 32px; border-bottom: 1px solid var(--km-border-light, #dee2e6); font-size: 14px; background: var(--km-bg-card);">
                                <span class="km_pro_card_editor_back_btn" t-on-click="() => this.closeKanbanCard()" style="cursor: pointer; color: #714B67; font-weight: 500; display: flex; align-items: center; gap: 6px;">
                                    <i class="fa fa-arrow-left"></i> <t t-esc="state.article ? state.article.name : 'Untitled'"/>
                                </span>
                                <span style="color: #adb5bd;">/</span>
                                <span style="color: var(--km-text-main); font-weight: 600;"><t t-esc="state.activeCard.content || 'Untitled'"/></span>
                            </div>

                            <div class="km_pro_editor_content" style="padding: 36px 10%; max-width: 800px; margin: 0 auto; width: 100%; flex: 1;">
                                <input type="text" 
                                       class="km_pro_title_input km_pro_card_title_input" 
                                       placeholder="Untitled"
                                       t-att-value="state.activeCard.content === 'Untitled' ? '' : (state.activeCard.content || '')" 
                                       t-on-input="(ev) => this.onCardTitleInput(ev)" 
                                       t-on-focus="onTitleFocus"
                                       style="font-size: 2.2rem; font-weight: 700; color: var(--km-text-title); border: none; outline: none; width: 100%; margin-bottom: 20px; background: transparent; padding: 0;" />

                                <!-- Card Article Content with Slash Commands and Rich Editing -->
                                <div class="km_pro_article_content km_pro_card_editor_body" 
                                     t-ref="cardContentRef" 
                                     contenteditable="true" 
                                     t-on-input="(ev) => this.onCardContentInput(ev)"
                                     t-on-keydown="(ev) => this.onCardContentKeydown(ev)"
                                     t-on-click="(ev) => this.onEditorClick(ev)"
                                     style="min-height: 250px; outline: none; font-size: 1.05rem; line-height: 1.6;"
                                     placeholder="">
                                    <t t-out="state.activeCard.article_content || ''" />
                                </div>
                                <t t-if="state.isSlashMenuOpen">
                                    <div class="km_pro_slash_menu shadow" t-attf-style="position: fixed !important; top: {{ state.slashMenuTop }}px !important; left: {{ state.slashMenuLeft }}px !important; z-index: 1060; background: var(--km-bg-dropdown); border: 1px solid var(--km-border-color); border-radius: 6px; box-shadow: var(--km-shadow-lg); width: 250px; max-height: 300px; overflow-y: auto;">
                                        <div style="padding: 8px 12px; font-size: 0.75rem; color: var(--km-text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Format</div>
                                        <t t-foreach="slashMenuItems" t-as="item" t-key="item.id">
                                            <div class="km_pro_slash_item" 
                                                 t-att-class="{'selected': state.slashMenuSelectedIndex === item_index}"
                                                 t-on-mousedown.prevent="() => this.executeSlashCommand(item)"
                                                 t-on-mouseenter="() => state.slashMenuSelectedIndex = item_index"
                                                 style="display: flex; align-items: center; gap: 12px; padding: 8px 12px; cursor: pointer; color: var(--km-text-main); transition: background 0.1s;">
                                                <div style="width: 24px; height: 24px; border-radius: 4px; background: var(--km-bg-tertiary); color: var(--km-primary); display: flex; align-items: center; justify-content: center;">
                                                    <i t-attf-class="fa {{ item.icon }}"></i>
                                                </div>
                                                <div>
                                                    <div style="font-weight: 500; font-size: 0.95rem; color: var(--km-text-title);"><t t-esc="item.title"/></div>
                                                    <div style="font-size: 0.8rem; color: var(--km-text-muted);"><t t-esc="item.description"/></div>
                                                </div>
                                            </div>
                                        </t>
                                    </div>
                                </t>
                                <t t-if="state.isLineEmptyVisible">
                                    <div class="km_pro_inline_commands" t-attf-style="position: fixed !important; top: {{ state.lineEmptyTop }}px !important; left: {{ state.lineEmptyLeft }}px !important; z-index: 1040; display: flex; align-items: center; color: #a0a0a0; font-size: 1.05rem; gap: 12px; pointer-events: none;">
                                        <span style="color: #adb5bd; pointer-events: none; user-select: none;">Type "/" for commands</span>
                                        <div style="display: flex; gap: 4px; align-items: center; pointer-events: auto;">
                                            <i class="fa fa-picture-o" title="Image" t-on-mousedown.prevent="() => this.triggerImageUpload()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-upload" title="Document" t-on-mousedown.prevent="() => this.triggerDocumentUpload()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-square" title="Block" t-on-mousedown.prevent="() => this.execFormat('formatBlock', 'P')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-list-ul" title="Bullet List" t-on-mousedown.prevent="() => this.execFormat('insertUnorderedList')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-list-ol" title="Numbered List" t-on-mousedown.prevent="() => this.execFormat('insertOrderedList')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-check-square-o" title="Checkbox" t-on-mousedown.prevent="() => this.insertCheckbox()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <strong title="AI" t-on-mousedown.prevent="onQuickActionAI" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s; font-family: sans-serif; font-size: 0.9rem;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'">AI</strong>
                                            <i class="fa fa-ellipsis-v" title="More" t-on-mousedown.prevent="openMoreMenu" style="cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(0,0,0,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        </div>
                                    </div>
                                </t>



                            </div>
                        </div>
                    </t>
                </div> <!-- END CENTER PANEL -->

                <!-- History Modal -->
                <t t-if="state.isHistoryModalOpen">
                    <div class="km_pro_modal_backdrop" style="background: rgba(0,0,0,0.6);" t-on-click="() => this.closeHistoryModal()">
                        <div class="km_pro_history_modal shadow" t-on-click="(ev) => ev.stopPropagation()">
                            
                            <div class="history-modal-header">
                                <h3 class="history-modal-title">History</h3>
                                <div class="history-header-actions">
                                    <i class="fa fa-expand"></i>
                                    <i class="fa fa-times" style="font-size: 1.2rem;" t-on-click="() => this.closeHistoryModal()"></i>
                                </div>
                            </div>
                            
                            <div class="history-modal-body">
                                <!-- Left Sidebar (Timeline) -->
                                <div class="history-sidebar">
                                    <t t-foreach="state.historyVersions" t-as="version" t-key="version.id">
                                        <div t-attf-class="history-timeline-item {{ state.selectedHistoryVersion and state.selectedHistoryVersion.id === version.id ? 'active' : '' }}" t-on-click="() => this.selectHistoryVersion(version)">
                                            <div class="history-timeline-line"></div>
                                            <div class="history-timeline-node">
                                                <i t-if="state.selectedHistoryVersion and state.selectedHistoryVersion.id === version.id" class="fa fa-play-circle"></i>
                                                <div t-else="" class="history-dot"></div>
                                            </div>
                                            <div class="history-version-details">
                                                <div class="history-version-time">
                                                    <strong style="color: #fff; margin-right: 6px;">v<t t-esc="version.version_number"/></strong>
                                                    <t t-esc="this.formatHistoryDate(version.date)"/>
                                                </div>
                                                <div class="history-version-author" style="display:flex; justify-content:space-between; align-items:center;">
                                                    <span>by <t t-esc="version.user_id ? version.user_id[1] : 'Unknown'"/></span>
                                                    <span t-if="version_index === 0" style="background:#005a5a; color:#fff; font-size:0.7rem; padding:2px 6px; border-radius:10px;">CURRENT</span>
                                                </div>
                                                <div style="font-size: 0.8rem; color: #888; margin-top: 4px; font-style: italic;">
                                                    <t t-esc="version.change_summary or ''"/>
                                                </div>
                                            </div>
                                            <div class="history-version-avatar" t-esc="version.user_id ? version.user_id[1].charAt(0).toUpperCase() : 'U'"></div>
                                        </div>
                                    </t>
                                    <t t-if="state.historyVersions.length === 0">
                                        <div style="padding: 24px; color: #a0a0a0; text-align: center;">No version history found.</div>
                                    </t>
                                </div>
                                
                                <!-- Right Preview Area -->
                                <div class="history-preview-area">
                                    <div class="history-preview-topbar" style="display:flex; justify-content:space-between; width:100%; align-items:center;">
                                        <div style="display:flex; align-items:center; gap: 12px;">
                                            <div t-attf-class="history-toggle-switch {{ state.showHistoryComparison ? 'active' : '' }}" t-on-click="() => state.showHistoryComparison = !state.showHistoryComparison">
                                                <div class="toggle-circle"></div>
                                            </div>
                                            <span class="history-toggle-label">Show comparison</span>
                                        </div>
                                        <div t-if="state.showHistoryComparison" style="display:flex; align-items:center; gap: 8px;">
                                            <span style="color:#a0a0a0; font-size:0.9rem;">Compare with:</span>
                                            <select style="background:#242426; border:1px solid #36363a; color:#fff; border-radius:4px; padding:4px 8px;" t-on-change="(ev) => state.compareVersion = state.historyVersions.find(v => v.id == ev.target.value)">
                                                <t t-foreach="state.historyVersions" t-as="v" t-key="v.id">
                                                    <option t-att-value="v.id" t-att-selected="state.compareVersion and state.compareVersion.id == v.id">
                                                        Version <t t-esc="v.version_number"/> (<t t-esc="this.formatHistoryDate(v.date)"/>)
                                                    </option>
                                                </t>
                                            </select>
                                            <button style="background:transparent; border:1px solid #36363a; color:#e0e0e0; border-radius:4px; padding:4px 8px; cursor:pointer;" t-on-click="() => this.compareWithPrevious()">
                                                Compare with Previous
                                            </button>
                                        </div>
                                    </div>
                                    
                                    <t t-if="state.selectedHistoryVersion">
                                        <div class="history-info-banner">
                                            <i class="fa fa-info-circle"></i>
                                            <span>Showing Version <strong t-esc="state.selectedHistoryVersion.version_number"/> (Read Only) - <strong t-esc="state.selectedHistoryVersion.user_id ? state.selectedHistoryVersion.user_id[1] : 'Unknown'"/> on <strong t-esc="this.formatHistoryDateFull(state.selectedHistoryVersion.date)"/> - <em t-esc="state.selectedHistoryVersion.change_summary"></em></span>
                                        </div>
                                        
                                        <t t-if="!state.showHistoryComparison">
                                            <div class="history-content-preview" style="padding:40px; overflow-y:auto; height: calc(100% - 130px);">
                                                <h1 style="color:#fff; margin-bottom: 20px;" t-esc="state.selectedHistoryVersion.title_snapshot or 'Untitled'"></h1>
                                                <div class="history-content-inner" t-out="state.selectedHistoryVersion.content_snapshot || '&lt;div style=\'text-align:center;color:#666;\'&gt;No content&lt;/div&gt;'"></div>
                                            </div>
                                        </t>
                                        <t t-else="">
                                            <div class="history-comparison-split" style="display:flex; gap:20px; padding:20px; height: calc(100% - 130px); overflow-y: auto;">
                                                <div class="history-compare-pane" style="flex:1; border:1px solid #36363a; border-radius:6px; background:#1c1c1e; padding:20px; overflow-y:auto;">
                                                    <h4 style="margin-top:0; color:#a0a0a0; border-bottom:1px solid #36363a; padding-bottom:10px;">
                                                        <t t-if="state.compareVersion">Version <t t-esc="state.compareVersion.version_number"/></t>
                                                        <t t-else="">Select a version</t>
                                                    </h4>
                                                    <t t-if="state.compareVersion">
                                                        <h1 style="color:#fff; margin-bottom: 20px; font-size: 1.5rem;" t-esc="state.compareVersion.title_snapshot or 'Untitled'"></h1>
                                                        <div class="history-content-inner" t-out="state.compareVersion.content_snapshot || '&lt;div style=\'text-align:center;color:#666;\'&gt;No content&lt;/div&gt;'"></div>
                                                    </t>
                                                </div>
                                                <div class="history-compare-pane" style="flex:1; border:1px solid #36363a; border-radius:6px; background:#1c1c1e; padding:20px; overflow-y:auto;">
                                                    <h4 style="margin-top:0; color:#a0a0a0; border-bottom:1px solid #36363a; padding-bottom:10px;">Version <t t-esc="state.selectedHistoryVersion.version_number"/></h4>
                                                    <h1 style="color:#fff; margin-bottom: 20px; font-size: 1.5rem;" t-esc="state.selectedHistoryVersion.title_snapshot or 'Untitled'"></h1>
                                                    <div class="history-content-inner" t-out="state.selectedHistoryVersion.content_snapshot || '&lt;div style=\'text-align:center;color:#666;\'&gt;No content&lt;/div&gt;'"></div>
                                                </div>
                                            </div>
                                        </t>
                                    </t>
                                </div>
                            </div>
                            
                            <div class="history-modal-footer">
                                <button class="history-btn-restore" t-on-click="() => this.restoreHistory()">Restore history</button>
                                <button class="history-btn-discard" t-on-click="() => this.closeHistoryModal()">Discard</button>
                            </div>
                            
                        </div>
                    </div>
                </t>

                <!-- Chatter Panel -->
                <t t-if="state.isChatterOpen and props.activeArticleId">
                    <div class="km_pro_chatter_panel">
                        <Chatter threadModel="'knowledge.management.article'" threadId="props.activeArticleId" />
                    </div>
                </t>
            </div>
        </t>

        <t t-if="state.showKanbanDialog">
            <div class="km_pro_modal_backdrop" t-on-click="() => this.state.showKanbanDialog = false">
                <div class="km_pro_kanban_dialog" t-on-click="(ev) => ev.stopPropagation()">
                    <div class="km_pro_kanban_dialog_header">
                        <h4 class="km_pro_kanban_dialog_title">Insert a Kanban View</h4>
                        <i class="fa fa-times km_pro_kanban_dialog_close" t-on-click="() => this.state.showKanbanDialog = false"></i>
                    </div>
                    <div class="km_pro_kanban_dialog_body">
                        <label class="km_pro_kanban_dialog_label">What items do you want to manage?</label>
                        <input type="text" 
                               class="km_pro_kanban_dialog_input" 
                               t-model="state.kanbanItemName" 
                               placeholder="e.g. Buildings" 
                               t-on-keydown="(ev) => ev.key === 'Enter' and this.insertKanban()"
                               autofocus="autofocus" />
                    </div>
                    <div class="km_pro_kanban_dialog_footer">
                        <button class="km_pro_kanban_dialog_btn_insert" t-on-click="insertKanban">Insert</button>
                        <button class="km_pro_kanban_dialog_btn_discard" t-on-click="() => this.state.showKanbanDialog = false">Discard</button>
                    </div>
                </div>
            </div>
        </t>

        <t t-if="state.showListDialog">
            <div class="km_pro_modal_backdrop" t-on-click="() => this.state.showListDialog = false">
                <div class="km_pro_kanban_dialog" t-on-click="(ev) => ev.stopPropagation()">
                    <div class="km_pro_kanban_dialog_header">
                        <h4 class="km_pro_kanban_dialog_title">Insert a List View</h4>
                        <i class="fa fa-times km_pro_kanban_dialog_close" t-on-click="() => this.state.showListDialog = false"></i>
                    </div>
                    <div class="km_pro_kanban_dialog_body">
                        <label class="km_pro_kanban_dialog_label">What items do you want to manage?</label>
                        <input type="text" class="km_pro_kanban_dialog_input" t-model="state.listItemName" placeholder="e.g. Todos" t-on-keydown="(ev) => ev.key === 'Enter' and this.insertList()" autofocus="autofocus" />
                    </div>
                    <div class="km_pro_kanban_dialog_footer">
                        <button class="km_pro_kanban_dialog_btn_insert" t-on-click="insertList">Insert</button>
                        <button class="km_pro_kanban_dialog_btn_discard" t-on-click="() => this.state.showListDialog = false">Discard</button>
                    </div>
                </div>
            </div>
        </t>

        <t t-if="state.showCalendarDialog">
            <div class="km_pro_modal_backdrop" t-on-click="() => this.state.showCalendarDialog = false">
                <div class="km_pro_kanban_dialog" t-on-click="(ev) => ev.stopPropagation()">
                    <div class="km_pro_kanban_dialog_header">
                        <h4 class="km_pro_kanban_dialog_title">Insert a Calendar View</h4>
                        <i class="fa fa-times km_pro_kanban_dialog_close" t-on-click="() => this.state.showCalendarDialog = false"></i>
                    </div>
                    <div class="km_pro_kanban_dialog_body">
                        <label class="km_pro_kanban_dialog_label">What do you want to manage?</label>
                        <input type="text" class="km_pro_kanban_dialog_input" t-model="state.calendarItemName" placeholder="e.g. Meetings" t-on-keydown="(ev) => ev.key === 'Enter' and this.insertCalendar()" autofocus="autofocus" />
                    </div>
                    <div class="km_pro_kanban_dialog_footer">
                        <button class="km_pro_kanban_dialog_btn_insert" t-on-click="insertCalendar">Insert</button>
                        <button class="km_pro_kanban_dialog_btn_discard" t-on-click="() => this.state.showCalendarDialog = false">Discard</button>
                    </div>
                </div>
            </div>
        </t>

        <!-- Invite People Modal -->
        <t t-if="state.isInviteModalOpen">
            <div class="km_pro_invite_backdrop" t-on-click="() => state.isInviteModalOpen = false">
                <div class="km_pro_invite_modal" t-on-click="(ev) => ev.stopPropagation()">
                    <div class="invite-modal-header">
                        <h3>Invite people</h3>
                        <i class="fa fa-times modal-close-btn" t-on-click="() => state.isInviteModalOpen = false"></i>
                    </div>
                    <div class="invite-modal-body">
                        <div class="invite-row" style="margin-bottom: 16px;">
                            <div class="invite-permission-trigger" t-on-click="() => state.isInvitePermissionDropdownOpen = !state.isInvitePermissionDropdownOpen" style="display: flex; justify-content: space-between; align-items: center; position: relative; width: 100%; border: 1px solid var(--km-border-color); border-radius: 4px; padding: 8px; background: var(--km-bg-input); color: var(--km-text-title); cursor: pointer; user-select: none;">
                                <span class="permission-text-plain"><t t-esc="state.invitePermission"/></span>
                                <i class="fa fa-chevron-down" style="font-size: 0.8rem; color: var(--km-text-muted);"></i>
                                <t t-if="state.isInvitePermissionDropdownOpen">
                                    <div class="km_pro_nested_dropdown" style="position: absolute; top: 100%; left: 0; right: 0; min-width: 100%; margin-top: 4px; background: var(--km-bg-dropdown); border: 1px solid var(--km-border-color); border-radius: 4px; z-index: 1000; box-shadow: var(--km-shadow-lg); overflow: hidden;">
                                        <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.invitePermission = 'Edit'; state.isInvitePermissionDropdownOpen = false; }" style="padding: 8px 12px; cursor: pointer; color: var(--km-text-main); border-bottom: 1px solid var(--km-border-color);">Edit</div>
                                        <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.invitePermission = 'Read'; state.isInvitePermissionDropdownOpen = false; }" style="padding: 8px 12px; cursor: pointer; color: var(--km-text-main); border-bottom: 1px solid var(--km-border-color);">Read</div>
                                        <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.invitePermission = 'No access'; state.isInvitePermissionDropdownOpen = false; }" style="padding: 8px 12px; cursor: pointer; color: var(--km-text-main);">No access</div>
                                    </div>
                                </t>
                            </div>
                        </div>
                        
                        <div class="invite-row" style="flex-direction: column; align-items: stretch; margin-top: 16px;">
                            <div class="km_pro_selected_users" style="display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px;">
                                <t t-foreach="state.selectedUsersToInvite" t-as="user" t-key="user.id">
                                    <span style="background: var(--km-bg-tertiary); color: var(--km-text-title); padding: 4px 8px; border-radius: 12px; font-size: 0.85rem; display: flex; align-items: center; gap: 6px;">
                                        <t t-esc="user.name" />
                                        <i class="fa fa-times" style="cursor: pointer;" t-on-click="() => this.removeSelectedUser(user)"></i>
                                    </span>
                                </t>
                            </div>
                            
                            <div style="position: relative;">
                                <input type="text" class="invite-input-borderless" placeholder="Search people..." t-model="state.inviteSearchQuery" style="width: 100%; border: 1px solid var(--km-border-color); border-radius: 4px; padding: 8px; background: var(--km-bg-input); color: var(--km-text-title);" />
                                
                                <t t-if="filteredUsersToInvite.length > 0">
                                    <div class="km_pro_user_dropdown" style="position: absolute; top: 100%; left: 0; width: 100%; background: var(--km-bg-dropdown); border: 1px solid var(--km-border-color); border-radius: 4px; max-height: 150px; overflow-y: auto; z-index: 10;">
                                        <t t-foreach="filteredUsersToInvite" t-as="user" t-key="user.id">
                                            <div class="km_pro_user_dropdown_item" style="padding: 8px; cursor: pointer; border-bottom: 1px solid var(--km-border-color); color: var(--km-text-main);" t-on-click="() => this.selectUserToInvite(user)">
                                                <t t-esc="user.name" /> <span style="color: var(--km-text-muted); font-size: 0.8rem;">(<t t-esc="user.email or 'No email'"/>)</span>
                                            </div>
                                        </t>
                                    </div>
                                </t>
                            </div>
                        </div>
                        
                        <t t-if="state.currentShares.length > 0">
                            <div class="invite-row" style="flex-direction: column; align-items: stretch; margin-top: 24px;">
                                <h4 style="font-size: 0.9rem; color: #a0a0a0; margin-bottom: 12px;">People with access</h4>
                                <t t-foreach="state.currentShares" t-as="share" t-key="share.user.id">
                                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <div style="width: 28px; height: 28px; border-radius: 50%; background: #1a4b8c; color: white; display: flex; align-items: center; justify-content: center; font-size: 0.8rem;">
                                                <t t-esc="share.user.name.charAt(0).toUpperCase()" />
                                            </div>
                                            <span style="font-size: 0.9rem;"><t t-esc="share.user.name" /></span>
                                        </div>
                                        <div style="display: flex; align-items: center; gap: 12px;">
                                            <span style="font-size: 0.8rem; color: #a0a0a0; background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 4px;"><t t-esc="share.access_level === 'write' ? 'Edit' : (share.access_level === 'none' ? 'No access' : 'Read')" /></span>
                                            <i class="fa fa-times" style="cursor: pointer; color: #ff4d4d; font-size: 1rem; opacity: 0.8; transition: opacity 0.2s;" t-on-click="() => this.removeShare(share)" title="Remove Access" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.8'"></i>
                                        </div>
                                    </div>
                                </t>
                            </div>
                        </t>

                    </div>
                    <div class="invite-modal-footer">
                        <button class="invite-btn-primary" t-on-click="() => this.submitInvite()" t-att-disabled="state.selectedUsersToInvite.length === 0 ? 'disabled' : undefined">Invite</button>
                        <button class="invite-btn-secondary" t-on-click="() => state.isInviteModalOpen = false">Discard</button>
                    </div>
                </div>
            </div>
        </t>
        <!-- Comment Modal -->
        <t t-if="state.isCommentModalOpen">
            <div class="km_pro_comment_modal shadow" t-on-click="(ev) => ev.stopPropagation()" t-attf-style="position: absolute; top: {{ state.commentModalTop }}px; left: {{ state.commentModalLeft }}px; z-index: 1050; background: #242426; border: 1px solid #4a4a50; border-radius: 6px; width: 450px; padding: 12px; display: flex; flex-direction: column; gap: 16px; box-shadow: 0 8px 24px rgba(0,0,0,0.5);">
                
                <t t-set="threadComments" t-value="state.articleComments.filter(c => c.anchor_id === state.activeCommentAnchorId)"/>
                <t t-if="threadComments.length > 0">
                    <div class="km_pro_comment_thread" style="display: flex; flex-direction: column; gap: 16px; max-height: 250px; overflow-y: auto;">
                        <t t-foreach="threadComments" t-as="comment" t-key="comment.id">
                            <div style="display: flex; gap: 12px;">
                                <div class="km_pro_comment_avatar" style="flex-shrink: 0;">
                                    <img t-attf-src="/web/image?model=res.users&amp;id={{ comment.user_id[0] }}&amp;field=avatar_128" style="width: 32px; height: 32px; border-radius: 6px; object-fit: cover; background: #2b2b30;" onerror="this.src='/web/static/img/user_menu_avatar.png'"/>
                                </div>
                                <div class="km_pro_comment_message_container" style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
                                    <div style="display: flex; gap: 8px; align-items: baseline;">
                                        <span style="font-weight: 600; font-size: 0.9rem; color: #a6b2c2;"><t t-esc="comment.user_id[1]"/></span>
                                        <span style="font-size: 0.75rem; color: #767a80;"><t t-esc="this.formatTime(comment.date)"/></span>
                                    </div>
                                    <div style="background: #19382b; color: #e0e0e0; padding: 8px 12px; border-radius: 0 8px 8px 8px; font-size: 0.9rem; position: relative; width: fit-content; max-width: 100%; border: 1px solid #204736;">
                                        <div style="position: absolute; left: -6px; top: 0; width: 0; height: 0; border-top: 8px solid #19382b; border-left: 6px solid transparent;"></div>
                                        <t t-esc="comment.content"/>
                                    </div>
                                </div>
                            </div>
                        </t>
                    </div>
                </t>

                <div style="display: flex; gap: 12px;">
                    <div class="km_pro_comment_avatar" style="flex-shrink: 0;">
                        <img t-attf-src="/web/image?model=res.users&amp;id={{ session.uid }}&amp;field=avatar_128" style="width: 36px; height: 36px; border-radius: 8px; object-fit: cover; background: #2b2b30;" onerror="this.src='/web/static/img/user_menu_avatar.png'"/>
                    </div>
                <div class="km_pro_comment_body" style="flex: 1; display: flex; flex-direction: column; gap: 8px;">
                    <div style="position: relative;">
                        <input type="text" class="km_pro_comment_input" placeholder="Add a comment..." t-model="state.commentContent" t-on-keydown="(ev) => ev.key === 'Enter' and this.postComment()" style="width: 100%; background: #1c1d21; border: 1px solid #208f7b; border-radius: 6px; padding: 10px 36px 10px 12px; color: #e0e0e0; font-size: 0.95rem; outline: none; box-sizing: border-box;" autofocus="autofocus"/>
                        <i class="fa fa-smile-o" style="position: absolute; right: 12px; top: 12px; color: #a0a0a0; font-size: 1.1rem; cursor: pointer;"></i>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <button class="km_pro_comment_post_btn" t-on-click="() => this.postComment()" style="background: #4d3a54; color: #d3b4e3; border: none; padding: 6px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.9rem;">Post</button>
                        <div style="display: flex; gap: 16px; color: #8e8e93; font-size: 1.1rem; align-items: center;">
                            <img src="/knowledge_management_pro/static/description/icon.png" style="width: 16px; filter: grayscale(100%); opacity: 0.7; cursor: pointer;" title="AI Comment"/>
                            <i class="fa fa-paperclip" style="cursor: pointer;" title="Attach File"></i>
                        </div>
                    </div>
                </div>
                </div>
            </div>
            <div class="km_pro_comment_backdrop" t-on-click="() => this.cancelComment()" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 1040; background: transparent;"></div>
        </t>
        <!-- Crop Modal -->
        <t t-if="state.isCropModalOpen">
            <div class="km_pro_modal_backdrop" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 1060;">
                <div class="km_pro_modal" style="background: #242426; border-radius: 6px; border: 1px solid #36363a; width: 800px; max-width: 95%; height: 80vh; max-height: 800px; color: #e0e0e0; box-shadow: 0 4px 24px rgba(0,0,0,0.4); display: flex; flex-direction: column;">
                    <div class="km_pro_modal_header" style="display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-bottom: 1px solid #36363a;">
                        <h4 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #ffffff;">Crop Image</h4>
                        <div style="display: flex; gap: 8px;">
                            <button t-on-click="() => this.setCropAspectRatio(1)" style="background: #3f3f46; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;"><i class="fa fa-square"></i> 1:1</button>
                            <button t-on-click="() => this.setCropAspectRatio(16/9)" style="background: #3f3f46; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;"><i class="fa fa-youtube-play"></i> 16:9</button>
                            <button t-on-click="() => this.setCropAspectRatio(NaN)" style="background: #3f3f46; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;">Free</button>
                        </div>
                    </div>
                    <div class="km_pro_modal_body" style="flex: 1; padding: 24px; display: flex; justify-content: center; align-items: center; background: #1e1e24; overflow: hidden;">
                        <div style="max-width: 100%; max-height: 100%;">
                            <img id="km_pro_cropper_image" style="display: block; max-width: 100%;" />
                        </div>
                    </div>
                    <div class="km_pro_modal_footer" style="padding: 16px 24px; border-top: 1px solid #36363a; display: flex; justify-content: flex-end; gap: 12px;">
                        <button t-on-click="() => this.cancelCrop()" style="background: transparent; color: #a0a0a0; border: 1px solid #4a4a50; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer;">Cancel</button>
                        <button t-on-click="() => this.applyCrop()" style="background: #2563eb; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer;">Apply Crop</button>
                    </div>
                </div>
            </div>
        </t>
        
        <!-- Add Cover Modal -->
        <t t-if="state.isCoverModalOpen">
            <div class="km_pro_cover_modal_overlay" t-on-click="() => this.closeCoverModal()"></div>
            <div class="km_pro_cover_modal">
                <div class="km_pro_cover_modal_header">
                    <h3>Choose a nice cover</h3>
                    <button class="km_pro_cover_modal_close" t-on-click="() => this.closeCoverModal()"><i class="fa fa-times"></i></button>
                </div>
                
                <div class="km_pro_cover_modal_tabs">
                    <div class="km_pro_unsplash_search">
                        <input type="text" placeholder="Search Unsplash..." t-model="state.unsplashQuery" t-on-keydown="(ev) => ev.key === 'Enter' and this.searchUnsplash()"/>
                        <i class="fa fa-search" style="cursor: pointer;" t-on-click="() => this.searchUnsplash()"></i>
                    </div>
                    <div class="km_pro_cover_actions">
                        <t t-if="state.coverModalTab === 'url'">
                            <div class="km_pro_url_input_wrapper" style="margin-bottom: 0;">
                                <input type="text" placeholder="https://example.com/image.jpg" t-model="state.coverUrl"/>
                                <button t-on-click="() => this.applyUrlCover(state.coverUrl)">Apply</button>
                            </div>
                        </t>
                        <t t-else="">
                            <button class="km_pro_cover_action_btn" t-on-click="() => this.setCoverTab('url')">
                                <i class="fa fa-link" style="color:#d44ca0;"></i> Add URL
                            </button>
                        </t>
                        <button class="km_pro_cover_action_btn" t-on-click="() => this.onUploadBtnClick()">
                            Upload an image
                        </button>
                    </div>
                </div>

                <div class="km_pro_cover_modal_body">
                    <t t-if="state.isUnsplashLoading or state.isCoverDownloading">
                        <div class="km_pro_cover_loading">
                            <i class="fa fa-circle-o-notch fa-spin fa-2x"></i>
                            <div style="margin-top: 10px;">Loading...</div>
                        </div>
                    </t>
                    <t t-else="">
                        <t t-if="state.unsplashImages and state.unsplashImages.length > 0">
                            <div class="km_pro_unsplash_grid">
                                <t t-foreach="state.unsplashImages" t-as="img" t-key="img.id">
                                    <img class="km_pro_unsplash_img" t-att-src="img.urls.small" t-on-click="() => this.applyUrlCover(img.urls.regular)"/>
                                </t>
                            </div>
                        </t>
                        <t t-else="">
                            <div class="km_pro_empty_cover_state">
                                <i class="fa fa-folder-open"></i>
                                <h4>No images found.</h4>
                                <p>Wow, it feels a bit empty in here. Upload from the button in the top right corner!</p>
                            </div>
                        </t>
                    </t>
                </div>
            </div>
        </t>
    </div>
`;

export class KnowledgeEmojiPicker extends Component {
    

    setup() {
        this.emojis = ['😀', '😃', '😄', '😁', '😆', '😅', '🤣', '😂', '🙂', '🙃', '😉', '😊', '😇', '🥰', '😍', '🤩', '😘', '😗', '😚', '😋', '😛', '😜', '🤪', '😝', '🤑', '🤗', '🤭', '🤫', '🤔', '🤐', '🤨', '😐', '😑', '😶', '😏', '😒', '🙄', '😬', '🤥', '😌', '😔', '😪', '🤤', '😴', '😷', '🤒', '🤕', '🤢', '🤮', '🤧', '🥵', '🥶', '🥴', '😵', '🤯', '🤠', '🥳', '😎', '🤓', '🧐', '😕', '😟', '🙁', '☹️', '😮', '😯', '😲', '😳', '🥺', '😦', '😧', '😨', '😰', '😥', '😢', '😭', '😱', '😖', '😣', '😞', '😓', '😩', '😫', '🥱', '😤', '😡', '😠', '🤬', '😈', '👿', '💀', '☠️', '💩', '🤡', '👹', '👺', '👻', '👽', '👾', '🤖', '🎃', '😺', '😸', '😹', '😻', '😼', '😽', '🙀', '😿', '😾', '📈', '📊', '📉', '💼', '📝', '✨', '🔥'];
    }
}
KnowledgeEmojiPicker.template = xml`
    <div class="km_pro_emoji_picker shadow" t-on-click="(ev) => ev.stopPropagation()">
        <div class="emoji-picker-search">
            <input type="text" placeholder="Search emojis..." />
            <i class="fa fa-search"></i>
        </div>
        <div class="emoji-picker-body">
            <div class="emoji-category-title">
                <i class="fa fa-smile-o"></i> SMILEYS &amp; EMOTION
            </div>
            <div class="emoji-grid">
                <t t-foreach="this.emojis" t-as="emoji" t-key="emoji_index">
                    <div class="emoji-cell" t-on-click="() => props.onSelect(emoji)">
                        <t t-esc="emoji"/>
                    </div>
                </t>
            </div>
        </div>
        <div class="emoji-picker-footer">
            <div class="footer-icons">
                <i class="fa fa-clock-o"></i>
                <i class="fa fa-smile-o active"></i>
                <i class="fa fa-paw"></i>
                <i class="fa fa-cutlery"></i>
                <i class="fa fa-futbol-o"></i>
                <i class="fa fa-car"></i>
                <i class="fa fa-lightbulb-o"></i>
                <i class="fa fa-hashtag"></i>
            </div>
            <div class="footer-close" t-on-click="props.onRemove">
                <i class="fa fa-times"></i>
            </div>
        </div>
    </div>
`;

KnowledgeManagementEditor.components = { Chatter, KnowledgeEmojiPicker, KnowledgeKanbanBoard, KnowledgeCalendarBoard, KnowledgeListMockup };
