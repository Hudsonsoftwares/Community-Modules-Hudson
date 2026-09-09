/** @odoo-module **/

import { Component, xml, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { KnowledgeManagementSidebar } from "./sidebar";
import { KnowledgeManagementEditor } from "./editor";

export function getOdooColorScheme() {
    const doc = document.documentElement;
    const body = document.body;
    
    // 1. Check explicit data attributes on html/body (Bootstrap 5.3 & Odoo 17/18/19)
    const bsTheme = doc.getAttribute("data-bs-theme") || (body && body.getAttribute("data-bs-theme"));
    if (bsTheme === "light") return "light";
    if (bsTheme === "dark") return "dark";
    
    const colorScheme = doc.getAttribute("data-color-scheme") || (body && body.getAttribute("data-color-scheme"));
    if (colorScheme === "light") return "light";
    if (colorScheme === "dark") return "dark";
    
    // 2. Check class o_dark_mode on html or body
    if (doc.classList.contains("o_dark_mode") || (body && body.classList.contains("o_dark_mode"))) {
        return "dark";
    }
    
    // 3. Check cookie or localStorage
    try {
        const match = document.cookie && document.cookie.match(/(?:^|;\s*)color_scheme=([^;]+)/);
        if (match && (match[1] === "dark" || match[1] === "light")) {
            return match[1];
        }
        const lsScheme = localStorage.getItem("color_scheme");
        if (lsScheme === "dark" || lsScheme === "light") {
            return lsScheme;
        }
    } catch (e) {}
    
    // 4. Fall back to system preference
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
        return "dark";
    }
    
    return "light";
}

export class KnowledgeManagementApp extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({
            colorScheme: getOdooColorScheme(),
            activeArticleId: null,
            favoriteArticles: [],
            workspaceArticles: [],
            privateArticles: [],
            isCreating: false,
            showMoveConfirmation: false,
            pendingMoveArticleId: null,
            pendingMoveArticleName: "",
            allArticlesMap: {},
            allArticlesList: [],
            isSearchModalOpen: false,
            searchQuery: "",
            isMoveModalOpen: false,
            moveSearchQuery: "",
            articleToMove: null,
            isTemplatesModalOpen: false,
            templates: [],
            isTrashModalOpen: false,
            trashArticles: [],
            expandedArticleIds: new Set()
        });

        const updateTheme = () => {
            const current = getOdooColorScheme();
            if (this.state.colorScheme !== current) {
                this.state.colorScheme = current;
            }
        };

        // MutationObserver for dynamic preference changes without page reload
        let observer = null;
        if (typeof MutationObserver !== "undefined") {
            observer = new MutationObserver(() => updateTheme());
            observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme", "data-color-scheme", "class"] });
            if (document.body) {
                observer.observe(document.body, { attributes: true, attributeFilter: ["data-bs-theme", "data-color-scheme", "class"] });
            }
        }

        const mediaQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
        if (mediaQuery) {
            mediaQuery.addEventListener("change", updateTheme);
        }

        onWillStart(async () => {
            await this.loadArticles();
        });

        onWillUnmount(() => {
            if (observer) observer.disconnect();
            if (mediaQuery) mediaQuery.removeEventListener("change", updateTheme);
        });
    }

    stripHtml(html) {
        if (!html) return 'Untitled';
        const tmp = document.createElement("DIV");
        tmp.innerHTML = html;
        return tmp.textContent || tmp.innerText || "Untitled";
    }

    toggleExpand(id) {
        if (this.state.expandedArticleIds.has(id)) {
            this.state.expandedArticleIds.delete(id);
        } else {
            this.state.expandedArticleIds.add(id);
        }
    }

    async loadArticles() {
        const result = await this.orm.searchRead(
            "knowledge.management.article",
            [["state", "!=", "archived"]],
            ["id", "name", "write_date", "write_uid", "is_favorite", "favorite_user_ids", "parent_id", "is_private", "icon", "sequence", "is_locked", "in_trash"]
        );
        // Build tree
        const articleMap = {};
        const rootArticles = [];
        
        result.forEach(a => { articleMap[a.id] = { ...a, children: [] }; });
        
        result.forEach(a => {
            if (a.parent_id && articleMap[a.parent_id[0]]) {
                articleMap[a.parent_id[0]].children.unshift(articleMap[a.id]);
            } else {
                rootArticles.unshift(articleMap[a.id]);
            }
        });
        
        const favoriteArticles = [];
        const workspaceArticles = [];
        const privateArticles = [];
        
        rootArticles.forEach(a => {
            const isFavorite = a.is_favorite;
            if (isFavorite) {
                favoriteArticles.push(a);
            }
            if (a.is_private) {
                privateArticles.push(a);
            } else {
                workspaceArticles.push(a);
            }
        });
        
        this.state.favoriteArticles = favoriteArticles;
        this.state.workspaceArticles = workspaceArticles;
        this.state.privateArticles = privateArticles;
        this.state.allArticlesMap = articleMap;
        this.state.allArticlesList = result;
    }

    // --- Search Handlers ---
    get filteredSearchArticles() {
        const list = this.state.allArticlesList || [];
        if (!this.state.searchQuery || !this.state.searchQuery.trim()) {
            return list;
        }
        const query = this.state.searchQuery.toLowerCase();
        return list.filter(a => (a.name || 'Untitled').toLowerCase().includes(query));
    }

    get filteredArticles() {
        return this.filteredSearchArticles;
    }

    get filteredMoveTargets() {
        let targets = this.state.allArticlesList || [];
        // Don't allow moving an article into itself or its own children (we skip complex cycle detection for mockup)
        if (this.state.articleToMove) {
            targets = targets.filter(a => a.id !== this.state.articleToMove.id);
        }
        
        if (this.state.moveSearchQuery && this.state.moveSearchQuery.trim()) {
            const query = this.state.moveSearchQuery.toLowerCase();
            targets = targets.filter(a => (a.name || 'Untitled').toLowerCase().includes(query));
        }
        return targets || [];
    }

    openSearchModal() {
        this.state.searchQuery = "";
        this.state.isSearchModalOpen = true;
    }

    closeSearchModal() {
        this.state.isSearchModalOpen = false;
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
    }

    selectSearchResult(ev, id, newTab = false) {
        if (ev && ev.ctrlKey) newTab = true;
        this.closeSearchModal();
        if (newTab) {
            this.openInNewTab(id);
        } else {
            this.setActiveArticle(id);
        }
    }

    // --- Sidebar Article Actions ---
    openInNewTab(id) {
        window.open(window.location.href + '&active_id=' + id, '_blank');
    }

    async toggleFavorite(article) {
        await this.orm.call("knowledge.management.article", "action_toggle_favorite", [[article.id]]);
        await this.loadArticles();
    }

    async toggleFavoriteById(id) {
        if (!id) return;
        const article = this.state.allArticlesMap[id];
        if (article) {
            await this.toggleFavorite(article);
        }
    }

    async renameArticle(article) {
        const newName = window.prompt("Rename Article", article.name);
        if (newName && newName.trim() !== "" && newName !== article.name) {
            await this.orm.write("knowledge.management.article", [article.id], {
                name: newName.trim()
            });
            await this.loadArticles();
        }
    }

    onTitleChange(newTitle) {
        if (this.state.activeArticleId && this.state.allArticlesMap[this.state.activeArticleId]) {
            this.state.allArticlesMap[this.state.activeArticleId].name = newTitle;
            const articleInList = this.state.allArticlesList.find(a => a.id === this.state.activeArticleId);
            if (articleInList) {
                articleInList.name = newTitle;
            }
        }
    }

    async duplicateArticle(id) {
        await this.orm.call("knowledge.management.article", "action_duplicate", [[id]]);
        await this.loadArticles();
    }

    async deleteArticle(id) {
        await this.orm.call("knowledge.management.article", "action_move_to_trash", [[id]]);
        if (this.state.activeArticleId === id) {
            this.state.activeArticleId = null;
        }
        await this.loadArticles();
    }

    shareArticle(id) {
        window.alert("Share dialog placeholder. This would open the standard share dialog.");
    }

    moveArticle(id) {
        if (!id) return;
        this.state.articleToMove = this.state.allArticlesMap[id];
        this.state.moveSearchQuery = "";
        this.state.isMoveModalOpen = true;
    }

    closeMoveModal() {
        this.state.isMoveModalOpen = false;
        this.state.articleToMove = null;
    }

    onMoveSearchInput(ev) {
        this.state.moveSearchQuery = ev.target.value;
    }

    async confirmMove(targetType, targetId = null) {
        if (!this.state.articleToMove) return;
        const articleId = this.state.articleToMove.id;
        
        const vals = {};
        if (targetType === 'private') {
            vals.parent_id = false;
            vals.is_private = true;
        } else if (targetType === 'workspace') {
            vals.parent_id = false;
            vals.is_private = false;
        } else if (targetType === 'article') {
            vals.parent_id = targetId;
            const targetArticle = this.state.allArticlesMap[targetId];
            if (targetArticle) {
                vals.is_private = targetArticle.is_private;
            }
        }
        
        try {
            await this.orm.write("knowledge.management.article", [articleId], vals);
            this.closeMoveModal();
            await this.loadArticles();
        } catch (error) {
            console.error("Failed to move article", error);
        }
    }

    // --- Trash Modal Handlers ---
    async openTrashModal() {
        this.state.isTrashModalOpen = true;
        try {
            const trash = await this.orm.searchRead(
                "knowledge.management.article",
                [["in_trash", "=", true]],
                ["id", "name", "write_date", "icon"],
                { context: { active_test: false } }
            );
            this.state.trashArticles = trash;
        } catch (e) {
            console.error("Failed to load trash", e);
        }
    }
    
    closeTrashModal() {
        this.state.isTrashModalOpen = false;
    }
    
    async restoreFromTrash(id) {
        try {
            await this.orm.call("knowledge.management.article", "action_restore_from_trash", [[id]], { context: { active_test: false } });
            this.state.trashArticles = this.state.trashArticles.filter(a => a.id !== id);
            await this.loadArticles();
        } catch (e) {
            console.error("Failed to restore", e);
        }
    }

    async permanentDeleteArticle(id) {
        if (window.confirm("Are you sure you want to permanently delete this article? This cannot be undone.")) {
            try {
                await this.orm.call("knowledge.management.article", "action_permanent_delete", [[id]], { context: { active_test: false } });
                this.state.trashArticles = this.state.trashArticles.filter(a => a.id !== id);
            } catch (e) {
                console.error("Failed to delete", e);
            }
        }
    }

    async toggleLock(id) {
        if (!id) return;
        await this.orm.call("knowledge.management.article", "action_toggle_lock", [[id]]);
        await this.loadArticles();
    }

    // --- Templates Modal Handlers ---
    async openTemplatesModal() {
        this.state.isTemplatesModalOpen = true;
        try {
            const templates = await this.orm.searchRead(
                "knowledge.management.template",
                [],
                ["id", "name", "description", "content", "icon", "cover_image", "cover_position"]
            );
            this.state.templates = templates;
        } catch (e) {
            console.error("Failed to load templates", e);
        }
    }
    
    closeTemplatesModal() {
        this.state.isTemplatesModalOpen = false;
    }
    
    async selectTemplate(template) {
        this.closeTemplatesModal();
        if (this.state.activeArticleId) {
            const activeArticle = this.state.allArticlesMap[this.state.activeArticleId];
            const content = activeArticle && activeArticle.content ? activeArticle.content.trim() : '';
            if (activeArticle && (content === '' || content === '<p><br></p>' || content === '<p></p>' || content === '<br>')) {
                // Load into current empty article
                const updateVals = {
                    content: template.content,
                    name: activeArticle.name && activeArticle.name !== 'Untitled' ? activeArticle.name : template.name
                };
                if (template.icon) updateVals.icon = template.icon;
                if (template.cover_image) {
                    updateVals.cover_image = template.cover_image;
                    updateVals.cover_position = template.cover_position;
                }
                await this.orm.write("knowledge.management.article", [this.state.activeArticleId], updateVals);
                // Force reload of editor component is tricky, so we'll just reload the whole list and reset active
                const currentId = this.state.activeArticleId;
                this.state.activeArticleId = null;
                await this.loadArticles();
                this.setActiveArticle(currentId);
                return;
            }
        }
        
        // Otherwise, create new article from template
        const createVals = {
            name: template.name,
            content: template.content
        };
        if (template.icon) createVals.icon = template.icon;
        if (template.cover_image) {
            createVals.cover_image = template.cover_image;
            createVals.cover_position = template.cover_position;
        }
        const newArticleIds = await this.orm.create("knowledge.management.article", [createVals]);
        await this.loadArticles();
        this.setActiveArticle(newArticleIds[0] || newArticleIds);
    }

    async createNewArticle(parentId = false) {
        if (this.state.isCreating) return;
        this.state.isCreating = true;
        
        try {
            // Smart contextual parent logic
            if (parentId === false && this.state.activeArticleId) {
                parentId = this.state.activeArticleId;
            }

            const vals = {
                name: "Untitled",
                state: "draft",
                is_private: true,
            };
            
            if (parentId && typeof parentId === 'number') {
                vals.parent_id = parentId;
                
                // Inherit privacy
                const parentArticle = this.state.allArticlesMap[parentId];
                if (parentArticle) {
                    vals.is_private = parentArticle.is_private;
                }
                
                // Auto-expand the parent folder
                this.state.expandedArticleIds.add(parentId);
            }
            const articleId = await this.orm.create("knowledge.management.article", [vals]);
            
            this.state.activeArticleId = Array.isArray(articleId) ? articleId[0] : articleId;
            await this.loadArticles();
        } catch (error) {
            console.error("Failed to create article", error);
        } finally {
            this.state.isCreating = false;
        }
    }

    // --- Drag and Drop Handlers ---
    onDropSection(ev, targetSection) {
        ev.preventDefault();
        const articleId = parseInt(ev.dataTransfer.getData("article_id"));
        const articleName = ev.dataTransfer.getData("article_name");
        
        if (!articleId) return;
        const article = this.state.allArticlesMap[articleId];

        if (targetSection === 'favorites') {
            if (article && !article.is_private) {
                // Prevent drag and drop from Workspace to Favorites
                return;
            }
            this.orm.call("knowledge.management.article", "action_toggle_favorite", [[articleId]])
                .then(() => this.loadArticles());
        } else if (targetSection === 'workspace') {
            // Check if it's currently private
            const isPrivate = this.state.privateArticles.some(a => a.id === articleId) || 
                              this.state.favoriteArticles.some(a => a.id === articleId && a.is_private);
            if (isPrivate) {
                this.state.pendingMoveArticleId = articleId;
                this.state.pendingMoveArticleName = articleName || "Untitled";
                this.state.showMoveConfirmation = true;
            }
        } else if (targetSection === 'private') {
            this.orm.write("knowledge.management.article", [articleId], {
                is_private: true
            }).then(() => this.loadArticles());
        }
    }
    
    confirmMoveToWorkspace() {
        if (this.state.pendingMoveArticleId) {
            this.orm.write("knowledge.management.article", [this.state.pendingMoveArticleId], {
                is_private: false
            }).then(() => {
                this.state.showMoveConfirmation = false;
                this.state.pendingMoveArticleId = null;
                this.loadArticles();
            });
        }
    }
    
    cancelMove() {
        this.state.showMoveConfirmation = false;
        this.state.pendingMoveArticleId = null;
    }

    setActiveArticle(id) {
        this.state.activeArticleId = id;
    }

    async onDropArticle(ev, targetId) {
        const articleId = parseInt(ev.dataTransfer.getData("article_id"));
        if (!articleId || articleId === targetId) return;

        try {
            await this.orm.call("knowledge.management.article", "move_article", [articleId, targetId]);
            await this.loadArticles();
        } catch (error) {
            console.error("Failed to move article", error);
            window.alert(error.message || "Cannot move article here.");
        }
    }
}

KnowledgeManagementApp.template = xml`
    <div t-attf-class="km_pro_app {{ state.colorScheme === 'dark' ? 'km_dark_mode' : 'km_light_mode' }}">

        <div class="km_pro_main_container">
            <KnowledgeManagementSidebar 
                favoriteArticles="state.favoriteArticles" 
                workspaceArticles="state.workspaceArticles" 
                privateArticles="state.privateArticles" 
                activeArticleId="state.activeArticleId"
                createNewArticle="(parentId) => this.createNewArticle(parentId)"
                setActiveArticle="(id) => this.setActiveArticle(id)"
                isCreating="state.isCreating"
                openInNewTab="(id) => this.openInNewTab(id)"
                toggleFavorite="(article) => this.toggleFavorite(article)"
                renameArticle="(article) => this.renameArticle(article)"
                duplicateArticle="(id) => this.duplicateArticle(id)"
                deleteArticle="(id) => this.deleteArticle(id)"
                shareArticle="(id) => this.shareArticle(id)"
                moveArticle="(id) => this.moveArticle(id)"
                onDropSection="(ev, targetSection) => this.onDropSection(ev, targetSection)"
                onDropArticle="(ev, id) => this.onDropArticle(ev, id)"
                openSearchModal="() => this.openSearchModal()"
                openTemplatesModal="() => this.openTemplatesModal()"
                openTrashModal="() => this.openTrashModal()"
                expandedArticleIds="state.expandedArticleIds"
                toggleExpand="(id) => this.toggleExpand(id)"
            />
            <KnowledgeManagementEditor 
                activeArticleId="state.activeArticleId"
                article="state.activeArticleId ? state.allArticlesMap[state.activeArticleId] : null"
                isFavorite="state.activeArticleId and state.allArticlesMap[state.activeArticleId] and state.allArticlesMap[state.activeArticleId].is_favorite"
                toggleFavorite="() => this.toggleFavoriteById(state.activeArticleId)"
                duplicateArticle="() => this.duplicateArticle(state.activeArticleId)"
                deleteArticle="() => this.deleteArticle(state.activeArticleId)"
                moveArticle="() => this.moveArticle(state.activeArticleId)"
                toggleLock="() => this.toggleLock(state.activeArticleId)"
                openTemplatesModal="() => this.openTemplatesModal()"
                onTitleChange="(newTitle) => this.onTitleChange(newTitle)"
                createNewArticle="(parentId) => this.createNewArticle(parentId)"
                setActiveArticle="(id) => this.setActiveArticle(id)"
            />
            
            <!-- Confirmation Popup -->
            <t t-if="state.showMoveConfirmation">
                <div class="km_pro_modal_backdrop" t-on-click="() => this.cancelMove()">
                    <div class="km_pro_modal" t-on-click="(ev) => ev.stopPropagation()">
                        <div class="km_pro_modal_header">
                            <h3>Confirmation</h3>
                            <button class="km_pro_modal_close" t-on-click="() => this.cancelMove()"><i class="fa fa-times"></i></button>
                        </div>
                        <div class="km_pro_modal_body">
                            <p>Are you sure you want to move "<t t-esc="state.pendingMoveArticleName"/>" to the Workspace? It will be shared with all internal users.</p>
                        </div>
                        <div class="km_pro_modal_footer">
                            <button class="km_pro_btn_primary" t-on-click="() => this.confirmMoveToWorkspace()">Move to Workspace</button>
                            <button class="km_pro_btn_secondary" t-on-click="() => this.cancelMove()">Discard</button>
                        </div>
                    </div>
                </div>
            </t>

            <!-- Move Modal -->
            <t t-if="state.isMoveModalOpen">
                <div class="km_pro_modal_backdrop" t-on-click="() => this.closeMoveModal()">
                    <div class="km_pro_move_modal shadow" t-on-click="(ev) => ev.stopPropagation()">
                        <div class="move-modal-header">
                            <h3>Move an Article</h3>
                            <button class="modal-close-btn" t-on-click="() => this.closeMoveModal()"><i class="fa fa-times"></i></button>
                        </div>
                        <div class="move-modal-body">
                            <div class="move-search-wrapper">
                                <input type="text" 
                                       class="move-search-input" 
                                       placeholder="Search for an article or category..." 
                                       t-att-value="state.moveSearchQuery" 
                                       t-on-input="(ev) => this.onMoveSearchInput(ev)" 
                                       autofocus="autofocus"/>
                                <i class="fa fa-search"></i>
                            </div>
                            
                            <div class="move-dropdown-list">
                                <div class="move-list-section">
                                    <div class="move-list-header">Categories</div>
                                    <div class="move-list-item" t-on-click="() => this.confirmMove('private')">
                                        <div class="move-cat-icon" style="background-color: #d8576b; color: white;">D</div>
                                        <span>Private</span>
                                    </div>
                                    <div class="move-list-item">
                                        <div class="move-cat-icon"><i class="fa fa-users" style="color: var(--km-text-muted);"></i></div>
                                        <span>Shared</span>
                                    </div>
                                    <div class="move-list-item" t-on-click="() => this.confirmMove('workspace')">
                                        <div class="move-cat-icon"><i class="fa fa-building-o" style="color: var(--km-text-muted);"></i></div>
                                        <span>Workspace</span>
                                    </div>
                                </div>
                                
                                <div class="move-list-section" style="margin-top: 8px;">
                                    <div class="move-list-header">Articles</div>
                                    <t t-foreach="this.filteredMoveTargets || []" t-as="targetArticle" t-key="targetArticle.id">
                                        <div class="move-list-item" t-on-click="() => this.confirmMove('article', targetArticle.id)">
                                            <div class="move-cat-icon"><i class="fa fa-file-text-o" style="color: var(--km-text-muted);"></i></div>
                                            <span t-esc="this.stripHtml(targetArticle.name || 'Untitled')"></span>
                                        </div>
                                    </t>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </t>
            
            <!-- Global Search Modal -->
            <t t-if="state.isSearchModalOpen">
                <div class="km_pro_search_backdrop" t-on-click="() => this.closeSearchModal()">
                    <div class="km_pro_search_modal" t-on-click="(ev) => ev.stopPropagation()">
                        <div class="km_pro_search_header">
                            <span class="km_pro_search_icon">?</span>
                            <input type="text" class="km_pro_search_input" placeholder="Search for an article or a keyword..." 
                                   t-att-value="state.searchQuery" 
                                   t-on-input="(ev) => this.onSearchInput(ev)" 
                                   autofocus="autofocus"/>
                            <i class="fa fa-search search-magnify"></i>
                        </div>
                        
                        <div class="km_pro_search_results">
                            <t t-foreach="this.filteredSearchArticles || []" t-as="article" t-key="article.id">
                                <div class="km_pro_search_result_item" t-on-click="(ev) => this.selectSearchResult(ev, article.id)">
                                    <div class="result-left">
                                        <div class="result-icon">
                                            <t t-if="article.icon" t-esc="article.icon"/>
                                            <t t-else="">📄</t>
                                        </div>
                                        <span class="result-name" t-esc="this.stripHtml(article.name || 'Untitled')"></span>
                                        <i t-if="article.is_favorite" class="fa fa-star result-favorite"></i>
                                    </div>
                                    <div class="result-shortcuts">
                                        <span class="shortcut-badge">JUMP</span>
                                    </div>
                                </div>
                            </t>
                        </div>
                        
                        <div class="km_pro_search_advanced">
                            <div class="advanced-left">
                                <i class="fa fa-arrows-alt"></i> Advanced Search
                            </div>
                            <div class="advanced-shortcuts">
                                <span class="shortcut-badge">ALT</span> + <span class="shortcut-badge">B</span>
                            </div>
                        </div>
                        
                        <div class="km_pro_search_footer">
                            <span class="tip-label">TIP</span> — search for <span class="tip-pink">/menus</span>, <span class="tip-@">@conversations</span> and <span class="tip-?">?articles</span>
                        </div>
                    </div>
                </div>
            </t>
            <!-- Templates Modal -->
            <t t-if="state.isTemplatesModalOpen">
                <div class="km_pro_modal_backdrop" t-on-click="() => this.closeTemplatesModal()">
                    <div class="km_pro_search_modal shadow" t-on-click="(ev) => ev.stopPropagation()">
                        <div class="search-modal-header" style="padding: 20px; border-bottom: 1px solid var(--km-border-color); display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0; color: var(--km-text-title);">Browse Templates</h3>
                            <i class="fa fa-times" style="cursor: pointer; color: var(--km-text-muted); font-size: 1.1rem;" t-on-click="() => this.closeTemplatesModal()"></i>
                        </div>
                        <div class="search-results">
                            <t t-foreach="state.templates || []" t-as="template" t-key="template.id">
                                <div class="search-result-item" t-on-click="() => this.selectTemplate(template)">
                                    <div class="result-icon"><i class="fa fa-file-text-o"></i></div>
                                    <div class="result-details">
                                        <div class="result-title" t-esc="this.stripHtml(template.name)"></div>
                                        <div class="result-path" t-esc="template.description || 'No description available'"></div>
                                    </div>
                                </div>
                            </t>
                            <t t-if="state.templates.length === 0">
                                <div class="no-results">No templates found. Create one from the 3-dot menu on an article!</div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>

            <!-- Trash Modal -->
            <t t-if="state.isTrashModalOpen">
                <div class="km_pro_modal_backdrop" t-on-click="() => this.closeTrashModal()">
                    <div class="km_pro_search_modal shadow" t-on-click="(ev) => ev.stopPropagation()">
                        <div class="search-modal-header" style="padding: 20px; border-bottom: 1px solid var(--km-border-color); display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0; color: var(--km-text-title);"><i class="fa fa-trash"></i> Trash</h3>
                            <i class="fa fa-times" style="cursor: pointer; color: var(--km-text-muted); font-size: 1.1rem;" t-on-click="() => this.closeTrashModal()"></i>
                        </div>
                        <div class="search-results">
                            <t t-foreach="state.trashArticles || []" t-as="article" t-key="article.id">
                                <div class="search-result-item" style="display: flex; justify-content: space-between; align-items: center;">
                                    <div style="display: flex; align-items: center;">
                                        <div class="result-icon">
                                            <t t-if="article.icon" t-esc="article.icon"/>
                                            <t t-else=""><i class="fa fa-file-text-o"></i></t>
                                        </div>
                                        <div class="result-details">
                                            <div class="result-title" t-esc="this.stripHtml(article.name || 'Untitled')"></div>
                                        </div>
                                    </div>
                                    <div style="display: flex; gap: 8px;">
                                        <button t-on-click="() => this.restoreFromTrash(article.id)" style="background: var(--km-bg-secondary); border: 1px solid var(--km-border-color); color: var(--km-text-main); padding: 4px 12px; border-radius: 4px; cursor: pointer;">Restore</button>
                                        <button t-on-click="() => this.permanentDeleteArticle(article.id)" style="background: #d8576b; border: 1px solid #c24659; color: white; padding: 4px 12px; border-radius: 4px; cursor: pointer;">Delete</button>
                                    </div>
                                </div>
                            </t>
                            <t t-if="state.trashArticles.length === 0">
                                <div class="no-results">Trash is empty.</div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>
            
        </div>
    </div>
`;
KnowledgeManagementApp.components = { KnowledgeManagementSidebar, KnowledgeManagementEditor };

registry.category("actions").add("knowledge_management_pro.app", KnowledgeManagementApp);
