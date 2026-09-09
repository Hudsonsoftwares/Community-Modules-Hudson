/** @odoo-module **/

import { Component, xml, useState, useEffect } from "@odoo/owl";

export class KnowledgeSidebarArticle extends Component {
    static props = {
        article: Object,
        section: { type: String, optional: true },
        depth: { type: Number, optional: true },
        activeArticleId: { type: Number, optional: true },
        setActiveArticle: Function,
        createNewArticle: Function,
        openInNewTab: { type: Function, optional: true },
        toggleFavorite: { type: Function, optional: true },
        renameArticle: { type: Function, optional: true },
        duplicateArticle: { type: Function, optional: true },
        deleteArticle: { type: Function, optional: true },
        shareArticle: { type: Function, optional: true },
        moveArticle: { type: Function, optional: true },
        onDropArticle: { type: Function, optional: true },
        activeMenuId: { type: [Number, String], optional: true },
        toggleMenu: Function,
        expandedArticleIds: Object,
        toggleExpand: Function
    };

    setup() {
        // Local state removed, using props.expandedArticleIds instead
    }

    stripHtml(html) {
        if (!html) return 'Untitled';
        const tmp = document.createElement("DIV");
        tmp.innerHTML = html;
        return tmp.textContent || tmp.innerText || "Untitled";
    }
    getRelativeTime(dateString) {
        if (!dateString) return 'recently';
        const diff = Date.now() - new Date(dateString).getTime();
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));
        if (days === 0) return 'today';
        if (days === 1) return 'yesterday';
        return `${days} days ago`;
    }
}

KnowledgeSidebarArticle.template = xml`
    <li t-att-class="{'km_pro_sidebar_active': props.activeArticleId === props.article.id}"
        t-on-click="() => props.setActiveArticle(props.article.id)"
        draggable="true"
        t-on-dragstart="(ev) => { ev.dataTransfer.setData('article_id', props.article.id); ev.dataTransfer.setData('article_name', props.article.name); }"
        t-on-dragover.prevent="() => {}"
        t-on-drop="(ev) => { ev.stopPropagation(); props.onDropArticle and props.onDropArticle(ev, props.article.id); }">
        
        <span t-if="props.article.children and props.article.children.length > 0" 
              class="km_pro_article_caret" 
              t-on-click="(ev) => { ev.stopPropagation(); props.toggleExpand(props.article.id); }">
            <i t-attf-class="fa #{props.expandedArticleIds.has(props.article.id) ? 'fa-caret-down' : 'fa-caret-right'}"></i>
        </span>
        <span t-else="" class="km_pro_article_caret_placeholder"></span>
        
        <span class="km_pro_article_icon">
            <t t-if="props.article.icon" t-esc="props.article.icon"/>
            <t t-else="">📄</t>
        </span>
        <span t-esc="this.stripHtml(props.article.name || 'Untitled')" style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"></span>
        
        <t t-if="props.article.is_locked">
            <i class="fa fa-lock" style="color: var(--km-text-muted); margin-right: 8px; font-size: 0.9em;" title="Locked"></i>
        </t>
        
        <div class="km_pro_article_menu_wrapper">
            <button class="km_pro_article_add_btn" t-on-click="(ev) => { ev.stopPropagation(); props.createNewArticle(props.article.id); }">
                <i class="fa fa-plus"></i>
            </button>
            <button class="km_pro_article_menu_btn" t-att-class="{'active': props.activeMenuId === ((props.section || 'default') + '_' + props.article.id)}" t-on-click="(ev) => props.toggleMenu(ev, (props.section || 'default') + '_' + props.article.id, props.article)">
                <i class="fa fa-ellipsis-v"></i>
            </button>
        </div>
    </li>
    <ul t-if="props.expandedArticleIds.has(props.article.id) and props.article.children and props.article.children.length > 0" class="km_pro_article_children">
        <t t-foreach="props.article.children || []" t-as="child" t-key="child.id">
            <KnowledgeSidebarArticle 
                article="child" 
                section="props.section"
                depth="(props.depth || 0) + 1"
                activeArticleId="props.activeArticleId"
                setActiveArticle="props.setActiveArticle"
                createNewArticle="props.createNewArticle"
                openInNewTab="props.openInNewTab"
                toggleFavorite="props.toggleFavorite"
                renameArticle="props.renameArticle"
                duplicateArticle="props.duplicateArticle"
                deleteArticle="props.deleteArticle"
                shareArticle="props.shareArticle"
                moveArticle="props.moveArticle"
                onDropArticle="props.onDropArticle"
                activeMenuId="props.activeMenuId"
                toggleMenu="props.toggleMenu"
                expandedArticleIds="props.expandedArticleIds"
                toggleExpand="props.toggleExpand"
            />
        </t>
    </ul>
`;
KnowledgeSidebarArticle.components = { KnowledgeSidebarArticle };

export class KnowledgeManagementSidebar extends Component {
    static props = {
        favoriteArticles: Array,
        workspaceArticles: Array,
        privateArticles: Array,
        activeArticleId: { type: Number, optional: true },
        createNewArticle: Function,
        setActiveArticle: Function,
        isCreating: Boolean,
        openInNewTab: { type: Function, optional: true },
        toggleFavorite: { type: Function, optional: true },
        renameArticle: { type: Function, optional: true },
        duplicateArticle: { type: Function, optional: true },
        deleteArticle: { type: Function, optional: true },
        shareArticle: { type: Function, optional: true },
        moveArticle: { type: Function, optional: true },
        onDropSection: { type: Function, optional: true },
        onDropArticle: { type: Function, optional: true },
        openSearchModal: { type: Function, optional: true },
        openTemplatesModal: { type: Function, optional: true },
        openTrashModal: { type: Function, optional: true },
        expandedArticleIds: Object,
        toggleExpand: Function
    };

    setup() {
        this.state = useState({
            activeMenuId: null,
            menuArticle: null,
            menuPosition: { top: 0, left: 0 }
        });

        const closeMenu = (ev) => {
            if (!ev.target.closest('.km_pro_dropdown_menu') && !ev.target.closest('.km_pro_article_menu_btn')) {
                this.closeMenu();
            }
        };

        const handleScrollOrResize = () => {
            if (this.state.activeMenuId) {
                this.closeMenu();
            }
        };

        useEffect(() => {
            document.addEventListener("click", closeMenu);
            window.addEventListener("scroll", handleScrollOrResize, true);
            window.addEventListener("resize", handleScrollOrResize);
            return () => {
                document.removeEventListener("click", closeMenu);
                window.removeEventListener("scroll", handleScrollOrResize, true);
                window.removeEventListener("resize", handleScrollOrResize);
            };
        });
    }

    closeMenu() {
        this.state.activeMenuId = null;
        this.state.menuArticle = null;
    }

    handleMenuAction(actionName) {
        if (!this.state.menuArticle) return;
        
        // Capture the article reference synchronously before closing menu
        // We do a shallow copy to prevent reference mutation issues
        const article = { ...this.state.menuArticle }; 
        const id = article.id;
        
        this.closeMenu();
        
        if (actionName === 'openInNewTab') this.props.openInNewTab(id);
        else if (actionName === 'createNewArticle') this.props.createNewArticle(id);
        else if (actionName === 'toggleFavorite') this.props.toggleFavorite(article);
        else if (actionName === 'shareArticle') this.props.shareArticle(id);
        else if (actionName === 'renameArticle') this.props.renameArticle(article);
        else if (actionName === 'moveArticle') this.props.moveArticle(id);
        else if (actionName === 'duplicateArticle') this.props.duplicateArticle(id);
        else if (actionName === 'trashArticle') this.props.deleteArticle(id);
    }

    toggleMenu(ev, menuId, article = null) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        if (this.state.activeMenuId === menuId) {
            this.closeMenu();
            return;
        }
        this.state.activeMenuId = menuId;
        this.state.menuArticle = article;
        if (ev && ev.currentTarget) {
            const rect = ev.currentTarget.getBoundingClientRect();
            const viewportHeight = window.innerHeight;
            const viewportWidth = window.innerWidth;
            const menuWidth = 240;
            const estimatedMenuHeight = 420;

            // Preferred: open to the right outside sidebar
            let left = rect.right + 6;
            if (left + menuWidth > viewportWidth - 10) {
                left = Math.max(10, rect.left - menuWidth);
            }

            // Check if trigger is in bottom half of screen or would overflow downwards
            const spaceBelow = viewportHeight - rect.bottom;
            const isBottomHalf = (spaceBelow < estimatedMenuHeight) || (rect.top > (viewportHeight * 0.42));

            if (isBottomHalf) {
                // Anchor to bottom! Grows upwards so it CANNOT hang off the bottom of the screen
                const bottomSpace = Math.max(14, viewportHeight - rect.bottom);
                const maxHeight = Math.min(420, viewportHeight - bottomSpace - 16);
                this.state.menuPosition = {
                    top: 'auto',
                    bottom: `${bottomSpace}px`,
                    left: `${left}px`,
                    maxHeight: `${maxHeight}px`
                };
            } else {
                // Anchor to top! Grows downwards, clamped strictly above bottom
                const topSpace = Math.max(14, rect.top);
                const maxHeight = Math.min(420, viewportHeight - topSpace - 16);
                this.state.menuPosition = {
                    top: `${topSpace}px`,
                    bottom: 'auto',
                    left: `${left}px`,
                    maxHeight: `${maxHeight}px`
                };
            }
        }
    }

    getRelativeTime(dateString) {
        if (!dateString) return 'recently';
        const diff = Date.now() - new Date(dateString).getTime();
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));
        if (days === 0) return 'today';
        if (days === 1) return 'yesterday';
        return `${days} days ago`;
    }
}
KnowledgeManagementSidebar.template = xml`
    <div class="km_pro_sidebar">
        <div class="km_pro_sidebar_header">
            <button 
                class="km_pro_new_article_btn" 
                t-on-click="() => props.createNewArticle(null)"
                t-att-disabled="props.isCreating">
                <i class="fa fa-plus"></i>
                <t t-if="props.isCreating">Creating...</t>
                <t t-else="">New Article</t>
            </button>
            <i class="fa fa-search km_pro_search_trigger" t-on-click="props.openSearchModal"></i>
        </div>
        
        <div class="km_pro_sidebar_scrollable" style="flex: 1; overflow-y: auto;">
            <div class="km_pro_sidebar_section" 
                 t-on-dragover="(ev) => ev.preventDefault()" 
                 t-on-drop="(ev) => props.onDropSection(ev, 'favorites')">
                <h3>Favorites</h3>
                <ul class="km_pro_article_list">
                    <t t-foreach="props.favoriteArticles || []" t-as="article" t-key="article.id">
                        <KnowledgeSidebarArticle 
                            article="article"
                            section="'favorites'"
                            depth="0"
                            activeArticleId="props.activeArticleId"
                            setActiveArticle="props.setActiveArticle"
                            createNewArticle="props.createNewArticle"
                            openInNewTab="props.openInNewTab"
                            toggleFavorite="props.toggleFavorite"
                            renameArticle="props.renameArticle"
                            duplicateArticle="props.duplicateArticle"
                            deleteArticle="props.deleteArticle"
                            shareArticle="props.shareArticle"
                            moveArticle="props.moveArticle"
                            onDropArticle="props.onDropArticle"
                            activeMenuId="state.activeMenuId"
                            toggleMenu="(ev, id, article) => this.toggleMenu(ev, id, article)"
                            expandedArticleIds="props.expandedArticleIds"
                            toggleExpand="props.toggleExpand"
                        />
                    </t>
                </ul>
            </div>

            <div class="km_pro_sidebar_section"
                 t-on-dragover="(ev) => ev.preventDefault()" 
                 t-on-drop="(ev) => props.onDropSection(ev, 'workspace')">
                <h3>Workspace</h3>
                <ul class="km_pro_article_list">
                    <t t-foreach="props.workspaceArticles || []" t-as="article" t-key="article.id">
                        <KnowledgeSidebarArticle 
                            article="article"
                            section="'workspace'"
                            depth="0"
                            activeArticleId="props.activeArticleId"
                            setActiveArticle="props.setActiveArticle"
                            createNewArticle="props.createNewArticle"
                            openInNewTab="props.openInNewTab"
                            toggleFavorite="props.toggleFavorite"
                            renameArticle="props.renameArticle"
                            duplicateArticle="props.duplicateArticle"
                            deleteArticle="props.deleteArticle"
                            shareArticle="props.shareArticle"
                            moveArticle="props.moveArticle"
                            onDropArticle="props.onDropArticle"
                            activeMenuId="state.activeMenuId"
                            toggleMenu="(ev, id, article) => this.toggleMenu(ev, id, article)"
                            expandedArticleIds="props.expandedArticleIds"
                            toggleExpand="props.toggleExpand"
                        />
                    </t>
                </ul>
            </div>
            
            <div class="km_pro_sidebar_section"
                 t-on-dragover="(ev) => ev.preventDefault()" 
                 t-on-drop="(ev) => props.onDropSection(ev, 'private')">
                <h3>Private</h3>
                <ul class="km_pro_article_list">
                    <t t-foreach="props.privateArticles || []" t-as="article" t-key="article.id">
                        <KnowledgeSidebarArticle 
                            article="article"
                            section="'private'"
                            depth="0"
                            activeArticleId="props.activeArticleId"
                            setActiveArticle="props.setActiveArticle"
                            createNewArticle="props.createNewArticle"
                            openInNewTab="props.openInNewTab"
                            toggleFavorite="props.toggleFavorite"
                            renameArticle="props.renameArticle"
                            duplicateArticle="props.duplicateArticle"
                            deleteArticle="props.deleteArticle"
                            shareArticle="props.shareArticle"
                            moveArticle="props.moveArticle"
                            onDropArticle="props.onDropArticle"
                            activeMenuId="state.activeMenuId"
                            toggleMenu="(ev, id, article) => this.toggleMenu(ev, id, article)"
                            expandedArticleIds="props.expandedArticleIds"
                            toggleExpand="props.toggleExpand"
                        />
                    </t>
                    <t t-if="!props.privateArticles || props.privateArticles.length === 0">
                        <li class="km_pro_empty_hint">No articles yet</li>
                    </t>
                </ul>
            </div>
        </div>
        
        <div class="km_pro_sidebar_bottom">
            <div t-on-click="props.openTrashModal" class="km_pro_sidebar_bottom_item">
                <i class="fa fa-trash"></i> Open Trash
            </div>
            <div t-on-click="props.openTemplatesModal" class="km_pro_sidebar_bottom_item">
                <i class="fa fa-paint-brush"></i> Browse Templates
            </div>
        </div>

        <!-- Floating Dropdown Menu (fixed position outside scrollable sidebar) -->
        <t t-if="state.activeMenuId and state.menuArticle">
            <div class="km_pro_dropdown_menu km_pro_floating_dropdown" 
                 t-attf-style="position: fixed !important; top: {{state.menuPosition.top}} !important; bottom: {{state.menuPosition.bottom}} !important; left: {{state.menuPosition.left}} !important; max-height: {{state.menuPosition.maxHeight}} !important; z-index: 99999 !important; width: 240px !important; overflow-y: auto !important; box-sizing: border-box !important;"
                 t-on-click="(ev) => ev.stopPropagation()">
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('openInNewTab')">
                    <i class="fa fa-external-link"></i> Open in new tab
                </div>
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('createNewArticle')">
                    <i class="fa fa-level-down"></i> New Child Article
                </div>
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('toggleFavorite')">
                    <i class="fa fa-star"></i> 
                    <t t-if="state.menuArticle.is_favorite">Remove from Favorite</t>
                    <t t-else="">Add to Favorite</t>
                </div>
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('shareArticle')">
                    <i class="fa fa-share"></i> Share
                </div>
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('renameArticle')">
                    <i class="fa fa-pencil"></i> Rename
                </div>
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('moveArticle')">
                    <i class="fa fa-angle-double-right"></i> Move To
                </div>
                <div class="km_pro_dropdown_item" t-on-click="() => this.handleMenuAction('duplicateArticle')">
                    <i class="fa fa-clone"></i> Create a Copy
                </div>
                <div class="km_pro_dropdown_item" style="color: #dc3545;" t-on-click="() => this.handleMenuAction('trashArticle')">
                    <i class="fa fa-trash"></i> Send to Trash
                </div>
                
                <div class="km_pro_dropdown_divider"></div>
                
                <div class="km_pro_dropdown_footer">
                    <div>Last Edited · <t t-esc="this.getRelativeTime(state.menuArticle?.write_date)"/></div>
                    <div class="footer-user">
                        <img t-attf-src="/web/image?model=res.users&amp;field=avatar_128&amp;id={{state.menuArticle?.write_uid ? state.menuArticle?.write_uid[0] : 2}}" alt="Avatar"/>
                        <span t-esc="state.menuArticle?.write_uid ? state.menuArticle?.write_uid[1] : 'Spiderman'"/>
                    </div>
                </div>
            </div>
        </t>
    </div>
`;
KnowledgeManagementSidebar.components = { KnowledgeSidebarArticle };
