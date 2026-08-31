/** @odoo-module **/

import { Component, xml, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { KnowledgeManagementSidebar } from "./sidebar";
import { KnowledgeManagementEditor } from "./editor";

export class KnowledgeManagementApp extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({
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
            trashArticles: []
        });

        onWillStart(async () => {
            await this.loadArticles();
        });
    }

    async loadArticles() {
        const result = await this.orm.searchRead(
            "knowledge.management.article",
            [["state", "!=", "archived"]],
            ["id", "name", "write_date", "write_uid", "favorite_user_ids", "parent_id", "is_private"],
            { order: "id desc", limit: 200 }
        );
        
        // Build tree
        const articleMap = {};
        const rootArticles = [];
        const userId = this.env.session ? this.env.session.uid : 2;
        
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
            const isFavorite = a.favorite_user_ids && a.favorite_user_ids.includes(userId);
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
    get filteredArticles() {
        if (!this.state.searchQuery.trim()) return [];
        const query = this.state.searchQuery.toLowerCase();
        return this.state.allArticlesList.filter(a => (a.name || 'Untitled').toLowerCase().includes(query));
    }

    get filteredMoveTargets() {
        let targets = this.state.allArticlesList;
        // Don't allow moving an article into itself or its own children (we skip complex cycle detection for mockup)
        if (this.state.articleToMove) {
            targets = targets.filter(a => a.id !== this.state.articleToMove.id);
        }
        
        if (this.state.moveSearchQuery.trim()) {
            const query = this.state.moveSearchQuery.toLowerCase();
            targets = targets.filter(a => (a.name || 'Untitled').toLowerCase().includes(query));
        }
        return targets;
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
        const userId = this.env.session ? this.env.session.uid : 2; // Fallback to 2 for mockup
        const isFavorite = article.favorite_user_ids && article.favorite_user_ids.includes(userId);
        const command = isFavorite ? 3 : 4; // 3 to unlink, 4 to link
        await this.orm.write("knowledge.management.article", [article.id], {
            favorite_user_ids: [[command, userId]]
        });
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
        await this.orm.call("knowledge.management.article", "copy", [[id]]);
        await this.loadArticles();
    }

    async deleteArticle(id) {
        if (window.confirm("Are you sure you want to send this article to trash?")) {
            await this.orm.write("knowledge.management.article", [id], { state: "archived" });
            if (this.state.activeArticleId === id) {
                this.state.activeArticleId = null;
            }
            await this.loadArticles();
        }
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
                [["state", "=", "archived"]],
                ["id", "name", "write_date"]
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
            await this.orm.write("knowledge.management.article", [id], { state: "draft" });
            this.state.trashArticles = this.state.trashArticles.filter(a => a.id !== id);
            await this.loadArticles();
        } catch (e) {
            console.error("Failed to restore", e);
        }
    }

    // --- Templates Modal Handlers ---
    async openTemplatesModal() {
        this.state.isTemplatesModalOpen = true;
        try {
            const templates = await this.orm.searchRead(
                "knowledge.management.template",
                [],
                ["id", "name", "description", "content"]
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
            if (activeArticle && (!activeArticle.content || activeArticle.content === '<p><br></p>' || activeArticle.content.trim() === '')) {
                // Load into current empty article
                await this.orm.write("knowledge.management.article", [this.state.activeArticleId], {
                    content: template.content,
                    name: activeArticle.name && activeArticle.name !== 'Untitled' ? activeArticle.name : template.name
                });
                // Force reload of editor component is tricky, so we'll just reload the whole list and reset active
                const currentId = this.state.activeArticleId;
                this.state.activeArticleId = null;
                await this.loadArticles();
                this.setActiveArticle(currentId);
                return;
            }
        }
        
        // Otherwise, create new article from template
        const newArticleIds = await this.orm.create("knowledge.management.article", [{
            name: template.name,
            content: template.content
        }]);
        await this.loadArticles();
        this.setActiveArticle(newArticleIds[0] || newArticleIds);
    }

    async createNewArticle(parentId = false) {
        if (this.state.isCreating) return;
        this.state.isCreating = true;
        
        try {
            const vals = {
                name: "Untitled",
                state: "draft",
                is_private: true,
            };
            if (parentId && typeof parentId === 'number') {
                vals.parent_id = parentId;
            }
            const articleId = await this.orm.create("knowledge.management.article", [vals]);
            
            this.state.activeArticleId = articleId[0];
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
            const userId = this.env.session ? this.env.session.uid : 2;
            this.orm.write("knowledge.management.article", [articleId], {
                favorite_user_ids: [[4, userId]]
            }).then(() => this.loadArticles());
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
}

KnowledgeManagementApp.template = xml`
    <div class="km_pro_app">

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
                openSearchModal="() => this.openSearchModal()"
                openTemplatesModal="() => this.openTemplatesModal()"
                openTrashModal="() => this.openTrashModal()"
            />
            <KnowledgeManagementEditor 
                activeArticleId="state.activeArticleId"
                isFavorite="state.activeArticleId and state.allArticlesMap[state.activeArticleId] and state.allArticlesMap[state.activeArticleId].favorite_user_ids and state.allArticlesMap[state.activeArticleId].favorite_user_ids.includes(env.session ? env.session.uid : 2)"
                toggleFavorite="() => this.toggleFavoriteById(state.activeArticleId)"
                duplicateArticle="() => this.duplicateArticle(state.activeArticleId)"
                deleteArticle="() => this.deleteArticle(state.activeArticleId)"
                moveArticle="() => this.moveArticle(state.activeArticleId)"
                openTemplatesModal="() => this.openTemplatesModal()"
                onTitleChange="(newTitle) => this.onTitleChange(newTitle)"
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
                            <i class="fa fa-times move-close-btn" t-on-click="() => this.closeMoveModal()"></i>
                        </div>
                        
                        <div class="move-modal-body">
                            <div class="move-subtitle">
                                Move "<span t-esc="state.articleToMove ? state.articleToMove.name : 'Untitled'"/>" under:
                            </div>
                            <div class="move-search-box">
                                <input type="text" placeholder="Choose an Article..." 
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
                                        <div class="move-cat-icon"><i class="fa fa-users" style="color: #a0a0a0;"></i></div>
                                        <span>Shared</span>
                                    </div>
                                    <div class="move-list-item" t-on-click="() => this.confirmMove('workspace')">
                                        <div class="move-cat-icon"><i class="fa fa-building-o" style="color: #a0a0a0;"></i></div>
                                        <span>Workspace</span>
                                    </div>
                                </div>
                                
                                <div class="move-list-section" style="margin-top: 8px;">
                                    <div class="move-list-header">Articles</div>
                                    <t t-foreach="this.filteredMoveTargets" t-as="targetArticle" t-key="targetArticle.id">
                                        <div class="move-list-item" t-on-click="() => this.confirmMove('article', targetArticle.id)">
                                            <div class="move-cat-icon"><i class="fa fa-file-text-o" style="color: #a0a0a0;"></i></div>
                                            <span t-esc="targetArticle.name || 'Untitled'"></span>
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
                        
                        <div class="km_pro_search_results" t-if="this.filteredArticles.length > 0">
                            <t t-foreach="this.filteredArticles" t-as="article" t-key="article.id">
                                <div class="km_pro_search_result_item" t-on-click="(ev) => this.selectSearchResult(ev, article.id)">
                                    <div class="result-left">
                                        <span class="result-icon">📄</span>
                                        <span class="result-name" t-esc="article.name || 'Untitled'"></span>
                                        <i t-if="article.favorite_user_ids and article.favorite_user_ids.includes(env.session ? env.session.uid : 2)" class="fa fa-star result-favorite"></i>
                                    </div>
                                    <div class="result-shortcuts">
                                        <span class="shortcut-badge">CTRL</span> + <span class="shortcut-badge">↵</span> new tab
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
                            <span class="tip-label">TIP</span> — search for <span class="tip-pink">/menus</span>, <span class="tip-pink">@conversations</span> and <span class="tip-pink">?articles</span>
                        </div>
                    </div>
                </div>
            </t>
            <!-- Templates Modal -->
            <t t-if="state.isTemplatesModalOpen">
                <div class="km_pro_modal_backdrop" t-on-click="() => this.closeTemplatesModal()">
                    <div class="km_pro_search_modal shadow" t-on-click="(ev) => ev.stopPropagation()">
                        <div class="search-modal-header" style="padding: 20px; border-bottom: 1px solid #36363a;">
                            <h3 style="margin: 0; color: white;">Browse Templates</h3>
                            <i class="fa fa-times" style="position: absolute; right: 20px; top: 20px; cursor: pointer; color: #a0a0a0;" t-on-click="() => this.closeTemplatesModal()"></i>
                        </div>
                        <div class="search-results">
                            <t t-foreach="state.templates" t-as="template" t-key="template.id">
                                <div class="search-result-item" t-on-click="() => this.selectTemplate(template)">
                                    <div class="result-icon"><i class="fa fa-file-text-o"></i></div>
                                    <div class="result-details">
                                        <div class="result-title" t-esc="template.name"></div>
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
                        <div class="search-modal-header" style="padding: 20px; border-bottom: 1px solid #36363a;">
                            <h3 style="margin: 0; color: white;"><i class="fa fa-trash"></i> Trash</h3>
                            <i class="fa fa-times" style="position: absolute; right: 20px; top: 20px; cursor: pointer; color: #a0a0a0;" t-on-click="() => this.closeTrashModal()"></i>
                        </div>
                        <div class="search-results">
                            <t t-foreach="state.trashArticles" t-as="article" t-key="article.id">
                                <div class="search-result-item" style="display: flex; justify-content: space-between; align-items: center;">
                                    <div style="display: flex; align-items: center;">
                                        <div class="result-icon"><i class="fa fa-file-text-o"></i></div>
                                        <div class="result-details">
                                            <div class="result-title" t-esc="article.name || 'Untitled'"></div>
                                        </div>
                                    </div>
                                    <button t-on-click="() => this.restoreFromTrash(article.id)" style="background: #2b2e3b; border: 1px solid #36363a; color: #e0e0e0; padding: 4px 12px; border-radius: 4px; cursor: pointer;">Restore</button>
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
