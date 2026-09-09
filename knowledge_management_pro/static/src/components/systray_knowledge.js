/** @odoo-module **/

import { Component, xml, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { KnowledgeManagementEditor } from "./editor";

export class KnowledgeSystrayItem extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        this.state = useState({
            isOpen: false,
            searchQuery: "",
            articles: [],
            isLoading: false,
            showDialog: false,
            activeArticleId: null,
            isMaximized: false
        });

        onWillStart(async () => {
            await this.fetchArticles();
        });
        
        // Close dropdown when clicking outside
        this.onClickOutside = (ev) => {
            if (this.state.isOpen && !ev.target.closest(".o_knowledge_systray_item")) {
                this.state.isOpen = false;
            }
        };
        document.addEventListener("click", this.onClickOutside);
        
        onWillDestroy(() => {
            document.removeEventListener("click", this.onClickOutside);
        });
    }

    stripHtml(html) {
        if (!html) return 'Untitled';
        const tmp = document.createElement("DIV");
        tmp.innerHTML = html;
        return tmp.textContent || tmp.innerText || "Untitled";
    }

    async toggleMenu(ev) {
        if (ev) ev.stopPropagation();
        this.state.isOpen = !this.state.isOpen;
        if (this.state.isOpen) {
            await this.fetchArticles();
        }
    }

    async fetchArticles() {
        this.state.isLoading = true;
        let domain = [];
        if (this.state.searchQuery) {
            domain = ['|', ('name', 'ilike', this.state.searchQuery), ('content', 'ilike', this.state.searchQuery)];
        }
        
        try {
            const articles = await this.orm.searchRead(
                "knowledge.management.article",
                domain,
                ["id", "name", "icon", "write_date"],
                { limit: 10, order: "write_date desc" }
            );
            this.state.articles = articles;
        } catch (e) {
            console.error("Failed to fetch knowledge articles for systray", e);
        }
        this.state.isLoading = false;
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        // Debounce search
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        this.searchTimeout = setTimeout(() => {
            this.fetchArticles();
        }, 300);
    }

    openArticle(articleId, ev) {
        if (ev) ev.stopPropagation();
        this.state.activeArticleId = articleId;
        this.state.showDialog = true;
        this.state.isOpen = false;
    }
    
    closeDialog() {
        this.state.showDialog = false;
        this.state.activeArticleId = null;
    }
    
    toggleMaximize() {
        this.state.isMaximized = !this.state.isMaximized;
    }
    
    openInApp() {
        this.closeDialog();
        this.action.doAction("knowledge_management_pro.knowledge_management_pro_action_app");
    }
}

KnowledgeSystrayItem.template = xml`
    <div class="o_knowledge_systray_item d-flex align-items-center" style="position: relative;">
        <!-- Systray Icon -->
        <a class="dropdown-toggle o-no-caret" href="#" role="button" t-on-click="toggleMenu" title="Knowledge Base" style="padding: 0 10px; color: #fff;">
            <i class="fa fa-book fa-lg" role="img" aria-label="Knowledge Base"></i>
        </a>
        
        <!-- Dropdown Menu -->
        <div t-if="state.isOpen" class="dropdown-menu dropdown-menu-right show" style="position: absolute; top: 100%; right: 0; width: 350px; padding: 0; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border: 1px solid #dee2e6; border-radius: 4px; z-index: 1050; background: white;" t-on-click="(ev) => ev.stopPropagation()">
            
            <div class="p-2 border-bottom" style="background: #f8f9fa; border-radius: 4px 4px 0 0;">
                <div class="input-group">
                    <div class="input-group-prepend">
                        <span class="input-group-text bg-white border-right-0"><i class="fa fa-search"></i></span>
                    </div>
                    <input type="text" class="form-control border-left-0 pl-0" placeholder="Search articles..." t-att-value="state.searchQuery" t-on-input="onSearchInput"/>
                </div>
            </div>
            
            <div class="systray-article-list" style="max-height: 400px; overflow-y: auto;">
                <t t-if="state.isLoading">
                    <div class="p-3 text-center text-muted">
                        <i class="fa fa-circle-o-notch fa-spin mr-2"></i> Loading...
                    </div>
                </t>
                <t t-else="">
                    <t t-if="state.articles.length === 0">
                        <div class="p-3 text-center text-muted">
                            No articles found.
                        </div>
                    </t>
                    <t t-foreach="state.articles" t-as="article" t-key="article.id">
                        <div class="p-2 border-bottom" style="cursor: pointer; transition: background 0.2s;" t-on-click="(ev) => this.openArticle(article.id, ev)" t-on-mouseenter="(ev) => ev.currentTarget.style.background = '#f1f1f1'" t-on-mouseleave="(ev) => ev.currentTarget.style.background = 'white'">
                            <div class="d-flex align-items-center">
                                <span class="mr-2" style="font-size: 1.2rem;">
                                    <t t-if="article.icon" t-esc="article.icon"/>
                                    <t t-else="">📄</t>
                                </span>
                                <div class="flex-grow-1 text-truncate">
                                    <div class="font-weight-bold text-dark text-truncate" t-esc="this.stripHtml(article.name || 'Untitled')"></div>
                                </div>
                            </div>
                        </div>
                    </t>
                </t>
            </div>
            
            <div class="p-2 border-top text-center" style="background: #f8f9fa; border-radius: 0 0 4px 4px; cursor: pointer;" t-on-click="openInApp">
                <a href="#" class="text-primary font-weight-bold">Open Knowledge App</a>
            </div>
        </div>
        
        <!-- Floating Dialog -->
        <t t-if="state.showDialog">
            <div class="km_pro_systray_dialog_backdrop" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1060; display: flex; align-items: center; justify-content: center;" t-on-click="closeDialog">
                <div class="km_pro_systray_dialog_content" 
                     t-att-style="state.isMaximized ? 'width: 100%; height: 100%; border-radius: 0;' : 'width: 80%; height: 85%; max-width: 1200px; border-radius: 8px;'"
                     style="background: #1e1e1e; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.3); transition: all 0.2s ease-in-out;" 
                     t-on-click="(ev) => ev.stopPropagation()">
                    
                    <div class="km_pro_systray_dialog_header" style="height: 40px; background: #2d2d2d; display: flex; align-items: center; justify-content: flex-end; padding: 0 16px; border-bottom: 1px solid #3c3c3c;">
                        <button class="btn btn-sm btn-link text-white mr-2" t-on-click="openInApp" title="Open in App">
                            <i class="fa fa-external-link"></i>
                        </button>
                        <button class="btn btn-sm btn-link text-white mr-2" t-on-click="toggleMaximize" title="Maximize">
                            <i class="fa" t-att-class="state.isMaximized ? 'fa-compress' : 'fa-expand'"></i>
                        </button>
                        <button class="btn btn-sm btn-link text-white" t-on-click="closeDialog" title="Close">
                            <i class="fa fa-times" style="font-size: 1.2rem;"></i>
                        </button>
                    </div>
                    
                    <div class="km_pro_systray_dialog_body" style="flex: 1; overflow-y: auto; position: relative;">
                        <KnowledgeManagementEditor activeArticleId="state.activeArticleId" />
                    </div>
                    
                </div>
            </div>
        </t>
    </div>
`;

KnowledgeSystrayItem.components = { KnowledgeManagementEditor };

export const systrayItem = {
    Component: KnowledgeSystrayItem,
};

// Removed as per user request to hide the book icon from the top navbar
// registry.category("systray").add("KnowledgeSystrayItem", systrayItem, { sequence: 90 });
