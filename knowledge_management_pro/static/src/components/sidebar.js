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
        activeMenuId: { type: [Number, String], optional: true },
        toggleMenu: Function
    };

    setup() {
        this.state = useState({
            isExpanded: true
        });
    }

    toggleExpand(ev) {
        ev.stopPropagation();
        this.state.isExpanded = !this.state.isExpanded;
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
        t-on-dragstart="(ev) => { ev.dataTransfer.setData('article_id', props.article.id); ev.dataTransfer.setData('article_name', props.article.name); }">
        
        <span t-if="props.article.children and props.article.children.length > 0" 
              class="km_pro_article_caret" 
              t-on-click="toggleExpand">
            <i t-attf-class="fa #{state.isExpanded ? 'fa-caret-down' : 'fa-caret-right'}"></i>
        </span>
        <span t-else="" class="km_pro_article_caret_placeholder"></span>
        
        <span class="km_pro_article_icon">📄</span>
        <span t-esc="props.article.name || 'Untitled'" style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"></span>
        
        <div class="km_pro_article_menu_wrapper">
            <button class="km_pro_article_add_btn" t-on-click="(ev) => { ev.stopPropagation(); props.createNewArticle(props.article.id); }">
                <i class="fa fa-plus"></i>
            </button>
            <button class="km_pro_article_menu_btn" t-att-class="{'active': props.activeMenuId === ((props.section || 'default') + '_' + props.article.id)}" t-on-click="(ev) => props.toggleMenu(ev, (props.section || 'default') + '_' + props.article.id)">
                <i class="fa fa-ellipsis-v"></i>
            </button>
            
            <t t-if="props.activeMenuId === ((props.section || 'default') + '_' + props.article.id)">
                <div class="km_pro_dropdown_menu" t-on-click="(ev) => ev.stopPropagation()">
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.openInNewTab(props.article.id); }">
                        <i class="fa fa-external-link"></i> Open in new tab
                    </div>
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.toggleFavorite(props.article); }">
                        <i class="fa fa-star"></i> 
                        <t t-if="props.article.favorite_user_ids and props.article.favorite_user_ids.includes(env.session ? env.session.uid : 2)">Remove from Favorite</t>
                        <t t-else="">Add to Favorite</t>
                    </div>
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.shareArticle(props.article.id); }">
                        <i class="fa fa-share"></i> Share
                    </div>
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.renameArticle(props.article); }">
                        <i class="fa fa-pencil"></i> Rename
                    </div>
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.moveArticle(props.article.id); }">
                        <i class="fa fa-angle-double-right"></i> Move To
                    </div>
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.duplicateArticle(props.article.id); }">
                        <i class="fa fa-clone"></i> Create a Copy
                    </div>
                    <div class="km_pro_dropdown_item" t-on-click="() => { props.toggleMenu(null, null); props.deleteArticle(props.article.id); }">
                        <i class="fa fa-trash"></i> Send to Trash
                    </div>
                    
                    <div class="km_pro_dropdown_divider"></div>
                    
                    <div class="km_pro_dropdown_footer">
                        <div>Last Edited · <t t-esc="getRelativeTime(props.article.write_date)"/></div>
                        <div class="footer-user">
                            <img t-attf-src="/web/image?model=res.users&amp;field=avatar_128&amp;id={{props.article.write_uid ? props.article.write_uid[0] : 2}}" alt="Avatar"/>
                            <span t-esc="props.article.write_uid ? props.article.write_uid[1] : 'Spiderman'"/>
                        </div>
                    </div>
                </div>
            </t>
        </div>
    </li>
    <ul t-if="state.isExpanded and props.article.children and props.article.children.length > 0" class="km_pro_article_children">
        <t t-foreach="props.article.children" t-as="child" t-key="child.id">
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
                activeMenuId="props.activeMenuId"
                toggleMenu="props.toggleMenu"
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
        openSearchModal: { type: Function, optional: true },
        openTemplatesModal: { type: Function, optional: true },
        openTrashModal: { type: Function, optional: true }
    };

    setup() {
        this.state = useState({
            activeMenuId: null
        });

        const closeMenu = (ev) => {
            if (!ev.target.closest('.km_pro_article_menu_wrapper')) {
                this.state.activeMenuId = null;
            }
        };

        useEffect(() => {
            document.addEventListener("click", closeMenu);
            return () => document.removeEventListener("click", closeMenu);
        });
    }

    toggleMenu(ev, menuId) {
        if (ev) ev.stopPropagation();
        this.state.activeMenuId = this.state.activeMenuId === menuId ? null : menuId;
    }

}
KnowledgeManagementSidebar.template = xml`
    <div class="km_pro_sidebar">
        <div class="km_pro_sidebar_header">
            <button 
                class="km_pro_new_article_btn" 
                t-on-click="() => props.createNewArticle()"
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
                    <t t-foreach="props.favoriteArticles" t-as="article" t-key="article.id">
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
                            activeMenuId="state.activeMenuId"
                            toggleMenu="(ev, id) => this.toggleMenu(ev, id)"
                        />
                    </t>
                </ul>
            </div>

            <div class="km_pro_sidebar_section"
                 t-on-dragover="(ev) => ev.preventDefault()" 
                 t-on-drop="(ev) => props.onDropSection(ev, 'workspace')">
                <h3>Workspace</h3>
                <ul class="km_pro_article_list">
                    <t t-foreach="props.workspaceArticles" t-as="article" t-key="article.id">
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
                            activeMenuId="state.activeMenuId"
                            toggleMenu="(ev, id) => this.toggleMenu(ev, id)"
                        />
                    </t>
                </ul>
            </div>
            
            <div class="km_pro_sidebar_section"
                 t-on-dragover="(ev) => ev.preventDefault()" 
                 t-on-drop="(ev) => props.onDropSection(ev, 'private')">
                <h3>Private</h3>
                <ul class="km_pro_article_list">
                    <t t-foreach="props.privateArticles" t-as="article" t-key="article.id">
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
                            activeMenuId="state.activeMenuId"
                            toggleMenu="(ev, id) => this.toggleMenu(ev, id)"
                        />
                    </t>
                    <t t-if="props.privateArticles.length === 0">
                        <li class="km_pro_empty_hint">No articles yet</li>
                    </t>
                </ul>
            </div>
        </div>
        
        <div class="km_pro_sidebar_bottom" style="padding: 15px 20px; border-top: 1px solid #36363a; color: #a0a0a0; font-size: 0.95rem;">
            <div t-on-click="props.openTemplatesModal" style="cursor: pointer; padding: 6px 0; display: flex; align-items: center; gap: 8px;">
                <i class="fa fa-paint-brush"></i> Browse Templates
            </div>
            <div t-on-click="props.openTrashModal" style="cursor: pointer; padding: 6px 0; display: flex; align-items: center; gap: 8px; margin-top: 4px;">
                <i class="fa fa-trash"></i> Open Trash
            </div>
        </div>
    </div>
`;
KnowledgeManagementSidebar.components = { KnowledgeSidebarArticle };
