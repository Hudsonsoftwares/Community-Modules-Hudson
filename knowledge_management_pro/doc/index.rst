========================
Knowledge Management Pro
========================

Developed Module Documentation (Template article-1.1)
=====================================================

Overview
--------
The `knowledge_management_pro` module is an advanced documentation and knowledge base management system designed for Odoo. It allows users to create, organize, review, and publish articles within workspaces and categories. The module incorporates version control, auto-saving capabilities, and a structured review process.

Features
--------
1. **Article Hierarchy**: Create structured knowledge bases with parent-child article relationships using Odoo's `_parent_store` for efficient querying.
2. **Version Control & Auto-Save**: Automatically captures versions of articles during edits (configurable auto-save interval, default is 600 seconds) or when changes are made by different users.
3. **Workflow & Status**: Articles go through stages: Draft, In Review, Published, and Archived. Status changes cascade to child articles when appropriate.
4. **Access Control & Privacy**: Features comprehensive RBAC (User, Editor, Manager, Administrator). Articles can be marked private or shared with specific contacts.
5. **Rich Text Editing**: Full HTML support for article content, including attachments and cover images.
6. **Templates**: Create articles from predefined templates for consistency.
7. **Social Features**: Favoriting, bookmarking, and commenting support using `mail.thread` and custom relations.

Technical Details
-----------------
- **Model**: `knowledge.management.article`
- **Mixins Used**: `mail.thread`, `mail.activity.mixin`, `website.published.mixin`
- **Optimization**: Write operations use batched queries (`read_group`) to fetch latest versions for auto-save, avoiding N+1 performance issues in bulk updates.
- **Logging**: Implements standard Python logging (`_logger`) for recording warnings, such as attempted recursive article structures, and tracking batch creations of versions.

Configuration
-------------
No special configuration is required to start using the module.
- Ensure that users are added to the appropriate security groups (`User`, `Editor`, `Manager`, `Administrator`) to control read/write access.
- The `AUTO_SAVE_INTERVAL` is currently set to a constant in `article.py` (600 seconds).

Dependencies
------------
Depends on standard Odoo modules: `base`, `mail`, `web`, `portal`, `website`.
