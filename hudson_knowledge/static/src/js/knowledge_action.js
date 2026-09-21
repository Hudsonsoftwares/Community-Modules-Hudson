/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import {
    Component,
    useState,
    useRef,
    onMounted,
    onWillStart,
    onWillUnmount,
    markup,
} from "@odoo/owl";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { KnowledgeEditorPlugin } from "./knowledge_wysiwyg_commands";
import { usePopover } from "@web/core/popover/popover_hook";
import { EmojiPicker, loader } from "@web/core/emoji_picker/emoji_picker";
import { MediaDialog } from "@html_editor/main/media/media_dialog/media_dialog";

function cleanHtmlContent(html) {
    if (!html || !html.trim()) {
        return `<h1><br></h1><p><br></p>`;
    }
    let str = String(html).trim();
    let passes = 0;
    while (passes < 3 && /&lt;\/?(h[1-6]|p|div|span|ul|ol|li|strong|em|table|tr|td|th|b|i|u|a|blockquote|pre|code|br|hr)\b/i.test(str)) {
        str = str
            .replace(/&lt;/g, "<")
            .replace(/&gt;/g, ">")
            .replace(/&amp;/g, "&")
            .replace(/&quot;/g, '"')
            .replace(/&#39;/g, "'");
        passes++;
    }

    // Strip any legacy data-placeholder attributes
    str = str.replace(/\s*data-placeholder="[^"]*"/gi, "");

    if (!/<h1\b/i.test(str)) {
        str = `<h1><br></h1>` + str;
    }
    return str;
}

function getInitialArticleHtml() {
    return `<h1><br></h1><p><br></p>`;
}

function updateEmptyHeadingClasses(root) {
    if (!root) return;
    const headings = root.querySelectorAll("h1, h2, h3");
    for (const h of headings) {
        const text = (h.textContent || "").replace(/[\n\r\uFEFF\s]/g, "");
        if (text.length === 0) {
            h.classList.add("o_empty_heading");
        } else {
            h.classList.remove("o_empty_heading");
        }
    }
}

function computeHtmlDiff(olderHtml, currentHtml) {
    if (!olderHtml && !currentHtml) return "";
    if (olderHtml === currentHtml) return currentHtml;

    const tokenize = (html) => {
        const tokens = [];
        const regex = /(<[^>]+>|[^<>\s]+|\s+)/g;
        let match;
        while ((match = regex.exec(html)) !== null) {
            tokens.push(match[0]);
        }
        return tokens;
    };

    const oldTokens = tokenize(olderHtml || "");
    const curTokens = tokenize(currentHtml || "");

    const m = Math.min(oldTokens.length, 1500);
    const n = Math.min(curTokens.length, 1500);

    const dp = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            if (oldTokens[i - 1] === curTokens[j - 1]) {
                dp[i][j] = dp[i - 1][j - 1] + 1;
            } else {
                dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
            }
        }
    }

    let i = m, j = n;
    const result = [];
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && oldTokens[i - 1] === curTokens[j - 1]) {
            result.unshift(oldTokens[i - 1]);
            i--;
            j--;
        } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
            const tok = curTokens[j - 1];
            if (tok.startsWith("<")) {
                result.unshift(tok);
            } else if (tok.trim().length > 0) {
                result.unshift(`<ins class="o_diff_ins">${tok}</ins>`);
            } else {
                result.unshift(tok);
            }
            j--;
        } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
            const tok = oldTokens[i - 1];
            if (!tok.startsWith("<") && tok.trim().length > 0) {
                result.unshift(`<del class="o_diff_del">${tok}</del>`);
            }
            i--;
        }
    }
    return result.join("");
}

// ─────────────────────────────────────────────────────────────────
// Embedded View Component (Kanban / List / Calendar inside article)
// ─────────────────────────────────────────────────────────────────
export class KnowledgeEmbeddedView extends Component {
    static template = "hudson_knowledge.KnowledgeEmbeddedView";
    static props = {
        articleId: Number,
        viewRefId: String,
        viewType: String,
        viewName: { type: String, optional: true },
        isLocked: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            items: [],
            stages: [],
            calYear: new Date().getFullYear(),
            calMonth: new Date().getMonth(),
            showItemModal: false,
            modalTitle: "",
            modalValue: "",
        });
        this._modalResolver = null;
        onMounted(async () => {
            await this.loadData();
        });
    }

    promptDialog({ title, defaultValue = "" }) {
        return new Promise((resolve) => {
            this.state.modalTitle = title || "Item Details";
            this.state.modalValue = defaultValue || "";
            this.state.showItemModal = true;
            this._modalResolver = resolve;
        });
    }

    onConfirmModal() {
        const val = (this.state.modalValue || "").trim();
        this.state.showItemModal = false;
        if (this._modalResolver) {
            this._modalResolver(val);
            this._modalResolver = null;
        }
    }

    onCloseModal() {
        this.state.showItemModal = false;
        if (this._modalResolver) {
            this._modalResolver(null);
            this._modalResolver = null;
        }
    }

    async loadData() {
        try {
            const [items, stages] = await Promise.all([
                this.orm.call(
                    "knowledge.management.item",
                    "get_items_for_view",
                    [this.props.articleId, this.props.viewRefId]
                ),
                this.orm.call(
                    "knowledge.management.item",
                    "get_stages_for_view",
                    [this.props.articleId]
                ),
            ]);
            this.state.items = items || [];
            this.state.stages = stages || [];
        } catch (e) {
            console.error("Failed to load embedded view data", e);
        }
    }

    get items() { return this.state.items; }
    get stages() { return this.state.stages; }
    get viewType() { return this.props.viewType; }
    get viewRefId() { return this.props.viewRefId; }
    get viewName() { return this.props.viewName || "Items"; }

    getItemsForStage(stageId) {
        return this.state.items.filter(i => i.stage_id === stageId);
    }

    getMonthLabel() {
        return new Date(this.state.calYear, this.state.calMonth, 1)
            .toLocaleDateString("en-US", { month: "long", year: "numeric" });
    }

    prevMonth() {
        if (this.state.calMonth === 0) {
            this.state.calMonth = 11;
            this.state.calYear--;
        } else {
            this.state.calMonth--;
        }
    }

    nextMonth() {
        if (this.state.calMonth === 11) {
            this.state.calMonth = 0;
            this.state.calYear++;
        } else {
            this.state.calMonth++;
        }
    }

    get calendarCells() {
        const { calYear, calMonth } = this.state;
        const firstDay = new Date(calYear, calMonth, 1).getDay();
        const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
        const today = new Date();

        const cells = [];
        for (let i = 0; i < firstDay; i++) {
            cells.push({ day: null, events: [], isEmpty: true });
        }
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${calYear}-${String(calMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const isToday =
                d === today.getDate() &&
                calMonth === today.getMonth() &&
                calYear === today.getFullYear();
            const events = this.state.items.filter(
                i => i.date && i.date.startsWith(dateStr.substring(0, 10))
            );
            cells.push({ day: d, dateStr, events, isToday, isEmpty: false });
        }
        return cells;
    }

    getCellClass(cell) {
        const classes = [];
        if (cell.isEmpty) classes.push("o_knowledge_cal_empty");
        if (cell.isToday) classes.push("o_knowledge_cal_today");
        return classes.join(" ");
    }

    onCalendarDayClick(cell) {
        if (!cell.day || this.props.isLocked) return;
        this.openItemDialog(null, { date: cell.dateStr });
    }

    async onAddItem() {
        if (this.props.isLocked) return;
        await this.openItemDialog(null, {});
    }

    async onAddItemToStage(stageId) {
        if (this.props.isLocked) return;
        await this.openItemDialog(null, { stage_id: stageId });
    }

    async onEditItem(itemId) {
        await this.openItemDialog(itemId, {});
    }

    async openItemDialog(itemId, defaults) {
        const name = await this.promptDialog({
            title: itemId ? "Edit Item Name" : "New Item Name",
            defaultValue: "",
        });
        if (!name) return;

        if (itemId) {
            await this.orm.write("knowledge.management.item", [itemId], { name });
        } else {
            await this.orm.create("knowledge.management.item", [{
                name,
                article_id: this.props.articleId,
                view_ref_id: this.props.viewRefId,
                view_type: this.props.viewType,
                stage_id: defaults.stage_id || false,
                date: defaults.date || false,
            }]);
        }
        await this.loadData();
    }

    async onAddStage() {
        if (this.props.isLocked) return;
        const name = await this.promptDialog({
            title: "New Stage Name",
            defaultValue: "",
        });
        if (!name) return;
        await this.orm.create("knowledge.management.item.stage", [{
            name,
            article_id: this.props.articleId,
        }]);
        await this.loadData();
    }
}

// ─────────────────────────────────────────────────────────────────
// Knowledge Emoji Picker Component (Integrated, Zero-Crash)
// ─────────────────────────────────────────────────────────────────
const EMOJI_CATEGORIES = [
    { id: "smileys", name: "Smileys & Emotion", icon: "😀" },
    { id: "people", name: "People & Body", icon: "👍" },
    { id: "nature", name: "Animals & Nature", icon: "🐱" },
    { id: "food", name: "Food & Drink", icon: "🍕" },
    { id: "travel", name: "Travel & Places", icon: "🚗" },
    { id: "activities", name: "Activities", icon: "⚽" },
    { id: "objects", name: "Objects", icon: "💡" },
    { id: "symbols", name: "Symbols", icon: "❤️" },
    { id: "flags", name: "Flags", icon: "🚩" },
];

const EMOJI_DATA = [
    // Smileys & Emotion
    { emoji: "😀", name: "grinning face", cat: "smileys" },
    { emoji: "😃", name: "smiling face with big eyes", cat: "smileys" },
    { emoji: "😄", name: "smiling face with smiling eyes", cat: "smileys" },
    { emoji: "😁", name: "beaming face with smiling eyes", cat: "smileys" },
    { emoji: "😆", name: "grinning squinting face", cat: "smileys" },
    { emoji: "😅", name: "grinning face with sweat", cat: "smileys" },
    { emoji: "🤣", name: "rolling on the floor laughing", cat: "smileys" },
    { emoji: "😂", name: "face with tears of joy", cat: "smileys" },
    { emoji: "🙂", name: "slightly smiling face", cat: "smileys" },
    { emoji: "🙃", name: "upside-down face", cat: "smileys" },
    { emoji: "😉", name: "winking face", cat: "smileys" },
    { emoji: "😊", name: "smiling face with smiling eyes", cat: "smileys" },
    { emoji: "😇", name: "smiling face with halo", cat: "smileys" },
    { emoji: "🥰", name: "smiling face with hearts", cat: "smileys" },
    { emoji: "😍", name: "smiling face with heart-eyes", cat: "smileys" },
    { emoji: "🤩", name: "star-struck", cat: "smileys" },
    { emoji: "😘", name: "face blowing a kiss", cat: "smileys" },
    { emoji: "😗", name: "kissing face", cat: "smileys" },
    { emoji: "😚", name: "kissing face with closed eyes", cat: "smileys" },
    { emoji: "😙", name: "kissing face with smiling eyes", cat: "smileys" },
    { emoji: "😋", name: "face savoring food", cat: "smileys" },
    { emoji: "😛", name: "face with tongue", cat: "smileys" },
    { emoji: "😜", name: "winking face with tongue", cat: "smileys" },
    { emoji: "🤪", name: "zany face", cat: "smileys" },
    { emoji: "😝", name: "squinting face with tongue", cat: "smileys" },
    { emoji: "🤑", name: "money-mouth face", cat: "smileys" },
    { emoji: "🤗", name: "smiling face with open hands", cat: "smileys" },
    { emoji: "🤭", name: "face with hand over mouth", cat: "smileys" },
    { emoji: "🤫", name: "shushing face", cat: "smileys" },
    { emoji: "🤔", name: "thinking face", cat: "smileys" },
    { emoji: "🤐", name: "zipper-mouth face", cat: "smileys" },
    { emoji: "🤨", name: "face with raised eyebrow", cat: "smileys" },
    { emoji: "😐", name: "neutral face", cat: "smileys" },
    { emoji: "😑", name: "expressionless face", cat: "smileys" },
    { emoji: "😶", name: "face without mouth", cat: "smileys" },
    { emoji: "😏", name: "smirking face", cat: "smileys" },
    { emoji: "😒", name: "unamused face", cat: "smileys" },
    { emoji: "🙄", name: "face with rolling eyes", cat: "smileys" },
    { emoji: "😬", name: "grimacing face", cat: "smileys" },
    { emoji: "🤥", name: "lying face", cat: "smileys" },
    { emoji: "😌", name: "relieved face", cat: "smileys" },
    { emoji: "😔", name: "pensive face", cat: "smileys" },
    { emoji: "😪", name: "sleepy face", cat: "smileys" },
    { emoji: "🤤", name: "drooling face", cat: "smileys" },
    { emoji: "😴", name: "sleeping face", cat: "smileys" },
    { emoji: "😷", name: "face with medical mask", cat: "smileys" },
    { emoji: "🤒", name: "face with thermometer", cat: "smileys" },
    { emoji: "🤕", name: "face with head-bandage", cat: "smileys" },
    { emoji: "🤢", name: "nauseated face", cat: "smileys" },
    { emoji: "🤮", name: "face vomiting", cat: "smileys" },
    { emoji: "🥵", name: "hot face", cat: "smileys" },
    { emoji: "🥶", name: "cold face", cat: "smileys" },
    { emoji: "🥴", name: "woozy face", cat: "smileys" },
    { emoji: "😵", name: "knocked-out face", cat: "smileys" },
    { emoji: "🤯", name: "exploding head", cat: "smileys" },
    { emoji: "🥳", name: "partying face", cat: "smileys" },
    { emoji: "😎", name: "smiling face with sunglasses", cat: "smileys" },
    { emoji: "🤓", name: "nerd face", cat: "smileys" },
    { emoji: "🧐", name: "face with monocle", cat: "smileys" },
    { emoji: "😕", name: "confused face", cat: "smileys" },
    { emoji: "😟", name: "worried face", cat: "smileys" },
    { emoji: "🙁", name: "slightly frowning face", cat: "smileys" },
    { emoji: "😮", name: "face with open mouth", cat: "smileys" },
    { emoji: "😯", name: "hushed face", cat: "smileys" },
    { emoji: "😲", name: "astonished face", cat: "smileys" },
    { emoji: "😳", name: "flushed face", cat: "smileys" },
    { emoji: "🥺", name: "pleading face", cat: "smileys" },
    { emoji: "😦", name: "frowning face with open mouth", cat: "smileys" },
    { emoji: "😧", name: "anguished face", cat: "smileys" },
    { emoji: "😨", name: "fearful face", cat: "smileys" },
    { emoji: "😰", name: "anxious face with sweat", cat: "smileys" },
    { emoji: "😥", name: "sad but relieved face", cat: "smileys" },
    { emoji: "😢", name: "crying face", cat: "smileys" },
    { emoji: "😭", name: "loudly crying face", cat: "smileys" },
    { emoji: "😱", name: "face screaming in fear", cat: "smileys" },
    { emoji: "😖", name: "confounded face", cat: "smileys" },
    { emoji: "😣", name: "persevering face", cat: "smileys" },
    { emoji: "😞", name: "disappointed face", cat: "smileys" },
    { emoji: "😓", name: "downcast face with sweat", cat: "smileys" },
    { emoji: "😩", name: "weary face", cat: "smileys" },
    { emoji: "😫", name: "tired face", cat: "smileys" },
    { emoji: "🥱", name: "yawning face", cat: "smileys" },
    { emoji: "😤", name: "face with steam from nose", cat: "smileys" },
    { emoji: "😡", name: "pouting face", cat: "smileys" },
    { emoji: "😠", name: "angry face", cat: "smileys" },
    { emoji: "🤬", name: "face with symbols on mouth", cat: "smileys" },
    { emoji: "😈", name: "smiling face with horns", cat: "smileys" },
    { emoji: "👿", name: "angry face with horns", cat: "smileys" },
    { emoji: "💀", name: "skull", cat: "smileys" },
    { emoji: "💩", name: "pile of poo", cat: "smileys" },
    { emoji: "🤡", name: "clown face", cat: "smileys" },
    { emoji: "👹", name: "ogre", cat: "smileys" },
    { emoji: "👺", name: "goblin", cat: "smileys" },
    { emoji: "👻", name: "ghost", cat: "smileys" },
    { emoji: "👽", name: "alien", cat: "smileys" },
    { emoji: "🤖", name: "robot", cat: "smileys" },
    { emoji: "😺", name: "grinning cat", cat: "smileys" },
    { emoji: "😸", name: "grinning cat with smiling eyes", cat: "smileys" },
    { emoji: "😹", name: "cat with tears of joy", cat: "smileys" },
    { emoji: "😻", name: "smiling cat with heart-eyes", cat: "smileys" },
    { emoji: "😼", name: "cat with wry smile", cat: "smileys" },
    { emoji: "😽", name: "kissing cat", cat: "smileys" },
    { emoji: "🙀", name: "weary cat", cat: "smileys" },
    { emoji: "😿", name: "crying cat", cat: "smileys" },
    { emoji: "😾", name: "pouting cat", cat: "smileys" },
    { emoji: "🙈", name: "see-no-evil monkey", cat: "smileys" },
    { emoji: "🙉", name: "hear-no-evil monkey", cat: "smileys" },
    { emoji: "🙊", name: "speak-no-evil monkey", cat: "smileys" },

    // People & Body
    { emoji: "👋", name: "waving hand", cat: "people" },
    { emoji: "✋", name: "raised hand", cat: "people" },
    { emoji: "👌", name: "OK hand", cat: "people" },
    { emoji: "🤌", name: "pinched fingers", cat: "people" },
    { emoji: "🤏", name: "pinching hand", cat: "people" },
    { emoji: "✌️", name: "victory hand", cat: "people" },
    { emoji: "🤞", name: "crossed fingers", cat: "people" },
    { emoji: "🤟", name: "love-you gesture", cat: "people" },
    { emoji: "🤘", name: "sign of the horns", cat: "people" },
    { emoji: "🤙", name: "call me hand", cat: "people" },
    { emoji: "👈", name: "backhand index pointing left", cat: "people" },
    { emoji: "👉", name: "backhand index pointing right", cat: "people" },
    { emoji: "👆", name: "backhand index pointing up", cat: "people" },
    { emoji: "👇", name: "backhand index pointing down", cat: "people" },
    { emoji: "☝️", name: "index pointing up", cat: "people" },
    { emoji: "👍", name: "thumbs up", cat: "people" },
    { emoji: "👎", name: "thumbs down", cat: "people" },
    { emoji: "✊", name: "raised fist", cat: "people" },
    { emoji: "👊", name: "oncoming fist", cat: "people" },
    { emoji: "👏", name: "clapping hands", cat: "people" },
    { emoji: "🙌", name: "raising hands", cat: "people" },
    { emoji: "👐", name: "open hands", cat: "people" },
    { emoji: "🤲", name: "palms up together", cat: "people" },
    { emoji: "🤝", name: "handshake", cat: "people" },
    { emoji: "🙏", name: "folded hands", cat: "people" },
    { emoji: "✍️", name: "writing hand", cat: "people" },
    { emoji: "💪", name: "flexed biceps", cat: "people" },
    { emoji: "🧠", name: "brain", cat: "people" },
    { emoji: "👀", name: "eyes", cat: "people" },

    // Animals & Nature
    { emoji: "🐶", name: "dog face", cat: "nature" },
    { emoji: "🐱", name: "cat face", cat: "nature" },
    { emoji: "🐭", name: "mouse face", cat: "nature" },
    { emoji: "🐹", name: "hamster face", cat: "nature" },
    { emoji: "🐰", name: "rabbit face", cat: "nature" },
    { emoji: "🦊", name: "fox", cat: "nature" },
    { emoji: "🐻", name: "bear", cat: "nature" },
    { emoji: "🐼", name: "panda", cat: "nature" },
    { emoji: "🐨", name: "koala", cat: "nature" },
    { emoji: "🐯", name: "tiger face", cat: "nature" },
    { emoji: "🦁", name: "lion", cat: "nature" },
    { emoji: "🐮", name: "cow face", cat: "nature" },
    { emoji: "🐷", name: "pig face", cat: "nature" },
    { emoji: "🐸", name: "frog", cat: "nature" },
    { emoji: "🐵", name: "monkey face", cat: "nature" },
    { emoji: "🐔", name: "chicken", cat: "nature" },
    { emoji: "🐧", name: "penguin", cat: "nature" },
    { emoji: "🐦", name: "bird", cat: "nature" },
    { emoji: "🦆", name: "duck", cat: "nature" },
    { emoji: "🦅", name: "eagle", cat: "nature" },
    { emoji: "🦉", name: "owl", cat: "nature" },
    { emoji: "🦄", name: "unicorn", cat: "nature" },
    { emoji: "🐝", name: "honeybee", cat: "nature" },
    { emoji: "🦋", name: "butterfly", cat: "nature" },
    { emoji: "🌸", name: "cherry blossom", cat: "nature" },
    { emoji: "🌹", name: "rose", cat: "nature" },
    { emoji: "🌻", name: "sunflower", cat: "nature" },
    { emoji: "🌲", name: "evergreen tree", cat: "nature" },
    { emoji: "🌴", name: "palm tree", cat: "nature" },
    { emoji: "🍀", name: "four leaf clover", cat: "nature" },

    // Food & Drink
    { emoji: "🍎", name: "red apple", cat: "food" },
    { emoji: "🍌", name: "banana", cat: "food" },
    { emoji: "🍉", name: "watermelon", cat: "food" },
    { emoji: "🍇", name: "grapes", cat: "food" },
    { emoji: "🍓", name: "strawberry", cat: "food" },
    { emoji: "🍒", name: "cherries", cat: "food" },
    { emoji: "🥑", name: "avocado", cat: "food" },
    { emoji: "🥕", name: "carrot", cat: "food" },
    { emoji: "🌽", name: "ear of corn", cat: "food" },
    { emoji: "🍞", name: "bread", cat: "food" },
    { emoji: "🥐", name: "croissant", cat: "food" },
    { emoji: "🧀", name: "cheese wedge", cat: "food" },
    { emoji: "🍔", name: "hamburger", cat: "food" },
    { emoji: "🍟", name: "french fries", cat: "food" },
    { emoji: "🍕", name: "pizza", cat: "food" },
    { emoji: "🌭", name: "hot dog", cat: "food" },
    { emoji: "🌮", name: "taco", cat: "food" },
    { emoji: "🍣", name: "sushi", cat: "food" },
    { emoji: "🍜", name: "steaming bowl", cat: "food" },
    { emoji: "🍦", name: "soft ice cream", cat: "food" },
    { emoji: "🎂", name: "birthday cake", cat: "food" },
    { emoji: "🍫", name: "chocolate bar", cat: "food" },
    { emoji: "☕", name: "hot beverage", cat: "food" },
    { emoji: "🍺", name: "beer mug", cat: "food" },
    { emoji: "🍷", name: "wine glass", cat: "food" },

    // Travel & Places
    { emoji: "🚗", name: "automobile", cat: "travel" },
    { emoji: "🚕", name: "taxi", cat: "travel" },
    { emoji: "🏎️", name: "racing car", cat: "travel" },
    { emoji: "🚑", name: "ambulance", cat: "travel" },
    { emoji: "🚒", name: "fire engine", cat: "travel" },
    { emoji: "🚲", name: "bicycle", cat: "travel" },
    { emoji: "✈️", name: "airplane", cat: "travel" },
    { emoji: "🚀", name: "rocket", cat: "travel" },
    { emoji: "⛵", name: "sailboat", cat: "travel" },
    { emoji: "🛸", name: "flying saucer", cat: "travel" },
    { emoji: "🏠", name: "house", cat: "travel" },
    { emoji: "🏢", name: "office building", cat: "travel" },
    { emoji: "🏥", name: "hospital", cat: "travel" },
    { emoji: "🏦", name: "bank", cat: "travel" },
    { emoji: "🏨", name: "hotel", cat: "travel" },
    { emoji: "🏖️", name: "beach with umbrella", cat: "travel" },
    { emoji: "⛰️", name: "mountain", cat: "travel" },

    // Activities
    { emoji: "⚽", name: "soccer ball", cat: "activities" },
    { emoji: "🏀", name: "basketball", cat: "activities" },
    { emoji: "🎾", name: "tennis", cat: "activities" },
    { emoji: "🏐", name: "volleyball", cat: "activities" },
    { emoji: "🥊", name: "boxing glove", cat: "activities" },
    { emoji: "🎯", name: "bullseye", cat: "activities" },
    { emoji: "🎮", name: "video game", cat: "activities" },
    { emoji: "🎨", name: "artist palette", cat: "activities" },
    { emoji: "🎸", name: "guitar", cat: "activities" },
    { emoji: "🎬", name: "clapper board", cat: "activities" },

    // Objects
    { emoji: "💡", name: "light bulb", cat: "objects" },
    { emoji: "📱", name: "mobile phone", cat: "objects" },
    { emoji: "💻", name: "laptop", cat: "objects" },
    { emoji: "📷", name: "camera", cat: "objects" },
    { emoji: "⏰", name: "alarm clock", cat: "objects" },
    { emoji: "💰", name: "money bag", cat: "objects" },
    { emoji: "💳", name: "credit card", cat: "objects" },
    { emoji: "💎", name: "gem stone", cat: "objects" },
    { emoji: "🔧", name: "wrench", cat: "objects" },
    { emoji: "🔨", name: "hammer", cat: "objects" },
    { emoji: "📦", name: "package", cat: "objects" },
    { emoji: "📄", name: "page facing up", cat: "objects" },
    { emoji: "📊", name: "bar chart", cat: "objects" },
    { emoji: "📋", name: "clipboard", cat: "objects" },
    { emoji: "📌", name: "pushpin", cat: "objects" },
    { emoji: "📎", name: "paperclip", cat: "objects" },
    { emoji: "🔒", name: "locked", cat: "objects" },
    { emoji: "🔑", name: "key", cat: "objects" },
    { emoji: "📁", name: "file folder", cat: "objects" },
    { emoji: "📅", name: "calendar", cat: "objects" },
    { emoji: "📚", name: "books", cat: "objects" },
    { emoji: "✉️", name: "envelope", cat: "objects" },
    { emoji: "✏️", name: "pencil", cat: "objects" },

    // Symbols
    { emoji: "❤️", name: "red heart", cat: "symbols" },
    { emoji: "🧡", name: "orange heart", cat: "symbols" },
    { emoji: "💛", name: "yellow heart", cat: "symbols" },
    { emoji: "💚", name: "green heart", cat: "symbols" },
    { emoji: "💙", name: "blue heart", cat: "symbols" },
    { emoji: "💜", name: "purple heart", cat: "symbols" },
    { emoji: "🖤", name: "black heart", cat: "symbols" },
    { emoji: "⭐", name: "star", cat: "symbols" },
    { emoji: "✨", name: "sparkles", cat: "symbols" },
    { emoji: "🔥", name: "fire", cat: "symbols" },
    { emoji: "🎉", name: "party popper", cat: "symbols" },
    { emoji: "🏆", name: "trophy", cat: "symbols" },
    { emoji: "🥇", name: "1st place medal", cat: "symbols" },
    { emoji: "✔️", name: "check mark", cat: "symbols" },
    { emoji: "✅", name: "check mark button", cat: "symbols" },
    { emoji: "❌", name: "cross mark", cat: "symbols" },
    { emoji: "⚠️", name: "warning", cat: "symbols" },
    { emoji: "🛑", name: "stop sign", cat: "symbols" },
    { emoji: "🔔", name: "bell", cat: "symbols" },

    // Flags
    { emoji: "🚩", name: "triangular flag", cat: "flags" },
    { emoji: "🏁", name: "chequered flag", cat: "flags" },
    { emoji: "🏳️", name: "white flag", cat: "flags" },
    { emoji: "🏴", name: "black flag", cat: "flags" },
];

export class KnowledgeEmojiPicker extends Component {
    static template = "hudson_knowledge.KnowledgeEmojiPicker";
    static props = {
        onSelect: { type: Function },
        onRemove: { type: Function, optional: true },
        close: { type: Function, optional: true },
    };

    setup() {
        this.categories = EMOJI_CATEGORIES;
        this.state = useState({
            searchTerm: "",
            activeCategory: "smileys",
            hoveredItem: null,
        });
    }

    get currentCategoryTitle() {
        if (this.state.searchTerm.trim()) {
            return "Search Results";
        }
        const cat = this.categories.find((c) => c.id === this.state.activeCategory);
        return cat ? `${cat.icon} ${cat.name}` : "Smileys & Emotion";
    }

    get displayedEmojis() {
        const term = this.state.searchTerm.trim().toLowerCase().replace(/:/g, "");
        if (term) {
            return EMOJI_DATA.filter(
                (item) => item.name.toLowerCase().includes(term) || item.emoji.includes(term)
            );
        }
        return EMOJI_DATA.filter((item) => item.cat === this.state.activeCategory);
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value;
    }

    onSelectCategory(catId) {
        this.state.activeCategory = catId;
        this.state.searchTerm = "";
    }

    onHoverEmoji(item) {
        this.state.hoveredItem = item;
    }

    onLeaveEmoji() {
        this.state.hoveredItem = null;
    }

    onSelectEmoji(emoji) {
        this.props.onSelect(emoji);
        this.props.close?.();
    }

    onRemoveEmoji(ev) {
        ev.stopPropagation();
        this.props.onRemove?.();
        this.props.close?.();
    }
}

// ── Ensure Odoo core EmojiPicker never crashes in content editor (Issue 4) ──
if (loader) {
    const origLoadEmoji = loader.loadEmoji;
    loader.loadEmoji = async () => {
        if (window.odoo?.loader?.modules?.has("@web/core/emoji_picker/emoji_data")) {
            return;
        }
        try {
            if (origLoadEmoji) await origLoadEmoji();
        } catch (e) {
            console.warn("loadEmoji bundle failed, using fallback data", e);
        }
    };
}

if (window.odoo?.loader?.modules && !window.odoo.loader.modules.has("@web/core/emoji_picker/emoji_data")) {
    const fallbackCategories = [
        { name: "Smileys & Emotion", displayName: "Smileys & Emotion", title: "😃", sortId: 1 },
        { name: "People & Body", displayName: "People & Body", title: "👋", sortId: 2 },
        { name: "Animals & Nature", displayName: "Animals & Nature", title: "🐱", sortId: 3 },
        { name: "Food & Drink", displayName: "Food & Drink", title: "🍕", sortId: 4 },
        { name: "Travel & Places", displayName: "Travel & Places", title: "🚗", sortId: 5 },
        { name: "Activities", displayName: "Activities", title: "⚽", sortId: 6 },
        { name: "Objects", displayName: "Objects", title: "💡", sortId: 7 },
        { name: "Symbols", displayName: "Symbols", title: "❤️", sortId: 8 },
        { name: "Flags", displayName: "Flags", title: "🚩", sortId: 9 },
    ];
    const fallbackEmojis = EMOJI_DATA.map((e) => ({
        name: e.name,
        codepoints: e.emoji,
        category: EMOJI_CATEGORIES.find(c => c.id === e.cat)?.name || "Smileys & Emotion",
        keywords: [e.name],
        shortcodes: [e.name.replace(/\s+/g, "_")],
        emoticons: [],
    }));
    window.odoo.loader.modules.set("@web/core/emoji_picker/emoji_data", {
        getCategories: () => fallbackCategories,
        getEmojis: () => fallbackEmojis,
    });
}

try {
    patch(EmojiPicker.prototype, {
        setup() {
            super.setup(...arguments);
            onWillStart(async () => {
                if (!this.categories || !this.categories.length) {
                    this.categories = [
                        { name: "Smileys & Emotion", displayName: "Smileys & Emotion", title: "😃", sortId: 1 },
                        { name: "People & Body", displayName: "People & Body", title: "👋", sortId: 2 },
                        { name: "Animals & Nature", displayName: "Animals & Nature", title: "🐱", sortId: 3 },
                        { name: "Food & Drink", displayName: "Food & Drink", title: "🍕", sortId: 4 },
                        { name: "Travel & Places", displayName: "Travel & Places", title: "🚗", sortId: 5 },
                        { name: "Activities", displayName: "Activities", title: "⚽", sortId: 6 },
                        { name: "Objects", displayName: "Objects", title: "💡", sortId: 7 },
                        { name: "Symbols", displayName: "Symbols", title: "❤️", sortId: 8 },
                        { name: "Flags", displayName: "Flags", title: "🚩", sortId: 9 },
                    ];
                    if (!this.state.categoryId) {
                        this.state.categoryId = 1;
                    }
                }
            });
        },
    });
} catch (e) {
    console.warn("EmojiPicker prototype patch skipped", e);
}

// ─────────────────────────────────────────────────────────────────
// Curated Unsplash Covers (Matching Images 2 & 3)
// ─────────────────────────────────────────────────────────────────
const CURATED_COVERS = [
    // Image 2: Matera ancient cave city at sunset
    {
        id: "matera",
        url: "https://images.unsplash.com/photo-1516483638261-f4dbaf036963?auto=format&fit=crop&w=1600&q=80",
        photographer: "Matera Sunset",
        category: "travel",
    },
    // Image 3: Exact 15 Car Covers with Photographer Credits
    {
        id: "car_1",
        url: "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=800&q=80",
        photographer: "Josh Berquist",
        category: "cars",
    },
    {
        id: "car_2",
        url: "https://images.unsplash.com/photo-1614162692292-7ac56d7f7f1e?auto=format&fit=crop&w=800&q=80",
        photographer: "Campbell",
        category: "cars",
    },
    {
        id: "car_3",
        url: "https://images.unsplash.com/photo-1542282088-72c9c27ed0cd?auto=format&fit=crop&w=800&q=80",
        photographer: "Olav Tvedt",
        category: "cars",
    },
    {
        id: "car_4",
        url: "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=800&q=80",
        photographer: "Erik Mclean",
        category: "cars",
    },
    {
        id: "car_5",
        url: "https://images.unsplash.com/photo-1603584173870-7f23fdae1b7a?auto=format&fit=crop&w=800&q=80",
        photographer: "Tyler Clemmensen",
        category: "cars",
    },
    {
        id: "car_6",
        url: "https://images.unsplash.com/photo-1583121274602-3e2820c69888?auto=format&fit=crop&w=800&q=80",
        photographer: "Peter Broomfield",
        category: "cars",
    },
    {
        id: "car_7",
        url: "https://images.unsplash.com/photo-1502877338535-766e1452684a?auto=format&fit=crop&w=800&q=80",
        photographer: "Ville Kaisla",
        category: "cars",
    },
    {
        id: "car_8",
        url: "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?auto=format&fit=crop&w=800&q=80",
        photographer: "Sven D",
        category: "cars",
    },
    {
        id: "car_9",
        url: "https://images.unsplash.com/photo-1525609004556-c46c7d6cf023?auto=format&fit=crop&w=800&q=80",
        photographer: "Dhiva Krishna",
        category: "cars",
    },
    {
        id: "car_10",
        url: "https://images.unsplash.com/photo-1617814076367-b759c7d7e738?auto=format&fit=crop&w=800&q=80",
        photographer: "Hyundai Motor Group",
        category: "cars",
    },
    {
        id: "car_11",
        url: "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=800&q=80",
        photographer: "Joshua Koblin",
        category: "cars",
    },
    {
        id: "car_12",
        url: "https://images.unsplash.com/photo-1617788138017-80ad40651399?auto=format&fit=crop&w=800&q=80",
        photographer: "Yuvraj Singh",
        category: "cars",
    },
    {
        id: "car_13",
        url: "https://images.unsplash.com/photo-1541348263662-e0c866661ba5?auto=format&fit=crop&w=800&q=80",
        photographer: "Evgeny",
        category: "cars",
    },
    {
        id: "car_14",
        url: "https://images.unsplash.com/photo-1511919884226-fd3cad34687c?auto=format&fit=crop&w=800&q=80",
        photographer: "Florian Schneider",
        category: "cars",
    },
    {
        id: "car_15",
        url: "https://images.unsplash.com/photo-1549399542-7e3f8b79c341?auto=format&fit=crop&w=800&q=80",
        photographer: "Lance Asper",
        category: "cars",
    },
    // Nature
    {
        id: "nature_1",
        url: "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=800&q=80",
        photographer: "Kalen Emsley",
        category: "nature",
    },
    {
        id: "nature_2",
        url: "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=800&q=80",
        photographer: "Luca Bravo",
        category: "nature",
    },
    {
        id: "nature_3",
        url: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=800&q=80",
        photographer: "Sean Oulashin",
        category: "nature",
    },
    // Architecture
    {
        id: "arch_1",
        url: "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=800&q=80",
        photographer: "Simone Hutsch",
        category: "architecture",
    },
    {
        id: "arch_2",
        url: "https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=800&q=80",
        photographer: "Dan Freeman",
        category: "architecture",
    },
    // Travel
    {
        id: "travel_1",
        url: "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=800&q=80",
        photographer: "Sprengben",
        category: "travel",
    },
    {
        id: "travel_2",
        url: "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=800&q=80",
        photographer: "Tianshu Liu",
        category: "travel",
    },
    // Space
    {
        id: "space_1",
        url: "https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=800&q=80",
        photographer: "NASA",
        category: "space",
    },
    // Minimal
    {
        id: "min_1",
        url: "https://images.unsplash.com/photo-1494438639946-1ebd1d20bf85?auto=format&fit=crop&w=800&q=80",
        photographer: "Scott Webb",
        category: "minimal",
    },
    // Abstract
    {
        id: "abs_1",
        url: "https://images.unsplash.com/photo-1541701494587-cb58502866ab?auto=format&fit=crop&w=800&q=80",
        photographer: "Geordanna Cordero",
        category: "abstract",
    },
];

// ─────────────────────────────────────────────────────────────────
// Main Knowledge Client Action
// ─────────────────────────────────────────────────────────────────
export class KnowledgeClientAction extends Component {
    static template = "hudson_knowledge.KnowledgeClientAction";
    static components = { KnowledgeEmbeddedView, Wysiwyg, KnowledgeEmojiPicker };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialogService = useService("dialog");

        this.bodyContainer = useRef("bodyContainer");
        this.kebabMenu = useRef("kebabMenu");
        this.contentArea = useRef("contentArea");
        this.insertViewNameInput = useRef("insertViewNameInput");
        this.titleEmojiRef = useRef("titleEmoji");
        this.toolbarEmojiRef = useRef("toolbarEmoji");
        this.kebabBtn = useRef("kebabBtn");
        this.coverImg = useRef("coverImg");

        this.emojiPopover = usePopover(KnowledgeEmojiPicker, {
            position: "bottom-start",
            closeOnClickOutside: true,
        });

        this.state = useState({
            loading: true,
            sidebar: {
                favorites: [],
                workspace: [],
                shared: [],
                private: [],
            },
            currentArticle: null,
            expandedIds: [],
            childrenMap: {},
            showKebab: false,
            editorKey: 0,
            showAIDialog: false,
            aiPrompt: "",
            aiPreset: "plan",
            aiGenerating: false,
            showTemplateDialog: false,
            availableTemplates: [],
            showInsertViewModal: false,
            insertViewType: "kanban",
            insertViewName: "",
            saveStatus: "saved",
            showItemPromptModal: false,
            itemPromptTitle: "",
            itemPromptLabel: "",
            itemPromptValue: "",
            itemPromptShowDelete: false,
            // Cover modal state
            showCoverModal: false,
            coverSearchQuery: "",
            coverActiveCategory: "all",
            showAddUrlTray: false,
            customCoverUrl: "",
            unsplashConfigured: false,
            coverPageLimit: 15,
            // Cover drag repositioning
            isRepositioningCover: false,
            savedCoverPosition: "50%",
            // Sidebar context menu
            sidebarMenu: {
                isOpen: false,
                article: null,
                x: 0,
                y: 0,
            },
            // Version History modal state (Matching Image 1)
            showHistoryModal: false,
            historyVersions: [],
            selectedHistoryVersion: null,
            historyShowComparison: true,
            historyIsFullscreen: false,
            historyLoading: false,
        });

        this._autoSaveTimer = null;
        this._lastSavedTitle = "";
        this._lastSavedBodyHtml = "";
        this._savedRange = null;
        this._lastTargetBlock = null;
        this._targetInsertionBlock = null;
        this._itemPromptResolver = null;
        this.editor = null;

        this._onDocSelectionChange = () => {
            if (!this.editor?.editable) return;
            const sel = window.getSelection();
            if (sel && sel.anchorNode && this.editor.editable.contains(sel.anchorNode)) {
                let curr = sel.anchorNode.nodeType === Node.ELEMENT_NODE ? sel.anchorNode : sel.anchorNode.parentElement;
                while (curr && curr.parentElement && curr.parentElement !== this.editor.editable) {
                    curr = curr.parentElement;
                }
                if (curr && curr.parentElement === this.editor.editable) {
                    this._lastTargetBlock = curr;
                }
            }
        };

        onMounted(async () => {
            await this._loadSidebar();
            const resId = this.props.action?.params?.res_id;
            if (resId) {
                await this.openArticle(resId);
            } else {
                const topId = await this.orm.call(
                    "knowledge.management.article",
                    "get_top_article",
                    []
                );
                if (topId) {
                    await this.openArticle(topId);
                } else {
                    this.state.loading = false;
                }
            }
            document.addEventListener("click", this._onDocumentClick.bind(this));
            document.addEventListener("selectionchange", this._onDocSelectionChange);
        });

        onWillUnmount(() => {
            document.removeEventListener("click", this._onDocumentClick.bind(this));
            document.removeEventListener("selectionchange", this._onDocSelectionChange);
            if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);
            this.editor = null;
        });
    }

    // ── Editor Configuration & Keys ───────────────────────────────

    get wysiwygKey() {
        return `art_${this.state.currentArticle?.id || 0}_${this.state.editorKey}`;
    }

    get editorConfig() {
        const article = this.state.currentArticle;
        let bodyHtml = article?.body_html || "";
        bodyHtml = cleanHtmlContent(bodyHtml);

        return {
            content: markup(bodyHtml),
            Plugins: [
                ...MAIN_PLUGINS,
                KnowledgeEditorPlugin,
            ],
            knowledgeAction: this,
            classList: ["o_knowledge_body", "note-editable"],
            onChange: () => this.onEditorChange(),
            dropImageAsAttachment: true,
            direction: "ltr",
            baseContainers: ["DIV", "P"],
        };
    }

    getReadonlyBody() {
        return markup(cleanHtmlContent(this.state.currentArticle?.body_html || ""));
    }

    async onEditorLoad(editor) {
        this.editor = editor;
        const artId = this.state.currentArticle?.id;
        setTimeout(() => {
            if (this.editor?.editable && this.state.currentArticle) {
                updateEmptyHeadingClasses(this.editor.editable);
                this.editor.editable.addEventListener("input", () => {
                    updateEmptyHeadingClasses(this.editor.editable);
                    this.onEditorChange();
                });
                const savePointerLocation = (ev) => {
                    let target = ev?.target;
                    if (!target && window.getSelection) {
                        const sel = window.getSelection();
                        if (sel && sel.anchorNode) {
                            target = sel.anchorNode.nodeType === Node.ELEMENT_NODE ? sel.anchorNode : sel.anchorNode.parentElement;
                        }
                    }
                    if (target && this.editor?.editable?.contains(target)) {
                        let curr = target;
                        while (curr && curr.parentElement && curr.parentElement !== this.editor.editable) {
                            curr = curr.parentElement;
                        }
                        if (curr && curr.parentElement === this.editor.editable) {
                            this._lastTargetBlock = curr;
                        }
                    }
                    this._savedRange = this._getEditorSelectionRange();
                };
                this.editor.editable.addEventListener("mouseup", savePointerLocation);
                this.editor.editable.addEventListener("keyup", savePointerLocation);
                this.editor.editable.addEventListener("click", savePointerLocation);
            }
        }, 40);
        this._ensureEmbeddedViewsRendered(artId);
    }

    async _ensureEmbeddedViewsRendered(articleId, attempts = 0) {
        if (!articleId) return;
        if (!this.editor?.editable || !document.body.contains(this.editor.editable)) {
            if (attempts < 30) {
                setTimeout(() => this._ensureEmbeddedViewsRendered(articleId, attempts + 1), 50);
            }
            return;
        }
        if (this.state.currentArticle?.id !== articleId) return;
        await this._renderEmbeddedViews(this.editor.editable, articleId);
        // Double check after 180ms to ensure any delayed DOM attach didn't wipe views
        if (attempts === 0) {
            setTimeout(() => {
                if (this.editor?.editable && this.state.currentArticle?.id === articleId) {
                    const emptyBoxes = this.editor.editable.querySelectorAll(
                        ".o_knowledge_embedded_view_container:empty, .o_knowledge_embedded_view_block:empty"
                    );
                    if (emptyBoxes.length > 0) {
                        this._renderEmbeddedViews(this.editor.editable, articleId);
                    }
                }
            }, 180);
        }
    }

    onToolbarTitleInput(ev) {
        if (!this.state.currentArticle) return;
        const val = ev.target.value;
        this.state.currentArticle.name = val;
        this._syncArticleToSidebar(this.state.currentArticle.id, { name: val || "Untitled" });
        this.state.saveStatus = "unsaved";
        if (this.editor?.editable) {
            const h1 = this.editor.editable.querySelector("h1");
            if (h1 && h1.innerText.trim() !== val.trim()) {
                h1.innerText = val;
            }
            updateEmptyHeadingClasses(this.editor.editable);
        }
        this._scheduleAutoSave(false);
    }

    onToolbarTitleChange(ev) {
        if (!this.state.currentArticle) return;
        const val = ev.target.value.trim() || "Untitled";
        this.state.currentArticle.name = val;
        this._syncArticleToSidebar(this.state.currentArticle.id, { name: val });
        this.state.saveStatus = "unsaved";
        this._scheduleAutoSave(true);
    }

    onCloseArticle() {
        this.state.currentArticle = null;
    }

    async onDiscardChanges() {
        if (!this.state.currentArticle) return;
        if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);
        this._autoSaveTimer = null;
        this.state.saveStatus = "saved";
        await this.openArticle(this.state.currentArticle.id);
        this.notification.add("Changes discarded", { type: "info" });
    }

    async onForceSave() {
        if (!this.state.currentArticle) return;
        if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);
        this._autoSaveTimer = null;
        let content = this.state.currentArticle.body_html;
        if (this.editor?.editable) {
            const el = this.editor.getElContent ? this.editor.getElContent() : null;
            if (el) content = el.innerHTML;
        }
        const title = this.state.currentArticle.name || "Untitled";
        await this.orm.write("knowledge.management.article", [this.state.currentArticle.id], {
            name: title,
            body_html: content,
        });
        this._lastSavedTitle = title;
        this._lastSavedBodyHtml = content;
        await this._loadSidebar();
        this.state.saveStatus = "saved";
        this.notification.add("All changes saved!", { type: "info" });
    }

    onEditorBlur() {
        if (!this.editor || this.editor.isDestroyed || !this.editor.editable || !this.state.currentArticle) {
            return;
        }
        try {
            updateEmptyHeadingClasses(this.editor.editable);
            const el = this.editor.getElContent ? this.editor.getElContent() : null;
            const content = el?.innerHTML;
            if (content !== undefined) {
                this.state.currentArticle.body_html = content;
                this._syncTitleFromEditor();
                this._scheduleAutoSave(true);
            }
        } catch (e) {
            console.warn("Editor blur save skipped:", e);
        }
    }

    onEditorChange() {
        if (!this.editor || this.editor.isDestroyed || !this.editor.editable || !this.state.currentArticle) {
            return;
        }
        try {
            updateEmptyHeadingClasses(this.editor.editable);
            const el = this.editor.getElContent ? this.editor.getElContent() : null;
            const content = el?.innerHTML;
            if (content !== undefined) {
                this.state.currentArticle.body_html = content;
                this._syncTitleFromEditor();

                const currentTitle = (this.state.currentArticle.name || "Untitled").trim();
                const hasChanges = (content !== this._lastSavedBodyHtml) || (currentTitle !== this._lastSavedTitle);
                if (hasChanges) {
                    this.state.saveStatus = "unsaved";
                    this._scheduleAutoSave(false);
                }
            }
        } catch (e) {
            console.warn("Editor change save skipped:", e);
        }
    }

    _syncTitleFromEditor() {
        if (!this.editor?.editable || !this.state.currentArticle) return;
        const h1 = this.editor.editable.querySelector("h1");
        const titleText = h1 ? h1.innerText.replace(/[\n\r]/g, "").trim() : "";
        const title = titleText || "Untitled";
        if (this.state.currentArticle.name !== title) {
            this.state.currentArticle.name = title;
            this._syncArticleToSidebar(this.state.currentArticle.id, { name: title });
            this._scheduleAutoSave(false);
        }
    }

    _scheduleAutoSave(immediate = false) {
        if (!this.state.currentArticle) return;
        const articleId = this.state.currentArticle.id;
        if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);

        const delay = immediate ? 50 : 800;
        this._autoSaveTimer = setTimeout(async () => {
            try {
                if (!this.state.currentArticle || this.state.currentArticle.id !== articleId) {
                    return;
                }
                const currentTitle = (this.state.currentArticle.name || "Untitled").trim();
                let currentBody = this.state.currentArticle.body_html || "";
                if (this.editor?.editable) {
                    const el = this.editor.getElContent ? this.editor.getElContent() : null;
                    if (el) currentBody = el.innerHTML;
                }

                const vals = {};
                if (currentTitle !== this._lastSavedTitle) {
                    vals.name = currentTitle;
                }
                if (currentBody !== this._lastSavedBodyHtml) {
                    vals.body_html = currentBody;
                }

                if (Object.keys(vals).length > 0) {
                    await this.orm.write("knowledge.management.article", [articleId], vals);
                    this._lastSavedTitle = currentTitle;
                    this._lastSavedBodyHtml = currentBody;
                    if (vals.name) {
                        await this._loadSidebar();
                    }
                }
                this.state.saveStatus = "saved";
            } catch (e) {
                console.warn("Auto-save failed", e);
            } finally {
                this._autoSaveTimer = null;
            }
        }, delay);
    }

    // ── Click Handlers for In-Editor Jump Buttons ──────────────────

    onEditorContainerClick(ev) {
        const jumpBtn = ev.target.closest(".o_knowledge_jump_item");
        if (!jumpBtn) return;
        ev.preventDefault();
        ev.stopPropagation();

        const action = jumpBtn.dataset.action;
        if (action === "template") {
            this.onBrowseTemplates();
        } else if (action === "kanban") {
            this.openInsertViewModal("kanban");
        } else if (action === "list") {
            this.openInsertViewModal("list");
        } else if (action === "calendar") {
            this.openInsertViewModal("calendar");
        } else if (action === "ai") {
            this.onOpenAIGenerator();
        }
    }

    // ── Data Loading & Article Selection ──────────────────────────

    async _loadSidebar() {
        const data = await this.orm.call(
            "knowledge.management.article",
            "get_sidebar_articles",
            []
        );
        this.state.sidebar = data || {
            favorites: [],
            workspace: [],
            shared: [],
            private: [],
        };
    }

    async _refreshExpandedChildren() {
        if (!this.state.expandedIds || !this.state.expandedIds.length) return;
        for (const parentId of this.state.expandedIds) {
            try {
                const children = await this.orm.call(
                    "knowledge.management.article",
                    "get_article_children",
                    [parentId]
                );
                this.state.childrenMap[parentId] = children || [];
            } catch (e) {
                console.warn("Failed to refresh children for", parentId, e);
            }
        }
    }

    _syncArticleToSidebar(articleId, updates) {
        if (!articleId) return;
        const updateList = (list) => {
            if (!list || !list.length) return;
            for (const item of list) {
                if (item.id === articleId) {
                    Object.assign(item, updates);
                }
            }
        };
        if (this.state.sidebar) {
            updateList(this.state.sidebar.favorites);
            updateList(this.state.sidebar.workspace);
            updateList(this.state.sidebar.shared);
            updateList(this.state.sidebar.private);
        }
        if (this.state.childrenMap) {
            for (const pid in this.state.childrenMap) {
                updateList(this.state.childrenMap[pid]);
            }
        }
    }

    _removeArticleFromSidebarState(articleId) {
        const filterOut = (list) => list ? list.filter(a => a.id !== articleId) : [];
        if (this.state.sidebar) {
            this.state.sidebar.favorites = filterOut(this.state.sidebar.favorites);
            this.state.sidebar.workspace = filterOut(this.state.sidebar.workspace);
            this.state.sidebar.shared = filterOut(this.state.sidebar.shared);
            this.state.sidebar.private = filterOut(this.state.sidebar.private);
        }
        if (this.state.childrenMap) {
            for (const pid in this.state.childrenMap) {
                this.state.childrenMap[pid] = filterOut(this.state.childrenMap[pid]);
            }
        }
    }

    _formatRelativeTime(dateStr) {
        if (!dateStr) return "recently";
        try {
            // Odoo datetimes are stored in UTC (e.g. "2026-09-21 14:45:00" or ISO string)
            const utcString = dateStr.endsWith("Z") ? dateStr : dateStr.replace(" ", "T") + "Z";
            const timestamp = Date.parse(utcString);
            if (isNaN(timestamp)) return "recently";
            const diffMs = Math.max(0, Date.now() - timestamp);
            const diffSecs = Math.floor(diffMs / 1000);
            if (diffSecs < 60) return "just now";
            const diffMins = Math.floor(diffSecs / 60);
            if (diffMins < 60) return `${diffMins}m ago`;
            const diffHours = Math.floor(diffMins / 60);
            if (diffHours < 24) return `${diffHours}h ago`;
            const diffDays = Math.floor(diffHours / 24);
            if (diffDays < 30) return `${diffDays}d ago`;
            const diffMonths = Math.floor(diffDays / 30);
            return `${diffMonths}mo ago`;
        } catch {
            return "recently";
        }
    }

    async openArticle(articleId) {
        this.state.loading = true;
        try {
            const records = await this.orm.call(
                "knowledge.management.article",
                "get_article_data",
                [],
                { context: { active_id: articleId } }
            ).catch(async () => {
                const recs = await this.orm.searchRead(
                    "knowledge.management.article",
                    [["id", "=", articleId]],
                    ["id", "name", "icon", "cover_image_url", "cover_position", "body_html",
                     "visibility", "is_locked", "full_width",
                     "write_uid", "write_date", "parent_id", "favorite_user_ids"]
                );
                if (!recs || !recs.length) return null;
                const r = recs[0];
                const uid = this.env.services.user?.userId || 1;
                return {
                    id: r.id,
                    name: r.name,
                    icon: r.icon || "📄",
                    cover_image_url: r.cover_image_url || false,
                    cover_position: r.cover_position || "50%",
                    body_html: cleanHtmlContent(r.body_html),
                    visibility: r.visibility,
                    is_locked: r.is_locked,
                    full_width: r.full_width,
                    is_user_favorite: (r.favorite_user_ids || []).includes(uid),
                    write_uid: r.write_uid
                        ? { id: r.write_uid[0], name: r.write_uid[1], avatar: `/web/image/res.users/${r.write_uid[0]}/avatar_128` }
                        : null,
                    write_date: r.write_date,
                    parent_id: r.parent_id ? r.parent_id[0] : false,
                    parent_name: r.parent_id ? r.parent_id[1] : false,
                };
            });

            if (!records) {
                this.state.loading = false;
                return;
            }

            records.body_html = cleanHtmlContent(records.body_html);
            this.state.currentArticle = records;
            this.state.saveStatus = "saved";
            this._lastSavedTitle = (records.name || "Untitled").trim();
            this._lastSavedBodyHtml = records.body_html || "";
            this.state.showKebab = false;
            this.state.editorKey++;
            setTimeout(() => {
                if (this.editor?.editable) {
                    updateEmptyHeadingClasses(this.editor.editable);
                }
            }, 60);
            this._ensureEmbeddedViewsRendered(records.id);
        } catch (e) {
            console.error("Failed to open article", e);
        }
        this.state.loading = false;
    }

    _findArticleById(id) {
        if (!id) return null;
        if (this.state.currentArticle && this.state.currentArticle.id === id) {
            return this.state.currentArticle;
        }
        const lists = [
            ...(this.state.sidebar?.favorites || []),
            ...(this.state.sidebar?.workspace || []),
            ...(this.state.sidebar?.shared || []),
            ...(this.state.sidebar?.private || []),
        ];
        for (const item of lists) {
            if (item.id === id) return item;
        }
        if (this.state.childrenMap) {
            for (const pid in this.state.childrenMap) {
                for (const item of (this.state.childrenMap[pid] || [])) {
                    if (item.id === id) return item;
                }
            }
        }
        return null;
    }

    async onNewArticle(parentId = false, visibility = "workspace") {
        let vis = visibility;
        if (parentId) {
            const parent = this._findArticleById(parentId);
            if (parent && parent.visibility) {
                vis = parent.visibility;
            }
        }
        const initialHtml = getInitialArticleHtml();
        const newArt = await this.orm.create("knowledge.management.article", [{
            name: "Untitled",
            icon: "📄",
            parent_id: parentId || false,
            visibility: vis,
            body_html: initialHtml,
        }]);
        const newId = newArt[0];
        await this._loadSidebar();
        await this.openArticle(newId);
    }

    // ── Insert View Modal (Kanban / List / Calendar) ──────────────

    _getEditorSelectionRange() {
        if (!this.editor?.editable) return null;
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
            const range = sel.getRangeAt(0);
            if (this.editor.editable.contains(range.commonAncestorContainer)) {
                return range.cloneRange();
            }
        }
        return null;
    }

    openInsertViewModal(viewType, targetBlock = null) {
        this._savedRange = this._getEditorSelectionRange();
        this._targetInsertionBlock = targetBlock || this._lastTargetBlock || null;
        this.state.insertViewType = viewType;
        this.state.insertViewName = "";
        this.state.showInsertViewModal = true;
        setTimeout(() => {
            if (this.insertViewNameInput?.el) {
                this.insertViewNameInput.el.focus();
            }
        }, 80);
    }

    onCloseInsertViewModal() {
        this.state.showInsertViewModal = false;
    }

    onInsertViewKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmInsertView();
        } else if (ev.key === "Escape") {
            this.onCloseInsertViewModal();
        }
    }

    // ── In-App Modal Dialog Helper (Replaces browser alert/prompt) ───
    promptDialog({ title, label, defaultValue = "", showDelete = false }) {
        return new Promise((resolve) => {
            this.state.itemPromptTitle = title || "Item Details";
            this.state.itemPromptLabel = label || "Name";
            this.state.itemPromptValue = defaultValue || "";
            this.state.itemPromptShowDelete = Boolean(showDelete);
            this.state.showItemPromptModal = true;
            this._itemPromptResolver = resolve;
            setTimeout(() => {
                const input = document.querySelector(".o_knowledge_modal input.form-control");
                if (input) {
                    input.focus();
                    input.select();
                }
            }, 60);
        });
    }

    onCloseItemPromptModal() {
        this.state.showItemPromptModal = false;
        if (this._itemPromptResolver) {
            this._itemPromptResolver(null);
            this._itemPromptResolver = null;
        }
    }

    onConfirmItemPrompt() {
        const val = (this.state.itemPromptValue || "").trim();
        this.state.showItemPromptModal = false;
        if (this._itemPromptResolver) {
            this._itemPromptResolver(val);
            this._itemPromptResolver = null;
        }
    }

    onItemPromptDelete() {
        this.state.showItemPromptModal = false;
        if (this._itemPromptResolver) {
            this._itemPromptResolver("__DELETE__");
            this._itemPromptResolver = null;
        }
    }

    onItemPromptKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmItemPrompt();
        } else if (ev.key === "Escape") {
            this.onCloseItemPromptModal();
        }
    }

    _exportViewToXlsx(viewName, items) {
        const headers = ["Name", "Stage", "Assigned To", "Date", "Description"];
        const rows = (items || []).map(i => [
            `"${(i.name || '').replace(/"/g, '""')}"`,
            `"${(i.stage_name || '').replace(/"/g, '""')}"`,
            `"${(i.user_name || '').replace(/"/g, '""')}"`,
            `"${(i.date || '').replace(/"/g, '""')}"`,
            `"${(i.description || '').replace(/"/g, '""')}"`,
        ]);
        const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(r => r.join(","))].join("\r\n");
        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", `${(viewName || "Items").replace(/[^a-zA-Z0-9_-]/g, "_")}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        this.notification.add(`Exported ${(items || []).length} items to file!`, { type: "success" });
    }

    async onConfirmInsertView() {
        if (!this.state.currentArticle) return;
        const viewType = this.state.insertViewType || "kanban";
        const articleId = this.state.currentArticle.id;
        const viewRefId = `emb_${viewType}_${Date.now()}`;
        const defaultName = viewType === "kanban" ? "Nandu" : viewType === "list" ? "My List" : "My Calendar";
        const viewName = this.state.insertViewName.trim() || defaultName;

        this.onCloseInsertViewModal();

        // Create default stages for kanban matching Image 2 (New, Ongoing, Done folded)
        if (viewType === "kanban") {
            await this.orm.create("knowledge.management.item.stage", [{
                name: "New",
                article_id: articleId,
                sequence: 10,
                fold: false,
            }, {
                name: "Ongoing",
                article_id: articleId,
                sequence: 20,
                fold: false,
            }, {
                name: "Done",
                article_id: articleId,
                sequence: 30,
                fold: true,
            }]);
        }

        // Full inline view block with paragraph afterwards so user can type below it
        const containerHtml = `<div class="o_knowledge_behavior_anchor o_knowledge_embedded_view_container" contenteditable="false"
                data-view-type="${viewType}"
                data-view-ref="${viewRefId}"
                data-view-name="${viewName}"
                data-article-id="${articleId}"></div><p><br></p>`;

        const targetBlock = this._targetInsertionBlock || this._lastTargetBlock;
        if (this.editor?.editable) {
            let inserted = false;
            if (targetBlock && this.editor.editable.contains(targetBlock)) {
                targetBlock.insertAdjacentHTML("beforebegin", containerHtml);
                if (!targetBlock.innerText.trim() && !targetBlock.classList.contains("o_knowledge_behavior_anchor")) {
                    targetBlock.remove();
                }
                inserted = true;
            } else if (this._savedRange && this.editor.editable.contains(this._savedRange.commonAncestorContainer)) {
                try {
                    let containerEl = this._savedRange.commonAncestorContainer;
                    if (containerEl.nodeType !== Node.ELEMENT_NODE) containerEl = containerEl.parentElement;
                    let topBlock = containerEl;
                    while (topBlock && topBlock.parentElement && topBlock.parentElement !== this.editor.editable) {
                        topBlock = topBlock.parentElement;
                    }
                    if (topBlock && topBlock.parentElement === this.editor.editable) {
                        topBlock.insertAdjacentHTML("beforebegin", containerHtml);
                        inserted = true;
                    }
                } catch (e) {
                    console.warn("Could not insert at range, appending instead", e);
                }
            }
            if (!inserted) {
                this.editor.editable.insertAdjacentHTML("beforeend", containerHtml);
            }
            this._savedRange = null;
            this._lastTargetBlock = null;
            this._targetInsertionBlock = null;
            this.onEditorChange();
            await this._renderEmbeddedViews(this.editor.editable, articleId);
        } else {
            let currentBody = this.state.currentArticle.body_html || "";
            const newBody = currentBody + containerHtml;
            this.state.currentArticle.body_html = newBody;
            this.state.editorKey++;
            await this.orm.write("knowledge.management.article", [articleId], { body_html: newBody });
        }

        this.notification.add(`${viewType.toUpperCase()} view inserted!`, { type: "success" });
    }

    // ── Full Inline Embedded Views Renderer (Matches Image 2) ─────

    async _renderEmbeddedViews(container, articleId) {
        if (!container) return;
        const blocks = container.querySelectorAll(".o_knowledge_embedded_view_container, .o_knowledge_embedded_view_block");
        for (const block of blocks) {
            const viewType = block.dataset.viewType || "kanban";
            const viewRef = block.dataset.viewRef;
            const viewName = block.dataset.viewName || "Items";
            const artId = parseInt(block.dataset.articleId) || articleId;

            block.setAttribute("contenteditable", "false");
            block.className = "o_knowledge_behavior_anchor o_knowledge_embedded_view_container";

            try {
                const [items, stages] = await Promise.all([
                    this.orm.call("knowledge.management.item", "get_items_for_view", [artId, viewRef]),
                    this.orm.call("knowledge.management.item", "get_stages_for_view", [artId]),
                ]);

                if (viewType === "kanban") {
                    this._renderKanbanBoard(block, artId, viewRef, viewName, items || [], stages || []);
                } else if (viewType === "list") {
                    this._renderListView(block, artId, viewRef, viewName, items || [], stages || []);
                } else if (viewType === "calendar") {
                    this._renderCalendarView(block, artId, viewRef, viewName, items || []);
                }
            } catch (e) {
                console.error("Failed to render embedded view", e);
            }
        }
    }

    _renderKanbanBoard(block, articleId, viewRef, viewName, items, stages) {
        const topBarHtml = `
            <div class="d-flex align-items-center gap-2 mb-3 pb-2 border-bottom position-relative">
                <button class="btn btn-sm text-white fw-semibold o_kanban_new_btn" style="background:#714B67; padding:4px 14px; border-radius:4px; font-size:13px;">New</button>
                <span class="fw-bold text-dark fs-6 ms-1">${viewName}</span>
                <div class="position-relative d-inline-block">
                    <i class="fa fa-cog text-muted o_kanban_settings_btn ms-1" style="cursor:pointer; padding:4px;" title="View Options"></i>
                    <div class="o_settings_dropdown_menu d-none position-absolute bg-white border rounded shadow-sm py-1" style="z-index:1050; min-width:180px; top:100%; left:0;">
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_rename_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-pencil text-muted"></i> Rename View
                        </button>
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_export_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-file-excel-o text-success"></i> Export (XLSX)
                        </button>
                        <div class="dropdown-divider my-1 border-top"></div>
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_expand_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-arrows-alt text-muted"></i> Expand View
                        </button>
                    </div>
                </div>
                <div class="ms-auto d-flex align-items-center">
                    <div class="input-group input-group-sm" style="width:220px;">
                        <span class="input-group-text bg-white border-end-0 py-1"><i class="fa fa-search text-muted"></i></span>
                        <input type="text" class="form-control border-start-0 border-end-0 py-1 o_kanban_search_input" placeholder="Search..."/>
                        <span class="input-group-text bg-white border-start-0 py-1"><i class="fa fa-caret-down text-muted"></i></span>
                    </div>
                </div>
            </div>
        `;

        let colsHtml = `<div class="d-flex gap-3 overflow-auto pb-2 o_kanban_columns_row" style="min-height:220px;">`;
        for (const stage of stages) {
            const stageItems = items.filter(i => i.stage_id === stage.id);
            if (stage.fold) {
                colsHtml += `
                    <div class="o_stage_folded d-flex flex-column align-items-center justify-content-between p-2 rounded" data-stage-id="${stage.id}" style="width:38px; min-width:38px; background:#f8fafc; border:1px solid #e2e8f0; cursor:pointer;" title="Click to unfold ${stage.name}">
                        <span style="writing-mode:vertical-rl; transform:rotate(180deg); font-weight:600; font-size:13px; color:#475569; margin-top:12px;">${stage.name} (${stageItems.length})</span>
                        <i class="fa fa-angle-double-right text-muted mb-2"></i>
                    </div>
                `;
            } else {
                colsHtml += `
                    <div class="o_stage_column flex-grow-1 p-2 rounded" data-stage-id="${stage.id}" style="min-width:280px; max-width:360px; background:#f8fafc; border:1px solid #e2e8f0; display:flex; flex-direction:column;">
                        <div class="d-flex align-items-center justify-content-between mb-2 px-1">
                            <span class="fw-semibold text-secondary" style="font-size:13px;">${stage.name} (${stageItems.length})</span>
                            <div class="d-flex align-items-center gap-2">
                                <button class="btn btn-link btn-sm p-0 text-muted o_add_stage_item_btn" data-stage-id="${stage.id}" title="Add Item" style="text-decoration:none; font-size:14px;">
                                    <i class="fa fa-plus"></i>
                                </button>
                                <button class="btn btn-link btn-sm p-0 text-muted o_fold_stage_btn" data-stage-id="${stage.id}" title="Fold column" style="text-decoration:none; font-size:13px;">
                                    <i class="fa fa-angle-double-left"></i>
                                </button>
                            </div>
                        </div>
                        <div class="o_cards_container flex-grow-1 d-flex flex-column gap-2">
                            ${stageItems.length === 0 ? `
                                <div class="o_empty_stage_box text-center py-4 px-3 rounded" style="background:#ffffff; border:1px dashed #cbd5e1; cursor:pointer;" data-stage-id="${stage.id}">
                                    <div class="mb-2">
                                        <svg width="68" height="68" viewBox="0 0 100 100" fill="none" style="display:inline-block;">
                                            <circle cx="50" cy="50" r="38" fill="#714B67" opacity="0.9"/>
                                            <path d="M42 20L58 20L68 30L68 76L32 76L32 20Z" fill="#FFFFFF" stroke="#374151" stroke-width="2" stroke-linejoin="round"/>
                                            <path d="M58 20L58 30L68 30" stroke="#374151" stroke-width="2" stroke-linejoin="round"/>
                                            <circle cx="44" cy="46" r="2.2" fill="#374151"/>
                                            <circle cx="56" cy="46" r="2.2" fill="#374151"/>
                                            <path d="M44 54C47 58 53 58 56 54" stroke="#374151" stroke-width="2" stroke-linecap="round"/>
                                            <path d="M38 64H62M38 68H54" stroke="#E5E7EB" stroke-width="2" stroke-linecap="round"/>
                                            <path d="M28 30L22 26M50 14L50 8M72 30L78 26" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"/>
                                        </svg>
                                    </div>
                                    <div class="fw-bold text-dark mb-1" style="font-size:14px;">Create an Article Item</div>
                                    <div class="text-muted" style="font-size:11px; line-height:1.45;">Article items are articles that exist inside their parents but are not displayed in the menu. They can be used to handle lists (Buildings, Tasks, ...).</div>
                                </div>
                            ` : stageItems.map(itm => `
                                <div class="o_kanban_card p-2 bg-white rounded border shadow-sm" data-item-id="${itm.id}" data-item-name="${itm.name}" data-child-article-id="${itm.child_article_id || ''}" style="cursor:pointer;" title="Click to open article">
                                    <div class="fw-medium text-dark d-flex align-items-center justify-content-between" style="font-size:13px;">
                                        <span>${itm.name}</span>
                                        <i class="fa fa-file-text-o text-muted ms-1" style="font-size:11px;"></i>
                                    </div>
                                    ${itm.user_name ? `<div class="text-muted mt-1" style="font-size:11px;"><i class="fa fa-user me-1"></i>${itm.user_name}</div>` : ''}
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;
            }
        }
        colsHtml += `</div>`;

        block.innerHTML = topBarHtml + colsHtml;

        // Attach Interactive Event Listeners
        const createItemHandler = async (stId) => {
            const name = await this.promptDialog({
                title: "Create Article Item",
                label: "Item Name",
                defaultValue: "Building " + (items.length + 1),
            });
            if (!name) return;
            await this.orm.create("knowledge.management.item", [{
                name,
                article_id: articleId,
                view_ref_id: viewRef,
                view_type: "kanban",
                stage_id: stId || (stages[0] ? stages[0].id : false),
            }]);
            await this._renderEmbeddedViews(this.editor?.editable, articleId);
        };

        // New button
        const newBtn = block.querySelector(".o_kanban_new_btn");
        if (newBtn) {
            newBtn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                createItemHandler(stages[0]?.id);
            });
        }

        // Add to stage buttons
        block.querySelectorAll(".o_add_stage_item_btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                createItemHandler(parseInt(btn.dataset.stageId));
            });
        });

        // Empty stage click
        block.querySelectorAll(".o_empty_stage_box").forEach(box => {
            box.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                createItemHandler(parseInt(box.dataset.stageId));
            });
        });

        // Fold column click
        block.querySelectorAll(".o_fold_stage_btn").forEach(btn => {
            btn.addEventListener("click", async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const stId = parseInt(btn.dataset.stageId);
                await this.orm.write("knowledge.management.item.stage", [stId], { fold: true });
                await this._renderEmbeddedViews(this.editor?.editable, articleId);
            });
        });

        // Unfold column click
        block.querySelectorAll(".o_stage_folded").forEach(col => {
            col.addEventListener("click", async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const stId = parseInt(col.dataset.stageId);
                await this.orm.write("knowledge.management.item.stage", [stId], { fold: false });
                await this._renderEmbeddedViews(this.editor?.editable, articleId);
            });
        });

        // Card open article or edit / delete
        block.querySelectorAll(".o_kanban_card").forEach(card => {
            card.addEventListener("click", async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const childArtId = parseInt(card.dataset.childArticleId);
                if (childArtId) {
                    await this.openArticle(childArtId);
                } else {
                    const itmId = parseInt(card.dataset.itemId);
                    const oldName = card.dataset.itemName || "";
                    const res = await this.promptDialog({
                        title: "Edit Item",
                        label: "Item Name",
                        defaultValue: oldName,
                        showDelete: true,
                    });
                    if (res === "__DELETE__" || res === "") {
                        await this.orm.unlink("knowledge.management.item", [itmId]);
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    } else if (res && res !== oldName) {
                        await this.orm.write("knowledge.management.item", [itmId], { name: res });
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    }
                }
            });
        });

        // Search filter with Backspace fix
        const searchInput = block.querySelector(".o_kanban_search_input");
        if (searchInput) {
            searchInput.setAttribute("contenteditable", "false");
            searchInput.addEventListener("keydown", (e) => {
                e.stopPropagation();
            });
            searchInput.addEventListener("keyup", (e) => {
                e.stopPropagation();
            });
            searchInput.addEventListener("input", (e) => {
                e.stopPropagation();
                const query = e.target.value.toLowerCase().trim();
                block.querySelectorAll(".o_kanban_card").forEach(c => {
                    const text = (c.dataset.itemName || "").toLowerCase();
                    c.style.display = text.includes(query) ? "" : "none";
                });
            });
        }

        // Settings gear with dropdown menu (Rename, Export, Expand)
        const settingsBtn = block.querySelector(".o_kanban_settings_btn");
        const settingsMenu = block.querySelector(".o_settings_dropdown_menu");
        if (settingsBtn && settingsMenu) {
            settingsBtn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                settingsMenu.classList.toggle("d-none");
            });

            document.addEventListener("click", (e) => {
                if (!settingsMenu.contains(e.target) && e.target !== settingsBtn) {
                    settingsMenu.classList.add("d-none");
                }
            });

            const renameBtn = settingsMenu.querySelector(".o_settings_rename_btn");
            if (renameBtn) {
                renameBtn.addEventListener("click", async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    const newName = await this.promptDialog({
                        title: "Rename Kanban View",
                        label: "View Title",
                        defaultValue: viewName,
                    });
                    if (newName && newName !== viewName) {
                        block.dataset.viewName = newName;
                        this.onEditorChange();
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    }
                });
            }

            const exportBtn = settingsMenu.querySelector(".o_settings_export_btn");
            if (exportBtn) {
                exportBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    this._exportViewToXlsx(viewName, items);
                });
            }

            const expandBtn = settingsMenu.querySelector(".o_settings_expand_btn");
            if (expandBtn) {
                expandBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    this._openEmbeddedViewAction(articleId, viewRef, "kanban", viewName);
                });
            }
        }
    }

    _renderListView(block, articleId, viewRef, viewName, items, stages) {
        const topBarHtml = `
            <div class="d-flex align-items-center gap-2 mb-3 pb-2 border-bottom position-relative">
                <button class="btn btn-sm text-white fw-semibold o_list_new_btn" style="background:#714B67; padding:4px 14px; border-radius:4px; font-size:13px;">New</button>
                <span class="fw-bold text-dark fs-6 ms-1">${viewName}</span>
                <div class="position-relative d-inline-block">
                    <i class="fa fa-cog text-muted o_list_settings_btn ms-1" style="cursor:pointer; padding:4px;" title="View Options"></i>
                    <div class="o_settings_dropdown_menu d-none position-absolute bg-white border rounded shadow-sm py-1" style="z-index:1050; min-width:180px; top:100%; left:0;">
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_rename_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-pencil text-muted"></i> Rename View
                        </button>
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_export_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-file-excel-o text-success"></i> Export (XLSX)
                        </button>
                        <div class="dropdown-divider my-1 border-top"></div>
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_expand_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-arrows-alt text-muted"></i> Expand View
                        </button>
                    </div>
                </div>
                <div class="ms-auto d-flex align-items-center">
                    <div class="input-group input-group-sm" style="width:220px;">
                        <span class="input-group-text bg-white border-end-0 py-1"><i class="fa fa-search text-muted"></i></span>
                        <input type="text" class="form-control border-start-0 border-end-0 py-1 o_list_search_input" placeholder="Search..."/>
                        <span class="input-group-text bg-white border-start-0 py-1"><i class="fa fa-caret-down text-muted"></i></span>
                    </div>
                </div>
            </div>
        `;

        const tableHtml = `
            <div class="table-responsive">
                <table class="table table-sm table-hover align-middle mb-0" style="font-size:13px;">
                    <thead class="table-light">
                        <tr>
                            <th style="width:40%;">Name</th>
                            <th style="width:20%;">Stage</th>
                            <th style="width:20%;">Assigned To</th>
                            <th style="width:20%;">Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items.length === 0 ? `
                            <tr><td colspan="4" class="text-center text-muted py-4">No items yet. Click <strong>New</strong> to add an item.</td></tr>
                        ` : items.map(itm => `
                            <tr class="o_list_row" data-item-id="${itm.id}" data-item-name="${itm.name}" data-child-article-id="${itm.child_article_id || ''}" style="cursor:pointer;" title="Click to open article">
                                <td class="fw-medium">
                                    <span>${itm.name}</span>
                                    <i class="fa fa-file-text-o text-muted ms-2" style="font-size:11px;"></i>
                                </td>
                                <td><span class="badge bg-light text-dark border">${itm.stage_name || 'New'}</span></td>
                                <td class="text-muted">${itm.user_name || '—'}</td>
                                <td class="text-muted">${itm.date || '—'}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            <div class="mt-2 pt-2 border-top">
                <button class="btn btn-sm btn-link text-muted p-0 o_list_add_item_btn" style="text-decoration:none; font-size:13px;">
                    <i class="fa fa-plus me-1"></i>Add an Item
                </button>
            </div>
        `;

        block.innerHTML = topBarHtml + tableHtml;

        const createItemHandler = async () => {
            const name = await this.promptDialog({
                title: "Create Article Item",
                label: "Item Name",
                defaultValue: "Item " + (items.length + 1),
            });
            if (!name) return;
            await this.orm.create("knowledge.management.item", [{
                name,
                article_id: articleId,
                view_ref_id: viewRef,
                view_type: "list",
                stage_id: stages[0]?.id || false,
            }]);
            await this._renderEmbeddedViews(this.editor?.editable, articleId);
        };

        const newBtn = block.querySelector(".o_list_new_btn");
        if (newBtn) newBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); createItemHandler(); });

        const addRowBtn = block.querySelector(".o_list_add_item_btn");
        if (addRowBtn) addRowBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); createItemHandler(); });

        block.querySelectorAll(".o_list_row").forEach(row => {
            row.addEventListener("click", async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const childArtId = parseInt(row.dataset.childArticleId);
                if (childArtId) {
                    await this.openArticle(childArtId);
                } else {
                    const itmId = parseInt(row.dataset.itemId);
                    const oldName = row.dataset.itemName || "";
                    const res = await this.promptDialog({
                        title: "Edit Item",
                        label: "Item Name",
                        defaultValue: oldName,
                        showDelete: true,
                    });
                    if (res === "__DELETE__" || res === "") {
                        await this.orm.unlink("knowledge.management.item", [itmId]);
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    } else if (res && res !== oldName) {
                        await this.orm.write("knowledge.management.item", [itmId], { name: res });
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    }
                }
            });
        });

        const searchInput = block.querySelector(".o_list_search_input");
        if (searchInput) {
            searchInput.setAttribute("contenteditable", "false");
            searchInput.addEventListener("keydown", (e) => { e.stopPropagation(); });
            searchInput.addEventListener("keyup", (e) => { e.stopPropagation(); });
            searchInput.addEventListener("input", (e) => {
                e.stopPropagation();
                const query = e.target.value.toLowerCase().trim();
                block.querySelectorAll(".o_list_row").forEach(r => {
                    const text = (r.dataset.itemName || "").toLowerCase();
                    r.style.display = text.includes(query) ? "" : "none";
                });
            });
        }

        const settingsBtn = block.querySelector(".o_list_settings_btn");
        const settingsMenu = block.querySelector(".o_settings_dropdown_menu");
        if (settingsBtn && settingsMenu) {
            settingsBtn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                settingsMenu.classList.toggle("d-none");
            });

            document.addEventListener("click", (e) => {
                if (!settingsMenu.contains(e.target) && e.target !== settingsBtn) {
                    settingsMenu.classList.add("d-none");
                }
            });

            const renameBtn = settingsMenu.querySelector(".o_settings_rename_btn");
            if (renameBtn) {
                renameBtn.addEventListener("click", async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    const newName = await this.promptDialog({
                        title: "Rename List View",
                        label: "View Title",
                        defaultValue: viewName,
                    });
                    if (newName && newName !== viewName) {
                        block.dataset.viewName = newName;
                        this.onEditorChange();
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    }
                });
            }

            const exportBtn = settingsMenu.querySelector(".o_settings_export_btn");
            if (exportBtn) {
                exportBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    this._exportViewToXlsx(viewName, items);
                });
            }

            const expandBtn = settingsMenu.querySelector(".o_settings_expand_btn");
            if (expandBtn) {
                expandBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    this._openEmbeddedViewAction(articleId, viewRef, "list", viewName);
                });
            }
        }
    }

    _renderCalendarView(block, articleId, viewRef, viewName, items) {
        const today = new Date();
        const year = today.getFullYear();
        const month = today.getMonth();
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const monthName = today.toLocaleDateString("en-US", { month: "long", year: "numeric" });

        let daysHtml = "";
        for (let i = 0; i < firstDay; i++) {
            daysHtml += `<div class="p-2 border bg-light" style="min-height:50px;"></div>`;
        }
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const dayEvents = items.filter(i => i.date && i.date.startsWith(dateStr));
            const isToday = d === today.getDate();
            daysHtml += `
                <div class="p-2 border o_cal_cell ${isToday ? 'bg-info-subtle fw-bold' : 'bg-white'}" data-date="${dateStr}" style="min-height:50px; cursor:pointer;" title="Click to add event on ${dateStr}">
                    <div class="d-flex justify-content-between mb-1" style="font-size:11px;">
                        <span>${d}</span>
                        ${isToday ? '<span class="badge bg-primary" style="font-size:9px;">Today</span>' : ''}
                    </div>
                    ${dayEvents.map(ev => `<div class="badge bg-purple text-white text-truncate w-100 mb-1" style="background:#714B67; font-size:11px;">${ev.name}</div>`).join('')}
                </div>
            `;
        }

        const topBarHtml = `
            <div class="d-flex align-items-center gap-2 mb-3 pb-2 border-bottom position-relative">
                <button class="btn btn-sm text-white fw-semibold o_cal_new_btn" style="background:#714B67; padding:4px 14px; border-radius:4px; font-size:13px;">New</button>
                <span class="fw-bold text-dark fs-6 ms-1">${viewName}</span>
                <div class="position-relative d-inline-block">
                    <i class="fa fa-cog text-muted o_cal_settings_btn ms-1" style="cursor:pointer; padding:4px;" title="View Options"></i>
                    <div class="o_settings_dropdown_menu d-none position-absolute bg-white border rounded shadow-sm py-1" style="z-index:1050; min-width:180px; top:100%; left:0;">
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_rename_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-pencil text-muted"></i> Rename View
                        </button>
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_export_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-file-excel-o text-success"></i> Export (XLSX)
                        </button>
                        <div class="dropdown-divider my-1 border-top"></div>
                        <button class="dropdown-item py-2 px-3 d-flex align-items-center gap-2 o_settings_expand_btn" style="font-size:13px; cursor:pointer; background:transparent; border:none; width:100%; text-align:left;">
                            <i class="fa fa-arrows-alt text-muted"></i> Expand View
                        </button>
                    </div>
                </div>
                <div class="ms-auto fw-semibold text-dark fs-6">${monthName}</div>
            </div>
            <div class="d-grid" style="grid-template-columns:repeat(7, 1fr); gap:1px; background:#e2e8f0; border:1px solid #e2e8f0; border-radius:6px; overflow:hidden;">
                ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(day => `
                    <div class="p-2 text-center fw-semibold text-muted bg-light" style="font-size:12px;">${day}</div>
                `).join('')}
                ${daysHtml}
            </div>
        `;

        block.innerHTML = topBarHtml;

        const addEventOnDate = async (dateStr) => {
            const name = await this.promptDialog({
                title: `Create Event on ${dateStr}`,
                label: "Event Name",
                defaultValue: "Event",
            });
            if (!name) return;
            await this.orm.create("knowledge.management.item", [{
                name,
                article_id: articleId,
                view_ref_id: viewRef,
                view_type: "calendar",
                date: dateStr,
            }]);
            await this._renderEmbeddedViews(this.editor?.editable, articleId);
        };

        const newBtn = block.querySelector(".o_cal_new_btn");
        if (newBtn) {
            newBtn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                const todayStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
                addEventOnDate(todayStr);
            });
        }

        block.querySelectorAll(".o_cal_cell").forEach(cell => {
            cell.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                addEventOnDate(cell.dataset.date);
            });
        });

        const settingsBtn = block.querySelector(".o_cal_settings_btn");
        const settingsMenu = block.querySelector(".o_settings_dropdown_menu");
        if (settingsBtn && settingsMenu) {
            settingsBtn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                settingsMenu.classList.toggle("d-none");
            });

            document.addEventListener("click", (e) => {
                if (!settingsMenu.contains(e.target) && e.target !== settingsBtn) {
                    settingsMenu.classList.add("d-none");
                }
            });

            const renameBtn = settingsMenu.querySelector(".o_settings_rename_btn");
            if (renameBtn) {
                renameBtn.addEventListener("click", async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    const newName = await this.promptDialog({
                        title: "Rename Calendar View",
                        label: "View Title",
                        defaultValue: viewName,
                    });
                    if (newName && newName !== viewName) {
                        block.dataset.viewName = newName;
                        this.onEditorChange();
                        await this._renderEmbeddedViews(this.editor?.editable, articleId);
                    }
                });
            }

            const exportBtn = settingsMenu.querySelector(".o_settings_export_btn");
            if (exportBtn) {
                exportBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    this._exportViewToXlsx(viewName, items);
                });
            }

            const expandBtn = settingsMenu.querySelector(".o_settings_expand_btn");
            if (expandBtn) {
                expandBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    settingsMenu.classList.add("d-none");
                    this._openEmbeddedViewAction(articleId, viewRef, "calendar", viewName);
                });
            }
        }
    }

    async _openEmbeddedViewAction(articleId, viewRefId, viewType, viewName) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: viewName,
            res_model: "knowledge.management.item",
            views: viewType === "kanban"
                ? [[false, "kanban"], [false, "list"], [false, "form"]]
                : viewType === "list"
                ? [[false, "list"], [false, "kanban"], [false, "form"]]
                : [[false, "calendar"], [false, "list"], [false, "form"]],
            domain: [
                ["article_id", "=", articleId],
                ["view_ref_id", "=", viewRefId],
            ],
            context: {
                default_article_id: articleId,
                default_view_ref_id: viewRefId,
                default_view_type: viewType,
                search_default_group_stage: 1,
                group_by: "stage_id",
            },
        });
    }

    // ── AI Article Generator Modal ────────────────────────────────

    onOpenAIGenerator() {
        this.state.showAIDialog = true;
        this.state.aiGenerating = false;
        this.selectAIPreset(this.state.aiPreset || "plan");
    }

    onCloseAIDialog() {
        this.state.showAIDialog = false;
    }

    selectAIPreset(preset) {
        this.state.aiPreset = preset;
        const prompts = {
            plan: "Create a detailed project plan with goals, phases, milestones, team assignments, and risk mitigation.",
            meeting: "Document meeting minutes covering attendees, executive summary, discussion topics, decisions made, and action items with owners.",
            sop: "Write a standard operating procedure (SOP) with purpose, scope, prerequisites, step-by-step instructions, and quality checklist.",
            prd: "Draft a product requirements document (PRD) detailing problem statement, user personas, functional requirements, and success metrics.",
            custom: "",
        };
        this.state.aiPrompt = prompts[preset] || "";
    }

    async onConfirmAIGenerate() {
        if (!this.state.currentArticle) return;
        this.state.aiGenerating = true;

        const preset = this.state.aiPreset;
        const userPrompt = this.state.aiPrompt || "Overview and Documentation";

        let title = "Generated Article";
        let bodyHtml = "";

        if (preset === "plan") {
            title = "Project Roadmap & Execution Plan";
            bodyHtml = `<h1>Project Roadmap &amp; Execution Plan 📊</h1>
<p class="lead"><strong>Objective:</strong> ${userPrompt}</p>
<hr/>
<h2>1. Executive Summary</h2>
<p>This document outlines the strategic timeline, deliverables, resource allocation, and key risks for the initiative.</p>
<h2>2. Project Phases &amp; Milestones</h2>
<ul>
    <li><strong>Phase 1: Discovery &amp; Scope Alignment</strong> — Finalize specifications, technical requirements, and stakeholder buy-in.</li>
    <li><strong>Phase 2: Execution &amp; Sprint Development</strong> — Bi-weekly sprint deliverables with continuous quality assurance.</li>
    <li><strong>Phase 3: Testing &amp; UAT</strong> — User acceptance testing, performance benchmarks, and bug fixes.</li>
    <li><strong>Phase 4: Launch &amp; Rollout</strong> — Phased release to customers, enablement sessions, and monitoring.</li>
</ul>
<h2>3. Key Deliverables</h2>
<ol>
    <li>Architecture documentation and database schema design</li>
    <li>Core functional modules and integration endpoints</li>
    <li>User guides and operational runbooks</li>
</ol>
<h2>4. Risk Assessment &amp; Mitigation</h2>
<p><strong>Identified Risks:</strong> Dependency delays and scope creep. <em>Mitigation:</em> Strict change request process and weekly status checkpoints.</p>`;
        } else if (preset === "meeting") {
            title = "Team Meeting Minutes";
            bodyHtml = `<h1>Team Meeting Minutes 📝</h1>
<p><strong>Date:</strong> ${new Date().toLocaleDateString()} | <strong>Time:</strong> 10:00 AM</p>
<p><strong>Attendees:</strong> Product Team, Engineering Leads, Design Lead</p>
<p><strong>Focus:</strong> ${userPrompt}</p>
<hr/>
<h2>Discussion Topics</h2>
<ul>
    <li>Reviewed sprint progress and resolved blocking dependencies.</li>
    <li>Aligned on user feedback regarding recent feature releases.</li>
    <li>Prioritized upcoming roadmap backlog items.</li>
</ul>
<h2>Decisions Made</h2>
<ul>
    <li>Approved implementation roadmap for Q4 deliverables.</li>
    <li>Adopted new workflow templates across workspace documentation.</li>
</ul>
<h2>Action Items</h2>
<ol>
    <li><strong>Engineering:</strong> Finalize API contracts by Friday.</li>
    <li><strong>Product:</strong> Share revised user stories with stakeholders.</li>
    <li><strong>Design:</strong> Provide high-fidelity prototypes for next sprint.</li>
</ol>`;
        } else if (preset === "sop") {
            title = "Standard Operating Procedure";
            bodyHtml = `<h1>Standard Operating Procedure (SOP) 📋</h1>
<p><strong>Procedure:</strong> ${userPrompt}</p>
<p><strong>Version:</strong> 1.0 | <strong>Effective Date:</strong> ${new Date().toLocaleDateString()}</p>
<hr/>
<h2>1. Purpose &amp; Scope</h2>
<p>To establish a consistent, reproducible standard across team operations and ensure quality compliance.</p>
<h2>2. Prerequisites</h2>
<ul>
    <li>Standard system access credentials</li>
    <li>Approved verification checklist</li>
</ul>
<h2>3. Step-by-Step Procedure</h2>
<ol>
    <li><strong>Step 1: Preparation</strong> — Verify all prerequisites and environment readiness before initiating the task.</li>
    <li><strong>Step 2: Execution</strong> — Execute designated steps according to standard operational parameters.</li>
    <li><strong>Step 3: Verification &amp; Quality Check</strong> — Audit output against acceptance criteria.</li>
    <li><strong>Step 4: Reporting &amp; Handover</strong> — Log task completion in knowledge records and notify relevant stakeholders.</li>
</ol>
<h2>4. Escalation Path</h2>
<p>In case of deviations or issues, escalate to the team lead within 1 hour.</p>`;
        } else {
            title = "Product Requirements Document";
            bodyHtml = `<h1>Product Requirements Document (PRD) 🚀</h1>
<p><strong>Initiative:</strong> ${userPrompt}</p>
<hr/>
<h2>1. Problem Statement</h2>
<p>Users require a seamless, intuitive workflow to achieve higher productivity and minimize manual overhead.</p>
<h2>2. Target Audience &amp; Personas</h2>
<ul>
    <li><strong>Primary:</strong> Department Managers and Team Leads</li>
    <li><strong>Secondary:</strong> Operational team members and contributors</li>
</ul>
<h2>3. Key Features &amp; Functional Requirements</h2>
<ul>
    <li><strong>Native Editor Integration:</strong> Rich text styling, inline slash commands, and block insertions.</li>
    <li><strong>Collaboration:</strong> Easy sharing across workspace, shared groups, and private domains.</li>
    <li><strong>Embedded Views:</strong> Dynamic Kanban, List, and Calendar items embedded in articles.</li>
</ul>
<h2>4. Success Metrics</h2>
<ol>
    <li>Adoption rate across active users exceeding 80%</li>
    <li>Reduction in task completion time by 30%</li>
</ol>`;
        }

        const articleId = this.state.currentArticle.id;
        this.state.currentArticle.name = title;
        this.state.currentArticle.body_html = bodyHtml;
        this.state.showAIDialog = false;
        this.state.aiGenerating = false;
        this.state.editorKey++;

        await this.orm.write("knowledge.management.article", [articleId], {
            name: title,
            body_html: bodyHtml,
        });
        await this._loadSidebar();

        this.notification.add("Article successfully generated with AI!", { type: "success" });
    }

    // ── Template Browser & Loader ─────────────────────────────────

    async onBrowseTemplates() {
        try {
            const templates = await this.orm.searchRead(
                "knowledge.management.article.template",
                [],
                ["id", "name", "icon", "body_html"]
            );
            this.state.availableTemplates = templates || [];
            this.state.showTemplateDialog = true;
        } catch (e) {
            console.error("Failed to load templates", e);
        }
    }

    onCloseTemplateDialog() {
        this.state.showTemplateDialog = false;
    }

    async onSelectTemplate(tmpl) {
        if (!this.state.currentArticle) return;
        const articleId = this.state.currentArticle.id;
        const bodyHtml = tmpl.body_html || "<h1>Template</h1><p><br></p>";

        this.state.currentArticle.name = tmpl.name;
        this.state.currentArticle.icon = tmpl.icon || "📄";
        this.state.currentArticle.body_html = bodyHtml;
        this.state.showTemplateDialog = false;
        this.state.editorKey++;

        await this.orm.write("knowledge.management.article", [articleId], {
            name: tmpl.name,
            icon: tmpl.icon || "📄",
            body_html: bodyHtml,
        });
        await this._loadSidebar();

        this.notification.add(`Template "${tmpl.name}" applied!`, { type: "success" });
    }

    // ── Auto-save ─────────────────────────────────────────────────

    _scheduleBodySave(articleId, html, urgent = false) {
        if (this._bodySaveTimer) clearTimeout(this._bodySaveTimer);
        const delay = urgent ? 0 : 700;
        this._bodySaveTimer = setTimeout(async () => {
            try {
                await this.orm.write("knowledge.management.article", [articleId], {
                    body_html: html,
                });
                if (this.state.currentArticle && this.state.currentArticle.id === articleId) {
                    this.state.currentArticle.body_html = html;
                }
            } catch (e) {
                console.warn("Auto-save failed", e);
            }
        }, delay);
    }

    // ── Sidebar Interactions ──────────────────────────────────────

    async onSelectArticle(articleId) {
        if (this.state.currentArticle?.id === articleId) return;
        await this.openArticle(articleId);
    }

    async onToggleExpand(articleId) {
        const ids = this.state.expandedIds;
        const idx = ids.indexOf(articleId);
        if (idx >= 0) {
            this.state.expandedIds.splice(idx, 1);
        } else {
            this.state.expandedIds.push(articleId);
            if (!this.state.childrenMap[articleId]) {
                const children = await this.orm.call(
                    "knowledge.management.article",
                    "get_article_children",
                    [articleId]
                );
                this.state.childrenMap[articleId] = children;
            }
        }
    }

    async onNewChildArticle(parentId) {
        await this.onNewArticle(parentId);
        if (!this.state.expandedIds.includes(parentId)) {
            this.state.expandedIds.push(parentId);
        }
    }

    onArticleQuickMenu(ev, article) {
        ev.stopPropagation();
        ev.preventDefault();
        const rect = ev.currentTarget.getBoundingClientRect();
        const viewportHeight = window.innerHeight;
        let y = rect.top;
        if (y + 320 > viewportHeight) {
            y = Math.max(10, viewportHeight - 330);
        }
        this.state.sidebarMenu = {
            isOpen: true,
            article: article,
            x: rect.right + 6,
            y: y,
        };
    }

    onCloseSidebarMenu() {
        if (this.state.sidebarMenu) {
            this.state.sidebarMenu.isOpen = false;
        }
    }

    onSidebarOpenNewTab(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        const url = window.location.origin + window.location.pathname + `?action=hudson_knowledge.action_knowledge_management#id=${article.id}&model=knowledge.management.article`;
        window.open(url, "_blank");
    }

    async onSidebarToggleFavorite(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        const res = await this.orm.call(
            "knowledge.management.article",
            "action_set_favorite",
            [[article.id]]
        );
        article.is_user_favorite = typeof res === "boolean" ? res : !article.is_user_favorite;
        if (this.state.currentArticle && this.state.currentArticle.id === article.id) {
            this.state.currentArticle.is_user_favorite = article.is_user_favorite;
        }
        this._syncArticleToSidebar(article.id, { is_user_favorite: article.is_user_favorite });
        await this._loadSidebar();
    }

    async onSetArticleVisibility(article, newVisibility) {
        this.onCloseSidebarMenu();
        this.state.showKebab = false;
        if (!article || !newVisibility) return;
        await this.orm.write(
            "knowledge.management.article",
            [article.id],
            { visibility: newVisibility }
        );
        article.visibility = newVisibility;
        if (this.state.currentArticle && this.state.currentArticle.id === article.id) {
            this.state.currentArticle.visibility = newVisibility;
        }
        this._syncArticleToSidebar(article.id, { visibility: newVisibility });
        await this._loadSidebar();
    }

    onSidebarShare(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Share Article",
            res_model: "knowledge.management.article",
            res_id: article.id,
            views: [[false, "form"]],
            target: "new",
        });
    }

    async onSidebarRename(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        const newName = await this.promptDialog({
            title: "Rename Article",
            label: "Article Name",
            defaultValue: article.name,
        });
        if (newName && newName.trim() && newName !== article.name) {
            article.name = newName.trim();
            await this.orm.write("knowledge.management.article", [article.id], { name: article.name });
            if (this.state.currentArticle && this.state.currentArticle.id === article.id) {
                this.state.currentArticle.name = article.name;
            }
            await this._loadSidebar();
        }
    }

    onSidebarMoveTo(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Move Article To",
            res_model: "knowledge.management.article",
            views: [[false, "list"]],
            target: "new",
            domain: [["id", "!=", article.id]],
        });
    }

    async onSidebarCreateCopy(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        const res = await this.orm.call(
            "knowledge.management.article",
            "action_create_copy",
            [[article.id]]
        );
        await this._loadSidebar();
        if (res && res.res_id) {
            await this.openArticle(res.res_id);
        }
    }

    async onSidebarMoveToTrash(article) {
        this.onCloseSidebarMenu();
        if (!article) return;
        const artId = article.id;
        this._removeArticleFromSidebarState(artId);
        await this.orm.call(
            "knowledge.management.article",
            "action_move_to_trash",
            [[artId]]
        );
        await this._loadSidebar();
        await this._refreshExpandedChildren();
        if (this.state.currentArticle && this.state.currentArticle.id === artId) {
            const topId = await this.orm.call(
                "knowledge.management.article",
                "get_top_article",
                []
            );
            if (topId) {
                await this.openArticle(topId);
            } else {
                this.state.currentArticle = null;
            }
        }
        this.notification.add("Article moved to trash", { type: "info" });
    }

    getArticleLastEdited(article) {
        if (!article || !article.write_date) return "recently";
        return this._formatRelativeTime(article.write_date);
    }

    onSearch() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Search Articles",
            res_model: "knowledge.management.article",
            views: [[false, "list"], [false, "form"]],
            domain: [["active", "=", true]],
            target: "current",
        });
    }

    onShare() {
        if (!this.state.currentArticle) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Share Article",
            res_model: "knowledge.management.article",
            res_id: this.state.currentArticle.id,
            views: [[false, "form"]],
            target: "new",
        });
    }

    onOpenTrash() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Trash",
            res_model: "knowledge.management.article",
            views: [[false, "list"], [false, "form"]],
            domain: [["active", "=", false]],
            context: { search_default_trash: 1 },
            target: "current",
        });
    }

    // ── Toolbar & Kebab Actions ───────────────────────────────────

    onToggleKebab(ev) {
        ev.stopPropagation();
        this.state.showKebab = !this.state.showKebab;
    }

    _onDocumentClick(ev) {
        if (this.state.showKebab) {
            const kebab = this.kebabMenu.el;
            if (kebab && !kebab.contains(ev.target)) {
                this.state.showKebab = false;
            }
        }
        if (this.state.sidebarMenu?.isOpen) {
            this.state.sidebarMenu.isOpen = false;
        }
    }

    async onToggleFavorite() {
        if (!this.state.currentArticle) return;
        const art = this.state.currentArticle;
        const res = await this.orm.call(
            "knowledge.management.article",
            "action_set_favorite",
            [[art.id]]
        );
        art.is_user_favorite = typeof res === "boolean" ? res : !art.is_user_favorite;
        this._syncArticleToSidebar(art.id, { is_user_favorite: art.is_user_favorite });
        await this._loadSidebar();
    }

    // ── Emoji & Icon Handlers (Image 1) ───────────────────────────

    openEmojiPicker(targetEl) {
        if (this.emojiPopover.isOpen) {
            this.emojiPopover.close();
            return;
        }
        const target = targetEl || this.titleEmojiRef?.el || this.toolbarEmojiRef?.el || document.body;
        this.emojiPopover.open(target, {
            onSelect: (emoji) => {
                if (!this.state.currentArticle) return;
                this.state.currentArticle.icon = emoji;
                this._syncArticleToSidebar(this.state.currentArticle.id, { icon: emoji });
                this._updateArticleField("icon", emoji);
                this.emojiPopover.close();
            },
            onRemove: () => {
                if (!this.state.currentArticle) return;
                this.state.currentArticle.icon = "";
                this._syncArticleToSidebar(this.state.currentArticle.id, { icon: "📄" });
                this._updateArticleField("icon", "");
                this.emojiPopover.close();
            },
            close: () => this.emojiPopover.close(),
        });
    }

    onEmojiClick(ev) {
        ev.stopPropagation();
        this.openEmojiPicker(ev.currentTarget);
    }

    onAddIcon(ev) {
        this.state.showKebab = false;
        const target = ev?.currentTarget || this.titleEmojiRef?.el || this.toolbarEmojiRef?.el;
        this.openEmojiPicker(target);
    }

    // ── Cover Image Handlers (Images 2 & 3) ────────────────────────

    get filteredCoverImages() {
        const query = (this.state.coverSearchQuery || "").trim().toLowerCase();
        const cat = this.state.coverActiveCategory || "all";
        return CURATED_COVERS.filter((img) => {
            const matchesCat = cat === "all" || img.category === cat;
            const matchesQuery =
                !query ||
                (img.photographer && img.photographer.toLowerCase().includes(query)) ||
                (img.category && img.category.toLowerCase().includes(query)) ||
                (img.id && img.id.toLowerCase().includes(query));
            return matchesCat && matchesQuery;
        }).slice(0, this.state.coverPageLimit);
    }

    onCoverSearchInput(ev) {
        this.state.coverSearchQuery = ev.target.value;
    }

    onCoverCategoryChange(ev) {
        this.state.coverActiveCategory = ev.target.value;
    }

    onLoadMoreCovers() {
        this.state.coverPageLimit += 15;
    }

    async onAddCover() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        this.openCoverMediaDialog();
    }

    async onOpenCoverModal() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        this.openCoverMediaDialog();
    }

    openCoverMediaDialog() {
        if (!this.state.currentArticle) return;
        this.dialogService.add(MediaDialog, {
            resModel: "knowledge.management.article",
            resId: this.state.currentArticle.id,
            onlyImages: true,
            save: (element) => {
                if (!element) return;
                let src = "";
                if (typeof element === "string") {
                    src = element;
                } else if (element.getAttribute) {
                    src = element.getAttribute("src") || element.getAttribute("data-src") || "";
                } else if (element.src) {
                    src = element.src;
                }
                if (src) {
                    this.state.currentArticle.cover_image_url = src;
                    this._updateArticleField("cover_image_url", src);
                }
            },
        });
    }

    onCloseCoverModal() {
        this.state.showCoverModal = false;
    }

    async onSelectCoverImage(url) {
        if (!url || !this.state.currentArticle) return;
        this.state.showCoverModal = false;
        this.state.currentArticle.cover_image_url = url;
        await this._updateArticleField("cover_image_url", url);
    }

    onUploadCoverFile(ev) {
        const file = ev.target?.files?.[0];
        if (!file || !this.state.currentArticle) return;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const dataUrl = e.target.result;
            this.state.showCoverModal = false;
            this.state.currentArticle.cover_image_url = dataUrl;
            await this._updateArticleField("cover_image_url", dataUrl);
        };
        reader.readAsDataURL(file);
    }

    onToggleAddUrlMode() {
        this.state.showAddUrlTray = !this.state.showAddUrlTray;
        if (this.state.showAddUrlTray) {
            this.state.customCoverUrl = "";
        }
    }

    async onApplyCustomUrl() {
        const url = (this.state.customCoverUrl || "").trim();
        if (!url || !this.state.currentArticle) return;
        this.state.showCoverModal = false;
        this.state.currentArticle.cover_image_url = url;
        await this._updateArticleField("cover_image_url", url);
    }

    onAddUrlKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onApplyCustomUrl();
        } else if (ev.key === "Escape") {
            this.state.showAddUrlTray = false;
        }
    }

    onStartRepositionCover() {
        if (!this.state.currentArticle) return;
        this.state.isRepositioningCover = true;
        this.state.savedCoverPosition = this.state.currentArticle.cover_position || "50%";
    }

    onCoverMouseDown(ev) {
        if (!this.state.isRepositioningCover) return;
        ev.preventDefault();
        const startY = ev.clientY;
        const startPos = parseFloat(this.state.currentArticle.cover_position || "50%") || 50;
        const coverEl = this.coverImg?.el;
        const rect = coverEl ? coverEl.getBoundingClientRect() : { height: 240 };

        const onMouseMove = (moveEv) => {
            const deltaY = moveEv.clientY - startY;
            const percentDelta = (deltaY / rect.height) * 100;
            let newPos = Math.round(startPos - percentDelta);
            if (newPos < 0) newPos = 0;
            if (newPos > 100) newPos = 100;
            this.state.currentArticle.cover_position = newPos + "%";
        };

        const onMouseUp = () => {
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
    }

    async onSaveCoverPosition() {
        if (!this.state.currentArticle) return;
        const pos = this.state.currentArticle.cover_position || "50%";
        this.state.isRepositioningCover = false;
        await this._updateArticleField("cover_position", pos);
        this.notification.add("Cover position saved", { type: "info" });
    }

    onCancelCoverPosition() {
        if (!this.state.currentArticle) return;
        this.state.currentArticle.cover_position = this.state.savedCoverPosition || "50%";
        this.state.isRepositioningCover = false;
    }

    async onRemoveCover() {
        if (!this.state.currentArticle) return;
        this.state.currentArticle.cover_image_url = false;
        await this._updateArticleField("cover_image_url", false);
    }

    async onToggleFullWidth() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        const newVal = !this.state.currentArticle.full_width;
        await this._updateArticleField("full_width", newVal);
    }

    onMoveTo() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Move Article To",
            res_model: "knowledge.management.article",
            views: [[false, "list"]],
            target: "new",
            domain: [["id", "!=", this.state.currentArticle.id]],
        });
    }

    async onToggleLock() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        await this.orm.call(
            "knowledge.management.article",
            "action_toggle_lock",
            [[this.state.currentArticle.id]]
        );
        this.state.currentArticle.is_locked = !this.state.currentArticle.is_locked;
        this.state.editorKey++;
    }

    async onCreateCopy() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        const copied = await this.orm.call(
            "knowledge.management.article",
            "action_create_copy",
            [[this.state.currentArticle.id]]
        );
        await this._loadSidebar();
        if (copied && copied[0]) await this.openArticle(copied[0]);
    }

    onDownloadPdf() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        window.open(
            `/knowledge/article/${this.state.currentArticle.id}/pdf`,
            "_blank"
        );
    }

    async onAddToTemplates() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        const art = this.state.currentArticle;
        await this.orm.create("knowledge.management.article.template", [{
            name: art.name,
            icon: art.icon || "📄",
            body_html: art.body_html || "<p><br></p>",
        }]);
        this.notification.add("Article added to Templates!", { type: "success" });
    }

    async onMoveToTrash() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        const artId = this.state.currentArticle.id;
        this._removeArticleFromSidebarState(artId);
        await this.orm.call(
            "knowledge.management.article",
            "action_move_to_trash",
            [[artId]]
        );
        this.state.currentArticle = null;
        await this._loadSidebar();
        await this._refreshExpandedChildren();
        const topId = await this.orm.call(
            "knowledge.management.article",
            "get_top_article",
            []
        );
        if (topId) await this.openArticle(topId);
        this.notification.add("Article moved to trash", { type: "info" });
    }

    async _updateArticleField(field, value) {
        if (!this.state.currentArticle) return;
        await this.orm.write(
            "knowledge.management.article",
            [this.state.currentArticle.id],
            { [field]: value }
        );
        this.state.currentArticle[field] = value;
    }

    // ── Version History Methods (Matching Image 1) ────────────────
    async onOpenVersionHistory() {
        this.state.showKebab = false;
        if (!this.state.currentArticle) return;
        this.state.historyLoading = true;
        this.state.showHistoryModal = true;
        try {
            const versions = await this.orm.call(
                "knowledge.management.article",
                "get_version_history",
                [[this.state.currentArticle.id]]
            );
            this.state.historyVersions = versions || [];
            this.state.selectedHistoryVersion = this.state.historyVersions.length > 0 ? this.state.historyVersions[0] : null;
            this.state.historyShowComparison = true;
        } catch (err) {
            console.error("Failed to load version history", err);
            this.notification.add("Could not load version history", { type: "danger" });
        } finally {
            this.state.historyLoading = false;
        }
    }

    onCloseVersionHistory() {
        this.state.showHistoryModal = false;
    }

    onToggleHistoryFullscreen() {
        this.state.historyIsFullscreen = !this.state.historyIsFullscreen;
    }

    onSelectHistoryVersion(v) {
        this.state.selectedHistoryVersion = v;
    }

    onToggleHistoryComparison() {
        this.state.historyShowComparison = !this.state.historyShowComparison;
    }

    async onRestoreHistoryVersion() {
        if (!this.state.currentArticle || !this.state.selectedHistoryVersion) return;
        const vId = this.state.selectedHistoryVersion.id;
        try {
            await this.orm.call(
                "knowledge.management.article",
                "action_restore_version",
                [[this.state.currentArticle.id], vId]
            );
            this.state.currentArticle.name = this.state.selectedHistoryVersion.name;
            this.state.currentArticle.body_html = this.state.selectedHistoryVersion.body_html;
            this.state.editorKey++;
            this.state.showHistoryModal = false;
            this.notification.add("Article restored to selected version", { type: "success" });
            await this._loadSidebar();
        } catch (err) {
            console.error("Failed to restore version", err);
            this.notification.add("Failed to restore version", { type: "danger" });
        }
    }

    formatHistoryRelativeTime(isoString) {
        if (!isoString) return "Recently";
        try {
            const date = new Date(isoString);
            const now = new Date();
            const diffSec = Math.floor((now - date) / 1000);
            if (diffSec < 60) return "Just now";
            const diffMin = Math.floor(diffSec / 60);
            if (diffMin < 60) return `${diffMin} minute${diffMin > 1 ? "s" : ""} ago`;
            const diffHours = Math.floor(diffMin / 60);
            if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
            const diffDays = Math.floor(diffHours / 24);
            if (diffDays === 1) return "Yesterday";
            if (diffDays < 30) return `${diffDays} days ago`;
            return date.toLocaleDateString();
        } catch {
            return "Recently";
        }
    }

    _replaceDynamicBlocks(html) {
        if (!html) return "";
        let clean = html.replace(/<div[^>]*class="[^"]*o_knowledge_embedded_view_container[^"]*"[^>]*>[\s\S]*?<\/div>/gi,
            '<div class="o_history_dynamic_block"><span class="o_history_cube_icon">📦</span> Dynamic element</div>');
        clean = clean.replace(/<div[^>]*data-embedded-view="[^"]*"[^>]*>[\s\S]*?<\/div>/gi,
            '<div class="o_history_dynamic_block"><span class="o_history_cube_icon">📦</span> Dynamic element</div>');
        return clean;
    }

    getHistoryDisplayHtml() {
        if (!this.state.selectedHistoryVersion) return "";
        const selClean = this._replaceDynamicBlocks(this.state.selectedHistoryVersion.body_html || "");
        if (!this.state.historyShowComparison) {
            return markup(selClean);
        }
        const curClean = this._replaceDynamicBlocks(this.state.currentArticle?.body_html || "");
        const diff = computeHtmlDiff(selClean, curClean);
        return markup(diff);
    }

    getHistorySelectedTitle() {
        return this.state.selectedHistoryVersion?.name || this.state.currentArticle?.name || "Untitled";
    }

    getLastEditedRelative() {
        const art = this.state.currentArticle;
        if (!art || !art.write_date) return "just now";
        return this._formatRelativeTime(art.write_date);
    }
}

// ─── Register Action in Registry ─────────────────────────────────
registry.category("actions").add(
    "hudson_knowledge.action_knowledge",
    KnowledgeClientAction
);
