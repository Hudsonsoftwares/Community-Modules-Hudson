/** @odoo-module **/

import { Component, xml, useState, onWillUpdateProps, useEffect, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { KnowledgeKanbanMockup } from "./kanban_mockup";
import { KnowledgeListMockup } from "./list_mockup";
import { KnowledgeCalendarMockup } from "./calendar_mockup";
import { Chatter } from "@mail/chatter/web_portal/chatter";

export class KnowledgeManagementEditor extends Component {
    static props = {
        activeArticleId: { type: Number, optional: true },
        isFavorite: { type: Boolean, optional: true },
        toggleFavorite: { type: Function, optional: true },
        duplicateArticle: { type: Function, optional: true },
        deleteArticle: { type: Function, optional: true },
        moveArticle: { type: Function, optional: true },
        openTemplatesModal: { type: Function, optional: true },
        onTitleChange: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
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
            showHistoryComparison: false,
            isKanbanMode: false,
            kanbanTitle: "",
            showListDialog: false,
            listItemName: "",
            isListMode: false,
            listTitle: "",
            showCalendarDialog: false,
            calendarItemName: "",
            isCalendarMode: false,
            calendarTitle: "",
            isShareMenuOpen: false,
            shareToWeb: false,
            generalAccess: "Members only",
            isGeneralAccessDropdownOpen: false,
            isInviteModalOpen: false,
            invitePermission: "Can edit",
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
            isToolbarVisible: false,
            toolbarTop: 0,
            toolbarLeft: 0,
            selectedImage: null,
            imageToolbarTop: 0,
            imageToolbarLeft: 0,
            isSlashMenuOpen: false,
            slashMenuTop: 0,
            slashMenuLeft: 0,
            slashMenuSelectedIndex: 0,
        });

        this.slashMenuItems = [
            { id: 'h1', title: 'Heading 1', description: 'Big section heading.', icon: 'fa-header', command: 'formatBlock', value: 'H1' },
            { id: 'h2', title: 'Heading 2', description: 'Medium section heading.', icon: 'fa-header', command: 'formatBlock', value: 'H2' },
            { id: 'h3', title: 'Heading 3', description: 'Small section heading.', icon: 'fa-header', command: 'formatBlock', value: 'H3' },
            { id: 'p', title: 'Text', description: 'Just start writing with plain text.', icon: 'fa-font', command: 'formatBlock', value: 'P' },
            { id: 'bullet', title: 'Bulleted List', description: 'Create a simple bulleted list.', icon: 'fa-list-ul', command: 'insertUnorderedList' },
            { id: 'number', title: 'Numbered List', description: 'Create a list with numbering.', icon: 'fa-list-ol', command: 'insertOrderedList' },
            { id: 'checkbox', title: 'To-do List', description: 'Track tasks with a to-do list.', icon: 'fa-check-square-o', action: 'insertCheckbox' },
            { id: 'image', title: 'Image', description: 'Upload or embed with a link.', icon: 'fa-image', action: 'triggerImageUpload' },
            { id: 'document', title: 'Document', description: 'Upload a document or file.', icon: 'fa-upload', action: 'triggerDocumentUpload' },
            { id: 'table', title: 'Table', description: 'Add simple tabular content.', icon: 'fa-table', action: 'insertTable' },
            { id: 'link', title: 'Button Link', description: 'Add a clickable button.', icon: 'fa-link', action: 'insertLink' },
        ];
        
        this.titleRef = useRef("title");
        this.contentRef = useRef("content");
        this.fileInputRef = useRef("fileInput");
        this.imageInputRef = useRef("imageInput");
        this.documentInputRef = useRef("documentInput");
        this.saveTimeout = null;

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.activeArticleId !== this.props.activeArticleId) {
                await this.loadArticle(nextProps.activeArticleId);
            }
        });

        this.closeMenus = (ev) => {
            if (this.state.isShareMenuOpen && !ev.target.closest('.km_pro_share_menu') && !ev.target.closest('.km_pro_share_btn')) {
                this.state.isShareMenuOpen = false;
            }
            if (this.state.isMoreMenuOpen && !ev.target.closest('.km_pro_more_menu') && !ev.target.closest('.km_pro_more_btn')) {
                this.state.isMoreMenuOpen = false;
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
            if (this.state.isSlashMenuOpen && !ev.target.closest('.km_pro_slash_menu')) {
                this.state.isSlashMenuOpen = false;
            }
        };

        this.handleSelection = () => {
            const selection = window.getSelection();
            if (!selection.anchorNode) return;
            
            const inContent = this.contentRef.el && this.contentRef.el.contains(selection.anchorNode);
            const inTitle = this.titleRef.el && this.titleRef.el.contains(selection.anchorNode);
            
            if (!inContent && !inTitle) {
                if (this.state.isToolbarVisible) {
                    this.state.isToolbarVisible = false;
                }
                return;
            }
            if (!selection.isCollapsed && selection.toString().trim().length > 0) {
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                this.state.toolbarTop = rect.top - 45;
                this.state.toolbarLeft = rect.left + (rect.width / 2);
                this.state.isToolbarVisible = true;
            } else {
                if (this.state.isToolbarVisible) {
                    this.state.isToolbarVisible = false;
                }
            }
        };

        useEffect(() => {
            document.addEventListener("click", this.closeMenus);
            document.addEventListener("selectionchange", this.handleSelection);
            return () => {
                document.removeEventListener("click", this.closeMenus);
                document.removeEventListener("selectionchange", this.handleSelection);
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
    }

    async loadArticle(articleId) {
        if (!articleId) {
            this.state.article = null;
            return;
        }
        
        this.state.isLoading = true;
        try {
            const result = await this.orm.read("knowledge.management.article", [articleId], ["name", "content", "write_date", "write_uid", "icon", "cover_image", "cover_position", "is_locked", "shared_partner_ids"]);
            if (result.length > 0) {
                this.state.article = result[0];
                this.updateDOMContent(this.state.article);
            }
        } catch (error) {
            console.error("Failed to load article", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    updateDOMContent(article) {
        if (this.titleRef.el) {
            this.titleRef.el.innerHTML = article.name === 'Untitled' ? '' : (article.name || '');
        }
        
        if (article.content && article.content.includes('data-kanban="true"')) {
            this.state.isKanbanMode = true;
            this.state.isListMode = false;
            const match = article.content.match(/data-kanban-title="([^"]*)"/);
            this.state.kanbanTitle = match ? match[1] : 'Items';
        } else if (article.content && article.content.includes('data-list="true"')) {
            this.state.isKanbanMode = false;
            this.state.isListMode = true;
            this.state.isCalendarMode = false;
            const match = article.content.match(/data-list-title="([^"]*)"/);
            this.state.listTitle = match ? match[1] : 'Items';
        } else if (article.content && article.content.includes('data-calendar="true"')) {
            this.state.isKanbanMode = false;
            this.state.isListMode = false;
            this.state.isCalendarMode = true;
            const match = article.content.match(/data-calendar-title="([^"]*)"/);
            this.state.calendarTitle = match ? match[1] : 'Items';
        } else {
            this.state.isKanbanMode = false;
            this.state.isListMode = false;
            this.state.isCalendarMode = false;
            if (this.contentRef.el) {
                this.contentRef.el.innerHTML = article.content || '';
            }
        }
    }

    onTitleInput() {
        const title = this.titleRef.el.innerHTML || 'Untitled';
        this.state.article.name = title;
        
        if (this.props.onTitleChange) {
            this.props.onTitleChange(title);
        }

        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }

        this.saveTimeout = setTimeout(async () => {
            if (!this.props.activeArticleId) return;
            try {
                await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                    name: title
                });
            } catch (error) {
                console.error("Failed to save article title", error);
            }
        }, 1000);
    }

    onEditorKeydown(ev) {
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

        if (ev.key === '/') {
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                
                // Position menu slightly below the cursor
                this.state.slashMenuTop = rect.bottom + 10;
                this.state.slashMenuLeft = rect.left;
                this.state.isSlashMenuOpen = true;
                this.state.slashMenuSelectedIndex = 0;
            }
        }
    }

    executeSlashCommand(item) {
        this.state.isSlashMenuOpen = false;
        
        // Remove the '/' character that was just typed
        const selection = window.getSelection();
        if (selection.rangeCount > 0) {
            const range = selection.getRangeAt(0);
            
            // Basic text node modification to remove the slash
            if (range.startContainer.nodeType === Node.TEXT_NODE) {
                const text = range.startContainer.textContent;
                const pos = range.startOffset;
                // Look backwards from cursor to find the slash
                const lastSlashIndex = text.lastIndexOf('/', pos);
                if (lastSlashIndex !== -1) {
                    range.startContainer.textContent = text.substring(0, lastSlashIndex) + text.substring(pos);
                    // Reposition cursor
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
        if (this.fileInputRef && this.fileInputRef.el) {
            this.fileInputRef.el.click();
        }
        this.state.isMoreMenuOpen = false;
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
        if (!this.props.activeArticleId) return;
        const newLockState = !this.state.article.is_locked;
        this.state.article.is_locked = newLockState;
        this.state.isMoreMenuOpen = false;
        
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                is_locked: newLockState
            });
            // Also explicitly update the contenteditable attribute since Owl might not re-bind it on an unmanaged DOM element cleanly
            if (this.contentRef && this.contentRef.el) {
                this.contentRef.el.setAttribute("contenteditable", !newLockState);
            }
        } catch (error) {
            console.error("Failed to save lock state", error);
            // Revert state on failure
            this.state.article.is_locked = !newLockState;
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
        this.state.isHistoryModalOpen = true;
        this.state.isMoreMenuOpen = false;
        
        try {
            const versions = await this.orm.searchRead(
                "knowledge.management.version",
                [["article_id", "=", this.props.activeArticleId]],
                ["id", "version_number", "user_id", "date", "content_snapshot", "change_summary"],
                { order: "date desc" }
            );
            this.state.historyVersions = versions;
            if (versions.length > 0) {
                this.state.selectedHistoryVersion = versions[0];
            }
        } catch (error) {
            console.error("Failed to load versions", error);
        }
    }

    closeHistoryModal() {
        this.state.isHistoryModalOpen = false;
        this.state.historyVersions = [];
        this.state.selectedHistoryVersion = null;
    }

    selectHistoryVersion(version) {
        this.state.selectedHistoryVersion = version;
    }

    async restoreHistory() {
        if (!this.state.selectedHistoryVersion || !this.props.activeArticleId) return;
        
        try {
            await this.orm.write("knowledge.management.article", [this.props.activeArticleId], {
                content: this.state.selectedHistoryVersion.content_snapshot || ""
            });
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
            await this.orm.create("knowledge.management.template", [{
                name: this.state.article.name,
                content: this.state.article.content,
                category_id: this.state.article.category_id ? this.state.article.category_id[0] : false,
            }]);
            
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

    onTitleKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            if (this.contentRef.el) {
                this.contentRef.el.focus();
            }
        }
    }

    onInput() {
        if (!this.contentRef.el) return;
        const content = this.contentRef.el.innerHTML;

        // Update local state so empty checks work immediately
        this.state.article.content = content;

        this.debouncedSave();
    }

    execFormat(command, value = null) {
        document.execCommand(command, false, value);
        this.onInput();
    }

    insertCheckbox() {
        const id = Math.random().toString(36).substr(2, 9);
        const checkboxHtml = `<div class="km_pro_checkbox_block" style="display: flex; align-items: flex-start; margin-bottom: 4px;"><input type="checkbox" id="chk_${id}" style="margin-top: 6px; margin-right: 8px; cursor: pointer;" contenteditable="false" onchange="if(this.hasAttribute('checked')) { this.removeAttribute('checked'); } else { this.setAttribute('checked', 'checked'); }" /> <label contenteditable="true" style="flex: 1; outline: none; margin: 0; min-width: 50px;">Task...</label></div><br/>`;
        document.execCommand("insertHTML", false, checkboxHtml);
        this.onInput();
    }

    insertTable() {
        const tableHtml = `
            <table class="km_pro_table" style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #36363a; padding: 8px; min-width: 50px;">Cell</td>
                        <td style="border: 1px solid #36363a; padding: 8px; min-width: 50px;">Cell</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #36363a; padding: 8px; min-width: 50px;">Cell</td>
                        <td style="border: 1px solid #36363a; padding: 8px; min-width: 50px;">Cell</td>
                    </tr>
                </tbody>
            </table><br/>
        `;
        document.execCommand("insertHTML", false, tableHtml);
        this.onInput();
    }

    insertColumns() {
        const columnsHtml = `
            <div class="km_pro_columns" style="display: flex; gap: 16px; margin-bottom: 16px;">
                <div style="flex: 1; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 4px; min-height: 24px;">Column 1...</div>
                <div style="flex: 1; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 4px; min-height: 24px;">Column 2...</div>
            </div><br/>
        `;
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
        const url = window.prompt("Enter the URL for the button:");
        if (!url) return;
        const text = window.prompt("Enter the button text:") || "Click Here";
        const buttonHtml = `<a href="${url}" class="btn btn-primary km_pro_button_link" style="display: inline-block; padding: 8px 16px; margin: 8px 0; background: #2563eb; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600;" target="_blank">${text}</a>&nbsp;`;
        document.execCommand("insertHTML", false, buttonHtml);
        this.onInput();
    }
    
    onEditorClick(ev) {
        if (ev.target.tagName === 'IMG') {
            if (this.state.selectedImage) {
                this.state.selectedImage.style.outline = '2px solid transparent';
            }
            this.state.selectedImage = ev.target;
            this.state.selectedImage.style.outline = '2px solid #2563eb';
            const rect = ev.target.getBoundingClientRect();
            this.state.imageToolbarTop = rect.top - 50;
            this.state.imageToolbarLeft = rect.left + rect.width / 2;
        } else if (this.state.selectedImage && !ev.target.closest('.km_pro_image_toolbar')) {
            this.state.selectedImage.style.outline = '2px solid transparent';
            this.state.selectedImage = null;
        }
    }

    resizeImage(percentage) {
        if (this.state.selectedImage) {
            this.state.selectedImage.style.width = percentage;
            this.onInput();
        }
    }

    toggleImagePadding() {
        if (this.state.selectedImage) {
            const currentPadding = this.state.selectedImage.style.padding;
            if (currentPadding === '20px') {
                this.state.selectedImage.style.padding = '0';
                this.state.selectedImage.style.background = 'transparent';
            } else {
                this.state.selectedImage.style.padding = '20px';
                this.state.selectedImage.style.background = '#2b2b30';
            }
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

    cropImage(aspectRatio) {
        if (this.state.selectedImage) {
            this.state.selectedImage.style.objectFit = 'cover';
            if (aspectRatio === '1:1') {
                this.state.selectedImage.style.aspectRatio = '1 / 1';
            } else if (aspectRatio === '16:9') {
                this.state.selectedImage.style.aspectRatio = '16 / 9';
            } else {
                this.state.selectedImage.style.aspectRatio = 'auto';
                this.state.selectedImage.style.objectFit = 'contain';
            }
            this.onInput();
        }
    }

    debouncedSave() {
        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }

        const contentHtml = this.contentRef.el ? this.contentRef.el.innerHTML : "";
        const contentText = this.contentRef.el ? this.contentRef.el.innerText.trim() : "";
        
        if (this.state.article && (this.state.article.name === 'Untitled' || this.state.article.name === '')) {
            const firstLine = contentText.split('\n')[0].substring(0, 50);
            if (firstLine) {
                this.state.article.name = firstLine;
                if (this.titleRef.el) {
                    this.titleRef.el.innerHTML = firstLine;
                }
                if (this.props.onTitleChange) {
                    this.props.onTitleChange(firstLine);
                }
            }
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
        const accessLevel = this.state.invitePermission === 'Can edit' ? 'write' : 'read';
        
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

    insertKanban() {
        const itemName = this.state.kanbanItemName || 'Items';
        this.state.kanbanTitle = itemName;
        this.state.isKanbanMode = true;
        this.state.showKanbanDialog = false;
        
        // Also save this state so it persists
        if (this.contentRef.el) {
            this.contentRef.el.innerHTML = `<div data-kanban="true" data-kanban-title="${itemName}"></div>`;
            this.onInput();
        }
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

    toggleFullWidth() {
        this.state.isFullWidth = !this.state.isFullWidth;
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
        if (this.contentRef.el) {
            this.contentRef.el.innerHTML = `<div data-list="true" data-list-title="${itemName}"></div>`;
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
        this.state.isCalendarMode = true;
        this.state.showCalendarDialog = false;
        
        // Also save this state so it persists
        if (this.contentRef.el) {
            this.contentRef.el.innerHTML = `<div data-calendar="true" data-calendar-title="${itemName}"></div>`;
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
    <div class="km_pro_editor_area">
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
                            <span t-esc="state.article ? state.article.name : 'Untitled'"></span>
                            <i t-if="state.article and state.article.is_locked" class="fa fa-lock" style="margin-left: 8px; color: #a0a0a0;"></i>
                        </span>
                    </div><i class="fa fa-cloud" style="color: #a0a0a0; margin-left: 8px;"></i>
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
                        <span class="km_pro_share_btn" t-att-class="{'active': state.isShareMenuOpen}" t-on-click="(ev) => { ev.stopPropagation(); state.isShareMenuOpen = !state.isShareMenuOpen; state.isGeneralAccessDropdownOpen = false; }">Share</span>
                        
                        <!-- Share Dropdown -->
                        <t t-if="state.isShareMenuOpen">
                            <div class="km_pro_share_menu" t-on-click="(ev) => ev.stopPropagation()">
                                <div class="share-row share-header-row">
                                    <div class="row-left">
                                        <i class="fa fa-globe" style="font-size: 1.5rem; color: #e0e0e0; margin-right: 16px;"></i>
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
                                    <div class="km_pro_toggle_switch" t-att-class="{'active': state.shareToWeb}" t-on-click="() => state.shareToWeb = !state.shareToWeb">
                                        <div class="toggle-circle"></div>
                                    </div>
                                </div>
                                <div class="share-divider"></div>
                                
                                <div class="share-row">
                                    <div class="row-left">
                                        <i class="fa fa-building-o" style="font-size: 1.2rem; color: #a0a0a0; margin-right: 16px;"></i>
                                        <span>General Access</span>
                                    </div>
                                    <div class="general-access-trigger" style="position: relative; cursor: pointer; color: #e0e0e0; font-size: 0.9rem;" t-on-click="() => state.isGeneralAccessDropdownOpen = !state.isGeneralAccessDropdownOpen">
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
                    <div class="km_pro_chatter_toggle" t-att-class="{'active': state.isChatterOpen}" title="Close chatter panel" t-on-click="() => state.isChatterOpen = !state.isChatterOpen">
                        <i class="fa fa-comments-o"></i>
                    </div>
                    <div class="km_pro_favorite_toggle" t-att-class="{'active': props.isFavorite}" t-att-title="props.isFavorite ? 'Remove from favorites' : 'Add to favorites'" t-on-click="props.toggleFavorite">
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
                                    <span class="km_pro_toggle_switch" t-att-class="{'active': state.isFullWidth}"></span>
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
                <div style="flex: 1; overflow-y: auto; display: flex; flex-direction: column;">
                    <t t-if="state.isKanbanMode">
                        <KnowledgeKanbanMockup itemName="state.kanbanTitle" />
                    </t>
                    <t t-elif="state.isListMode">
                        <KnowledgeListMockup itemName="state.listTitle" />
                    </t>
                    <t t-elif="state.isCalendarMode">
                        <KnowledgeCalendarMockup itemName="state.calendarTitle" />
                    </t>
                    <t t-else="">
                        <input type="file" t-ref="fileInput" style="display: none;" accept="image/*" t-on-change="onCoverFileChange" />
                        <input type="file" t-ref="imageInput" style="display: none;" accept="image/*" t-on-change="onImageFileChange" />
                        <input type="file" t-ref="documentInput" style="display: none;" t-on-change="onDocumentFileChange" />
                        
                        <!-- Floating Image Menu -->
                        <t t-if="state.selectedImage">
                            <div class="km_pro_image_toolbar shadow" t-attf-style="position: fixed; top: {{ state.imageToolbarTop }}px; left: {{ state.imageToolbarLeft }}px; transform: translateX(-50%); z-index: 1060; display: flex; gap: 8px; padding: 6px 12px; background: #2b2b30; border: 1px solid #4a4a50; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                                <button title="100% Width" t-on-click.prevent="() => this.resizeImage('100%')" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-arrows-h"></i> 100%</button>
                                <button title="50% Width" t-on-click.prevent="() => this.resizeImage('50%')" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;">50%</button>
                                <button title="25% Width" t-on-click.prevent="() => this.resizeImage('25%')" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;">25%</button>
                                <div style="width: 1px; background: #4a4a50; margin: 0 4px;"></div>
                                <button title="Toggle Padding" t-on-click.prevent="() => this.toggleImagePadding()" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-expand"></i> Pad</button>
                                <button title="Add Caption" t-on-click.prevent="() => this.addCaption()" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-align-center"></i> Capt</button>
                                <div style="width: 1px; background: #4a4a50; margin: 0 4px;"></div>
                                <button title="Crop Square" t-on-click.prevent="() => this.cropImage('1:1')" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-square"></i> 1:1</button>
                                <button title="Crop 16:9" t-on-click.prevent="() => this.cropImage('16:9')" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-youtube-play"></i> 16:9</button>
                                <button title="Reset Crop" t-on-click.prevent="() => this.cropImage('auto')" style="background: transparent; color: #e0e0e0; border: none; cursor: pointer;"><i class="fa fa-refresh"></i> Fix</button>
                            </div>
                        </t>

                        <!-- Cover Display (Full Width) -->
                        <t t-if="state.article and state.article.cover_image">
                            <div class="km_pro_cover_container" t-att-class="{'repositioning': state.isRepositioning}" t-on-mousedown="startDrag" t-on-mousemove="onCoverDrag" t-on-mouseup="stopDrag" t-on-mouseleave="stopDrag">
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

                        <div class="km_pro_editor_content" t-att-class="{'full_width': state.isFullWidth}">

                            <!-- Icon Display -->
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

                            <h1 class="km_pro_article_title" 
                                   t-on-input="onTitleInput" 
                                   t-on-keydown="onTitleKeydown"
                                   placeholder="Untitled" 
                                   style="text-transform: uppercase; background: transparent; width: 100%; display: block; border: none; outline: none; margin: 0; padding: 0; min-height: 40px;"
                                   t-ref="title"
                                   t-att-contenteditable="state.article.is_locked ? 'false' : 'true'"></h1>
                            
                            <t t-if="state.article and !state.article.is_locked and state.isToolbarVisible">
                                <div class="km_pro_format_toolbar shadow" t-attf-style="position: fixed; top: {{ state.toolbarTop }}px; left: {{ state.toolbarLeft }}px; transform: translateX(-50%); z-index: 1050; display: flex; gap: 8px; padding: 4px 8px; background: #2b2b30; border: 1px solid #36363a; border-radius: 6px; align-items: center; box-shadow: 0 4px 12px rgba(0,0,0,0.2); white-space: nowrap;">
                                    <select class="km_pro_format_select" t-on-change="(ev) => this.execFormat('formatBlock', ev.target.value)" style="background: transparent; color: #e0e0e0; border: 1px solid #4a4a50; border-radius: 4px; padding: 2px 4px; cursor: pointer;">
                                        <option value="P" style="background: #2b2b30;">Paragraph</option>
                                        <option value="H1" style="background: #2b2b30;">Heading 1</option>
                                        <option value="H2" style="background: #2b2b30;">Heading 2</option>
                                        <option value="H3" style="background: #2b2b30;">Heading 3</option>
                                    </select>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: #4a4a50; margin: 0 4px;"></div>
                                    
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('bold')" title="Bold" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-bold"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('italic')" title="Italic" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-italic"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('underline')" title="Underline" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-underline"></i></button>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: #4a4a50; margin: 0 4px;"></div>
                                    
                                    <div class="km_pro_format_btn" style="position: relative; display: flex; align-items: center; padding: 4px 8px; cursor: pointer; border-radius: 4px;" title="Text Color">
                                        <i class="fa fa-font" style="color: #e0e0e0; pointer-events: none;"></i>
                                        <input type="color" t-on-input="(ev) => this.execFormat('foreColor', ev.target.value)" style="opacity: 0; position: absolute; left: 0; top: 0; width: 100%; height: 100%; cursor: pointer;" />
                                    </div>
                                    <div class="km_pro_format_btn" style="position: relative; display: flex; align-items: center; padding: 4px 8px; cursor: pointer; border-radius: 4px;" title="Highlight Color">
                                        <i class="fa fa-paint-brush" style="color: #e0e0e0; pointer-events: none;"></i>
                                        <input type="color" t-on-input="(ev) => this.execFormat('backColor', ev.target.value)" style="opacity: 0; position: absolute; left: 0; top: 0; width: 100%; height: 100%; cursor: pointer;" />
                                    </div>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: #4a4a50; margin: 0 4px;"></div>
                                    
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.triggerImageUpload()" title="Upload Image" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-image"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.triggerDocumentUpload()" title="Upload Document" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-paperclip"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.insertLink()" title="Add Button Link" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-link"></i></button>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: #4a4a50; margin: 0 4px;"></div>
                                    
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('insertUnorderedList')" title="Bullet List" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-list-ul"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.execFormat('insertOrderedList')" title="Numbered List" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-list-ol"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.insertCheckbox()" title="Checkbox" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-check-square-o"></i></button>
                                    
                                    <div class="km_pro_format_divider" style="width: 1px; height: 16px; background: #4a4a50; margin: 0 4px;"></div>
                                    
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.insertTable()" title="Table" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-table"></i></button>
                                    <button class="km_pro_format_btn" t-on-mousedown.prevent="() => this.insertColumns()" title="Columns" style="background: transparent; border: none; color: #e0e0e0; cursor: pointer; padding: 4px 8px; border-radius: 4px;"><i class="fa fa-columns"></i></button>
                                </div>
                            </t>
                                
                            <div class="km_pro_article_content" 
                                 t-ref="content" 
                                 t-att-contenteditable="state.article and state.article.is_locked ? 'false' : 'true'" 
                                 t-on-input="onInput"
                                 t-on-click="onEditorClick"
                                 t-on-keydown="onEditorKeydown"
                                 style="min-height: 200px; outline: none; margin-top: 8px;"
                                 placeholder="Type '/' for commands"></div>

                            <t t-if="state.isSlashMenuOpen">
                                <div class="km_pro_slash_menu shadow" t-attf-style="position: fixed; top: {{ state.slashMenuTop }}px; left: {{ state.slashMenuLeft }}px; z-index: 1060; background: #2b2b30; border: 1px solid #36363a; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); width: 250px; max-height: 300px; overflow-y: auto;">
                                    <t t-foreach="slashMenuItems" t-as="item" t-key="item.id">
                                        <div class="km_pro_slash_item" 
                                             t-att-class="{'selected': state.slashMenuSelectedIndex === item_index}"
                                             t-on-mousedown.prevent="() => this.executeSlashCommand(item)"
                                             t-on-mouseenter="() => state.slashMenuSelectedIndex = item_index"
                                             style="display: flex; align-items: center; gap: 12px; padding: 8px 12px; cursor: pointer; color: #e0e0e0; transition: background 0.1s;">
                                            <div style="width: 24px; height: 24px; border-radius: 4px; background: #3f3f46; display: flex; align-items: center; justify-content: center;">
                                                <i t-attf-class="fa {{ item.icon }}"></i>
                                            </div>
                                            <div>
                                                <div style="font-weight: 500; font-size: 0.95rem;"><t t-esc="item.title"/></div>
                                                <div style="font-size: 0.8rem; color: #a0a0a0;"><t t-esc="item.description"/></div>
                                            </div>
                                        </div>
                                    </t>
                                </div>
                            </t>

                            <t t-if="state.article and !state.article.content">
                                <div class="km_pro_empty_state_quick_actions" style="margin-top: 0; padding-top: 0;">
                                    <div class="km_pro_inline_commands" style="display: flex; align-items: center; margin-bottom: 24px; color: #a0a0a0; font-size: 1.05rem; gap: 12px;">
                                        <span style="user-select: none;">Type "/" for commands</span>
                                        <div style="display: flex; gap: 4px; align-items: center;">
                                            <i class="fa fa-picture-o" title="Image" t-on-click="() => this.triggerImageUpload()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-upload" title="Document" t-on-click="() => this.triggerDocumentUpload()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-square" title="Block" t-on-click="() => this.execFormat('formatBlock', 'P')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-list-ul" title="Bullet List" t-on-click="() => this.execFormat('insertUnorderedList')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-list-ol" title="Numbered List" t-on-click="() => this.execFormat('insertOrderedList')" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <i class="fa fa-check-square-o" title="Checkbox" t-on-click="() => this.insertCheckbox()" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                            <strong title="AI" t-on-click="onQuickActionAI" style="cursor: pointer; padding: 4px 6px; border-radius: 4px; transition: background 0.2s; font-family: sans-serif; font-size: 0.9rem;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'">AI</strong>
                                            <i class="fa fa-ellipsis-v" title="More" t-on-click="() => this.execFormat('formatBlock', 'H1')" style="cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'"></i>
                                        </div>
                                    </div>
                                    <p class="km_pro_hint_text">Keep writing, or choose an option below to jump right in!</p>
                                    
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionTemplate">
                                        <i class="fa fa-paint-brush"></i> Load a Template
                                    </div>
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionKanban">
                                        <i class="fa fa-th-large"></i> Build an Item Kanban
                                    </div>
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionList">
                                        <i class="fa fa-list-ul"></i> Build an Item List
                                    </div>
                                    <div class="km_pro_quick_action" t-on-click="onQuickActionCalendar">
                                        <i class="fa fa-calendar"></i> Build an Item Calendar
                                    </div>
                                    <div class="km_pro_quick_action km_pro_ai_action" t-on-click="onQuickActionAI">
                                        <i class="fa fa-magic"></i> Generate an Article with AI
                                    </div>
                                </div>
                            </t>

                            <!-- Removed duplicate km_pro_rich_text div -->
                        </div>
                    </t>
                </div>
                
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
                                        <div class="history-timeline-item" t-att-class="{'active': state.selectedHistoryVersion and state.selectedHistoryVersion.id === version.id}" t-on-click="() => this.selectHistoryVersion(version)">
                                            <div class="history-timeline-line"></div>
                                            <div class="history-timeline-node">
                                                <i t-if="state.selectedHistoryVersion and state.selectedHistoryVersion.id === version.id" class="fa fa-play-circle"></i>
                                                <div t-else="" class="history-dot"></div>
                                            </div>
                                            <div class="history-version-details">
                                                <div class="history-version-time" t-esc="this.formatHistoryDate(version.date)"></div>
                                                <div class="history-version-author">
                                                    by <t t-esc="version.user_id ? version.user_id[1] : 'Unknown'"/>
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
                                    <div class="history-preview-topbar">
                                        <div class="history-toggle-switch" t-att-class="{'active': state.showHistoryComparison}" t-on-click="() => state.showHistoryComparison = !state.showHistoryComparison">
                                            <div class="toggle-circle"></div>
                                        </div>
                                        <span class="history-toggle-label">Show comparison</span>
                                    </div>
                                    
                                    <t t-if="state.selectedHistoryVersion">
                                        <div class="history-info-banner">
                                            <i class="fa fa-info-circle"></i>
                                            <span>Showing <strong t-esc="state.selectedHistoryVersion.user_id ? state.selectedHistoryVersion.user_id[1] : 'Unknown'"/>'s description from <strong t-esc="this.formatHistoryDateFull(state.selectedHistoryVersion.date)"/></span>
                                        </div>
                                        
                                        <div class="history-content-preview">
                                            <div class="history-content-inner" t-out="state.selectedHistoryVersion.content_snapshot || '&lt;div style=\'text-align:center;color:#666;\'&gt;No content&lt;/div&gt;'"></div>
                                        </div>
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
            <div class="km_pro_modal_backdrop" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050;">
                <div class="km_pro_modal" style="background: #242426; border-radius: 6px; border: 1px solid #36363a; width: 600px; max-width: 90%; color: #e0e0e0; box-shadow: 0 4px 24px rgba(0,0,0,0.4);">
                    <div class="km_pro_modal_header" style="display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; border-bottom: 1px solid transparent;">
                        <h4 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #ffffff;">Insert a Kanban View</h4>
                        <i class="fa fa-times" style="cursor: pointer; font-size: 1.1rem; color: #a0a0a0;" t-on-click="() => this.state.showKanbanDialog = false"></i>
                    </div>
                    <div class="km_pro_modal_body" style="padding: 10px 24px 24px;">
                        <div style="display: flex; align-items: center; gap: 16px;">
                            <label style="font-size: 0.95rem; white-space: nowrap; color: #e0e0e0;">What items do you want to manage?</label>
                            <input type="text" t-model="state.kanbanItemName" placeholder="e.g. Buildings" style="flex: 1; background: transparent; border: 1px solid #005a5a; color: #fff; padding: 8px 12px; border-radius: 2px; outline: none; font-size: 0.95rem;" />
                        </div>
                    </div>
                    <div class="km_pro_modal_footer" style="padding: 16px 24px 24px; display: flex; gap: 12px;">
                        <button t-on-click="insertKanban" style="background: #7f4a7c; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.95rem;">Insert</button>
                        <button t-on-click="() => this.state.showKanbanDialog = false" style="background: #3f3f46; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.95rem;">Discard</button>
                    </div>
                </div>
            </div>
        </t>

        <t t-if="state.showListDialog">
            <div class="km_pro_modal_backdrop" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050;">
                <div class="km_pro_modal" style="background: #242426; border-radius: 6px; border: 1px solid #36363a; width: 600px; max-width: 90%; color: #e0e0e0; box-shadow: 0 4px 24px rgba(0,0,0,0.4);">
                    <div class="km_pro_modal_header" style="display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; border-bottom: 1px solid transparent;">
                        <h4 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #ffffff;">Insert a List View</h4>
                        <i class="fa fa-times" style="cursor: pointer; font-size: 1.1rem; color: #a0a0a0;" t-on-click="() => this.state.showListDialog = false"></i>
                    </div>
                    <div class="km_pro_modal_body" style="padding: 10px 24px 24px;">
                        <div style="display: flex; align-items: center; gap: 16px;">
                            <label style="font-size: 0.95rem; white-space: nowrap; color: #e0e0e0;">What items do you want to manage?</label>
                            <input type="text" t-model="state.listItemName" placeholder="e.g. Todos" style="flex: 1; background: transparent; border: 1px solid #005a5a; color: #fff; padding: 8px 12px; border-radius: 2px; outline: none; font-size: 0.95rem;" t-on-keydown="(ev) => ev.key === 'Enter' and this.insertList()" autofocus="autofocus" />
                        </div>
                    </div>
                    <div class="km_pro_modal_footer" style="padding: 16px 24px 24px; display: flex; gap: 12px;">
                        <button t-on-click="insertList" style="background: #7f4a7c; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.95rem;">Insert</button>
                        <button t-on-click="() => this.state.showListDialog = false" style="background: #3f3f46; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.95rem;">Discard</button>
                    </div>
                </div>
            </div>
        </t>

        <t t-if="state.showCalendarDialog">
            <div class="km_pro_modal_backdrop" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050;">
                <div class="km_pro_modal" style="background: #242426; border-radius: 6px; border: 1px solid #36363a; width: 600px; max-width: 90%; color: #e0e0e0; box-shadow: 0 4px 24px rgba(0,0,0,0.4);">
                    <div class="km_pro_modal_header" style="display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; border-bottom: 1px solid transparent;">
                        <h4 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #ffffff;">Insert a Calendar View</h4>
                        <i class="fa fa-times" style="cursor: pointer; font-size: 1.1rem; color: #a0a0a0;" t-on-click="() => this.state.showCalendarDialog = false"></i>
                    </div>
                    <div class="km_pro_modal_body" style="padding: 10px 24px 24px;">
                        <div style="display: flex; align-items: center; gap: 16px;">
                            <label style="font-size: 0.95rem; white-space: nowrap; color: #e0e0e0;">What do you want to manage?</label>
                            <input type="text" t-model="state.calendarItemName" placeholder="e.g. Meetings" style="flex: 1; background: transparent; border: 1px solid #005a5a; color: #fff; padding: 8px 12px; border-radius: 2px; outline: none; font-size: 0.95rem;" t-on-keydown="(ev) => ev.key === 'Enter' and this.insertCalendar()" autofocus="autofocus" />
                        </div>
                    </div>
                    <div class="km_pro_modal_footer" style="padding: 16px 24px 24px; display: flex; gap: 12px;">
                        <button t-on-click="insertCalendar" style="background: #7f4a7c; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.95rem;">Insert</button>
                        <button t-on-click="() => this.state.showCalendarDialog = false" style="background: #3f3f46; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.95rem;">Discard</button>
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
                        <div class="invite-row permission-underline-row">
                            <div class="invite-permission-trigger" t-on-click="() => state.isInvitePermissionDropdownOpen = !state.isInvitePermissionDropdownOpen" style="display: flex; justify-content: space-between; align-items: center; position: relative;">
                                <span class="permission-text-plain" style="background-color: #1a4b8c; padding: 0 4px;"><t t-esc="state.invitePermission"/></span>
                                <t t-if="state.isInvitePermissionDropdownOpen">
                                    <div class="km_pro_nested_dropdown" style="top: 100%; right: 0;">
                                        <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.invitePermission = 'Can edit'; state.isInvitePermissionDropdownOpen = false; }">Can edit</div>
                                        <div class="nested-item" t-on-click="(ev) => { ev.stopPropagation(); state.invitePermission = 'Can read'; state.isInvitePermissionDropdownOpen = false; }">Can read</div>
                                    </div>
                                </t>
                            </div>
                        </div>
                        
                        <div class="invite-row" style="flex-direction: column; align-items: stretch; margin-top: 16px;">
                            <div class="km_pro_selected_users" style="display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px;">
                                <t t-foreach="state.selectedUsersToInvite" t-as="user" t-key="user.id">
                                    <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 12px; font-size: 0.85rem; display: flex; align-items: center; gap: 6px;">
                                        <t t-esc="user.name" />
                                        <i class="fa fa-times" style="cursor: pointer;" t-on-click="() => this.removeSelectedUser(user)"></i>
                                    </span>
                                </t>
                            </div>
                            
                            <div style="position: relative;">
                                <input type="text" class="invite-input-borderless" placeholder="Search people..." t-model="state.inviteSearchQuery" style="width: 100%; border: 1px solid #36363a; border-radius: 4px; padding: 8px; background: transparent; color: #fff;" />
                                
                                <t t-if="filteredUsersToInvite.length > 0">
                                    <div class="km_pro_user_dropdown" style="position: absolute; top: 100%; left: 0; width: 100%; background: #2b2b30; border: 1px solid #36363a; border-radius: 4px; max-height: 150px; overflow-y: auto; z-index: 10;">
                                        <t t-foreach="filteredUsersToInvite" t-as="user" t-key="user.id">
                                            <div class="km_pro_user_dropdown_item" style="padding: 8px; cursor: pointer; border-bottom: 1px solid #36363a; transition: background 0.2s;" t-on-click="() => this.selectUserToInvite(user)" onmouseover="this.style.background='rgba(255,255,255,0.05)'" onmouseout="this.style.background='transparent'">
                                                <t t-esc="user.name" /> <span style="color:#a0a0a0; font-size: 0.8rem;">(<t t-esc="user.email or 'No email'"/>)</span>
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
                                            <span style="font-size: 0.8rem; color: #a0a0a0; background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 4px;"><t t-esc="share.access_level === 'write' ? 'Can edit' : 'Can read'" /></span>
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

KnowledgeManagementEditor.components = { KnowledgeKanbanMockup, KnowledgeListMockup, KnowledgeCalendarMockup, Chatter, KnowledgeEmojiPicker };
