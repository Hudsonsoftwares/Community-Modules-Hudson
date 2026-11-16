/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, proxy, signal } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { iconShapes } from "./floor_plan_icons";

const REFRESH_MS = 60000;
const GRID = 0.5; // snap step, in % of the canvas
const HISTORY_LIMIT = 50;
const SWATCHES = ["#0891b2", "#2563eb", "#7c3aed", "#db2777", "#dc2626", "#d97706", "#16a34a", "#0d9488", "#475569", "#0f172a"];

const round = (v) => Math.round(v / GRID) * GRID;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const normAngle = (deg) => ((Math.round(deg) % 360) + 360) % 360;

/**
 * Clinic floor plan of the selected company.
 * View mode: rooms, equipment and live elements (click an element, or linked equipment, to open its records).
 * Edit mode (Dental Administrators): add / move / resize / rename rooms; place dental equipment from the
 * icon library (move, scale, rotate, recolour, label, link to live data); drag live elements from the
 * palette (only installed modules are offered) and customise their icon and colour; undo; then save.
 */
export class DentalFloorPlan extends Component {
    static template = "dental_core.DentalFloorPlan";

    canvas = signal.ref();
    swatches = SWATCHES;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");

        this.state = proxy({
            loading: true,
            saving: false,
            editing: false,
            dirty: false,
            showFixtures: true,
            paletteTab: "equipment", // 'equipment' | 'live'
            category: "all",
            search: "",
            canUndo: false,
            data: {
                rooms: [], elements: [], fixtures: [], palette: [], room_types: [],
                fixture_catalog: [], fixture_categories: [], can_edit: false, background_url: false,
            },
            selected: null, // { kind: 'room' | 'element' | 'fixture', uid }
        });
        this.newId = 0;
        this.drag = null;
        this.history = [];
        this.lastEditKey = null;

        this._onMove = (ev) => this.onPointerMove(ev);
        this._onUp = () => this.onPointerUp();
        this._onKey = (ev) => this.onKeyDown(ev);

        onWillStart(() => this.load());
        onMounted(() => {
            this.timer = setInterval(() => {
                if (!this.state.editing) {
                    this.load({ silent: true });
                }
            }, REFRESH_MS);
            window.addEventListener("keydown", this._onKey);
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            this.stopListening();
            window.removeEventListener("keydown", this._onKey);
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async load({ silent = false } = {}) {
        if (!silent) {
            this.state.loading = true;
        }
        try {
            const data = await this.orm.call("dental.floor.plan", "get_floor_plan", []);
            this.setData(data);
        } catch (e) {
            console.error("Floor plan load failed:", e);
            if (!silent) {
                this.notification.add("Could not load the clinic floor plan.", { type: "danger" });
            }
        } finally {
            this.state.loading = false;
        }
    }

    setData(data) {
        // Local uids so new (unsaved) items can be edited like saved ones
        data.rooms.forEach((r) => (r.uid = `r${r.id}`));
        data.elements.forEach((e) => (e.uid = `e${e.id}`));
        data.fixtures = data.fixtures || [];
        data.fixtures.forEach((f) => (f.uid = `f${f.id}`));
        this.state.data = data;
        this.state.dirty = false;
        this.state.selected = null;
        this.resetHistory();
    }

    get isEmpty() {
        const { rooms, elements, fixtures } = this.state.data;
        return !rooms.length && !elements.length && !fixtures.length;
    }

    findSelected(kind) {
        const sel = this.state.selected;
        if (!sel || sel.kind !== kind) {
            return null;
        }
        return this.listFor(kind).find((item) => item.uid === sel.uid) || null;
    }

    get selectedRoom() {
        return this.findSelected("room");
    }

    get selectedElement() {
        return this.findSelected("element");
    }

    get selectedFixture() {
        return this.findSelected("fixture");
    }

    listFor(kind) {
        const data = this.state.data;
        return kind === "room" ? data.rooms : kind === "element" ? data.elements : data.fixtures;
    }

    isSelected(item) {
        return Boolean(this.state.selected && this.state.selected.uid === item.uid);
    }

    roomTypeColor(key) {
        const type = this.state.data.room_types.find((t) => t.key === key);
        return type ? type.color : "#f8fafc";
    }

    roomTypeLabel(key) {
        const type = this.state.data.room_types.find((t) => t.key === key);
        return type ? type.label : "";
    }

    fixtureSpec(key) {
        return this.state.data.fixture_catalog.find((s) => s.key === key);
    }

    paletteSpec(key) {
        return this.state.data.palette.find((p) => p.key === key);
    }

    iconShapes(key) {
        return iconShapes(key);
    }

    get filteredFixtureCatalog() {
        const term = this.state.search.trim().toLowerCase();
        return this.state.data.fixture_catalog.filter(
            (spec) =>
                (this.state.category === "all" || spec.category === this.state.category) &&
                (!term || spec.label.toLowerCase().includes(term) || spec.category_label.toLowerCase().includes(term))
        );
    }

    fixtureTitle(fx) {
        const name = fx.label ? `${fx.label} (${fx.name})` : fx.name;
        if (this.state.editing) {
            return `${name} - drag to move`;
        }
        const link = fx.link_key && this.paletteSpec(fx.link_key);
        return link ? `${name} - click to open ${link.label}` : name;
    }

    fixtureStyle(fx) {
        return `left: ${fx.x}%; top: ${fx.y}%; width: ${fx.size}%; --dfp-fx: ${fx.color};`;
    }

    // ------------------------------------------------------------------
    // Undo history
    // ------------------------------------------------------------------

    snapshot() {
        const { rooms, elements, fixtures } = this.state.data;
        return JSON.stringify({ rooms, elements, fixtures });
    }

    resetHistory() {
        this.history = [];
        this.lastEditKey = null;
        this.state.canUndo = false;
    }

    pushHistory(editKey = null) {
        if (editKey && editKey === this.lastEditKey) {
            return; // typing in the same field is one undo step
        }
        this.lastEditKey = editKey;
        this.history.push(this.snapshot());
        if (this.history.length > HISTORY_LIMIT) {
            this.history.shift();
        }
        this.state.canUndo = true;
        this.state.dirty = true;
    }

    undo() {
        const last = this.history.pop();
        if (!last) {
            return;
        }
        const { rooms, elements, fixtures } = JSON.parse(last);
        Object.assign(this.state.data, { rooms, elements, fixtures });
        const sel = this.state.selected;
        if (sel && !this.listFor(sel.kind).some((item) => item.uid === sel.uid)) {
            this.state.selected = null;
        }
        this.lastEditKey = null;
        this.state.canUndo = this.history.length > 0;
        this.state.dirty = true;
    }

    // ------------------------------------------------------------------
    // Edit mode
    // ------------------------------------------------------------------

    startEditing() {
        this.state.editing = true;
        this.state.selected = null;
        this.state.showFixtures = true;
        this.resetHistory();
    }

    async cancelEditing() {
        this.state.editing = false;
        await this.load();
    }

    async save() {
        this.state.saving = true;
        try {
            const { rooms, elements, fixtures } = this.state.data;
            const dbId = (item) => (typeof item.id === "number" ? item.id : false);
            const data = await this.orm.call("dental.floor.plan", "save_floor_plan", [
                rooms.map((r) => ({
                    id: dbId(r), name: r.name, room_type: r.room_type, color: r.color,
                    x: r.x, y: r.y, w: r.w, h: r.h,
                })),
                elements.map((e) => ({
                    id: dbId(e), key: e.key, x: e.x, y: e.y, custom_label: e.custom_label || "",
                    svg: e.svg || false, custom_color: e.custom_color || "",
                })),
                fixtures.map((f) => ({
                    id: dbId(f), key: f.key, label: f.label || "", x: f.x, y: f.y,
                    size: f.size, rotation: f.rotation, color: f.color, link_key: f.link_key || false,
                })),
            ]);
            this.setData(data);
            this.state.editing = false;
            this.notification.add("Floor plan saved.", { type: "success" });
        } finally {
            this.state.saving = false;
        }
    }

    loadDefault() {
        const run = async () => {
            const data = await this.orm.call("dental.floor.plan", "load_default_floor_plan", []);
            this.setData(data);
            this.state.editing = true;
        };
        if (this.isEmpty) {
            return run();
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Load standard layout",
            body: "This replaces the current rooms, equipment and elements of this clinic with a standard layout.",
            confirmLabel: "Replace layout",
            confirm: run,
            cancel: () => {},
        });
    }

    addRoom() {
        this.pushHistory();
        const uid = `n${++this.newId}`;
        this.state.data.rooms.push({
            uid, id: uid, name: "New Room", room_type: "other", type_label: "Other",
            color: this.roomTypeColor("other"), x: 40, y: 35, w: 20, h: 25,
        });
        this.state.selected = { kind: "room", uid };
    }

    addElement(spec, x = 50, y = 50) {
        this.pushHistory();
        const uid = `n${++this.newId}`;
        this.state.data.elements.push({
            uid, id: uid, key: spec.key, label: spec.label, icon: spec.icon, color: spec.color,
            svg: false, custom_color: "", custom_label: "",
            x: clamp(round(x), 3, 97), y: clamp(round(y), 4, 96), value: "", caption: "Save to see live data", status: "idle",
        });
        this.state.selected = { kind: "element", uid };
    }

    addFixture(spec, x = 50, y = 50) {
        this.pushHistory();
        const uid = `n${++this.newId}`;
        this.state.data.fixtures.push({
            uid, id: uid, key: spec.key, name: spec.label, label: "", color: spec.color,
            size: spec.size, rotation: 0, link_key: false, status: false,
            x: clamp(round(x), 0, 100), y: clamp(round(y), 0, 100),
        });
        this.state.selected = { kind: "fixture", uid };
    }

    removeSelected() {
        const sel = this.state.selected;
        if (!sel) {
            return;
        }
        const list = this.listFor(sel.kind);
        const idx = list.findIndex((item) => item.uid === sel.uid);
        if (idx >= 0) {
            this.pushHistory();
            list.splice(idx, 1);
        }
        this.state.selected = null;
    }

    duplicateSelected() {
        const sel = this.state.selected;
        const item = sel && this.listFor(sel.kind).find((i) => i.uid === sel.uid);
        if (!item) {
            return;
        }
        this.pushHistory();
        const uid = `n${++this.newId}`;
        const copy = { ...JSON.parse(JSON.stringify(item)), uid, id: uid };
        if (sel.kind === "room") {
            copy.x = clamp(item.x + 3, 0, 100 - item.w);
            copy.y = clamp(item.y + 3, 0, 100 - item.h);
        } else {
            copy.x = clamp(item.x + 3, 0, 100);
            copy.y = clamp(item.y + 4, 0, 100);
        }
        if (sel.kind === "element") {
            copy.value = "";
            copy.caption = "Save to see live data";
            copy.status = "idle";
        }
        this.listFor(sel.kind).push(copy);
        this.state.selected = { kind: sel.kind, uid };
    }

    /** Move the selected equipment above (front) or below (back) the other equipment. */
    reorderSelected(toFront) {
        const fx = this.selectedFixture;
        if (!fx) {
            return;
        }
        this.pushHistory();
        const list = this.state.data.fixtures;
        list.splice(list.indexOf(fx), 1);
        toFront ? list.push(fx) : list.unshift(fx);
    }

    select(kind, item, ev) {
        if (!this.state.editing) {
            return;
        }
        ev.stopPropagation();
        this.state.selected = { kind, uid: item.uid };
    }

    clearSelection() {
        if (this.state.editing) {
            this.state.selected = null;
        }
    }

    onRoomField(field, ev) {
        const room = this.selectedRoom;
        if (!room) {
            return;
        }
        this.pushHistory(`${room.uid}:${field}`);
        room[field] = ev.target.value;
        if (field === "room_type") {
            room.color = this.roomTypeColor(room.room_type);
            room.type_label = this.roomTypeLabel(room.room_type);
        }
    }

    onElementLabel(ev) {
        const element = this.selectedElement;
        if (element) {
            this.pushHistory(`${element.uid}:label`);
            element.custom_label = ev.target.value;
            element.label = ev.target.value || this.paletteSpec(element.key)?.label || element.label;
        }
    }

    setElementIcon(svgKey) {
        const element = this.selectedElement;
        if (element && element.svg !== svgKey) {
            this.pushHistory();
            element.svg = svgKey || false;
        }
    }

    setElementColor(color) {
        const element = this.selectedElement;
        if (!element) {
            return;
        }
        this.pushHistory(`${element.uid}:color`);
        element.custom_color = color || "";
        element.color = color || this.paletteSpec(element.key)?.color || element.color;
    }

    onFixtureField(field, value) {
        const fx = this.selectedFixture;
        if (!fx) {
            return;
        }
        this.pushHistory(`${fx.uid}:${field}`);
        if (field === "size") {
            fx.size = clamp(parseFloat(value) || fx.size, 1.5, 25);
        } else if (field === "rotation") {
            fx.rotation = normAngle(parseFloat(value) || 0);
        } else if (field === "link_key") {
            fx.link_key = value || false;
        } else {
            fx[field] = value;
        }
    }

    rotateSelected(delta) {
        const fx = this.selectedFixture;
        if (fx) {
            this.pushHistory();
            fx.rotation = normAngle(fx.rotation + delta);
        }
    }

    resetFixtureColor() {
        const fx = this.selectedFixture;
        const spec = fx && this.fixtureSpec(fx.key);
        if (spec) {
            this.onFixtureField("color", spec.color);
        }
    }

    // ------------------------------------------------------------------
    // Keyboard shortcuts (edit mode)
    // ------------------------------------------------------------------

    onKeyDown(ev) {
        if (!this.state.editing) {
            return;
        }
        const tag = ev.target && ev.target.tagName;
        if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || (ev.target && ev.target.isContentEditable)) {
            return;
        }
        const mod = ev.ctrlKey || ev.metaKey;
        if (mod && ev.key.toLowerCase() === "z") {
            ev.preventDefault();
            this.undo();
            return;
        }
        const sel = this.state.selected;
        if (!sel) {
            return;
        }
        const item = this.listFor(sel.kind).find((i) => i.uid === sel.uid);
        if (!item) {
            return;
        }
        if (mod && ev.key.toLowerCase() === "d") {
            ev.preventDefault();
            this.duplicateSelected();
        } else if (ev.key === "Delete" || ev.key === "Backspace") {
            ev.preventDefault();
            this.removeSelected();
        } else if (ev.key === "Escape") {
            this.state.selected = null;
        } else if (ev.key.startsWith("Arrow")) {
            ev.preventDefault();
            const step = ev.shiftKey ? 2.5 : GRID;
            const dx = ev.key === "ArrowLeft" ? -step : ev.key === "ArrowRight" ? step : 0;
            const dy = ev.key === "ArrowUp" ? -step : ev.key === "ArrowDown" ? step : 0;
            this.pushHistory(`${item.uid}:nudge`);
            const maxX = sel.kind === "room" ? 100 - item.w : 100;
            const maxY = sel.kind === "room" ? 100 - item.h : 100;
            item.x = clamp(round(item.x + dx), 0, maxX);
            item.y = clamp(round(item.y + dy), 0, maxY);
        } else if (sel.kind === "fixture" && !mod && ev.key.toLowerCase() === "r") {
            ev.preventDefault();
            this.rotateSelected(ev.shiftKey ? -90 : 90);
        } else if (sel.kind === "fixture" && !mod && ["+", "=", "-", "_"].includes(ev.key)) {
            ev.preventDefault();
            const grow = ev.key === "+" || ev.key === "=";
            this.onFixtureField("size", item.size + (grow ? 0.5 : -0.5));
        }
    }

    // ------------------------------------------------------------------
    // Dragging (pointer events: move/resize rooms, move/scale/rotate equipment, move elements)
    // ------------------------------------------------------------------

    canvasPercent(ev) {
        const rect = this.canvas().getBoundingClientRect();
        return {
            x: ((ev.clientX - rect.left) / rect.width) * 100,
            y: ((ev.clientY - rect.top) / rect.height) * 100,
        };
    }

    startDrag(ev, kind, item, mode = "move") {
        if (!this.state.editing || ev.button !== 0) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.state.selected = { kind, uid: item.uid };
        const start = this.canvasPercent(ev);
        this.drag = {
            item, kind, mode, start, pushed: false,
            orig: { x: item.x, y: item.y, w: item.w, h: item.h, size: item.size, rotation: item.rotation },
        };
        window.addEventListener("pointermove", this._onMove);
        window.addEventListener("pointerup", this._onUp);
    }

    onPointerMove(ev) {
        const drag = this.drag;
        if (!drag) {
            return;
        }
        if (!drag.pushed) {
            // One undo step per drag, recorded only once something actually moves
            drag.pushed = true;
            this.pushHistory();
        }
        const pos = this.canvasPercent(ev);
        const dx = pos.x - drag.start.x;
        const dy = pos.y - drag.start.y;
        const { item, orig, kind, mode } = drag;
        if (kind === "room" && mode === "resize") {
            item.w = clamp(round(orig.w + dx), 4, 100 - orig.x);
            item.h = clamp(round(orig.h + dy), 4, 100 - orig.y);
        } else if (kind === "room") {
            item.x = clamp(round(orig.x + dx), 0, 100 - orig.w);
            item.y = clamp(round(orig.y + dy), 0, 100 - orig.h);
        } else if (kind === "fixture" && (mode === "rotate" || mode === "scale")) {
            const rect = this.canvas().getBoundingClientRect();
            const cx = rect.left + (item.x / 100) * rect.width;
            const cy = rect.top + (item.y / 100) * rect.height;
            const px = ev.clientX - cx;
            const py = ev.clientY - cy;
            if (mode === "rotate") {
                // Handle sits above the icon: 0deg when the pointer is straight up. Snap to 15deg unless Shift.
                const deg = (Math.atan2(py, px) * 180) / Math.PI + 90;
                item.rotation = normAngle(ev.shiftKey ? deg : Math.round(deg / 15) * 15);
            } else {
                const half = Math.max(Math.abs(px), Math.abs(py));
                item.size = clamp(round(((2 * half) / rect.width) * 100), 1.5, 25);
            }
        } else if (kind === "fixture") {
            item.x = clamp(round(orig.x + dx), 0, 100);
            item.y = clamp(round(orig.y + dy), 0, 100);
        } else {
            item.x = clamp(round(orig.x + dx), 3, 97);
            item.y = clamp(round(orig.y + dy), 4, 96);
        }
    }

    onPointerUp() {
        this.drag = null;
        this.stopListening();
    }

    stopListening() {
        window.removeEventListener("pointermove", this._onMove);
        window.removeEventListener("pointerup", this._onUp);
    }

    // Palette -> canvas (HTML5 drag and drop)
    onPaletteDragStart(ev, kind, spec) {
        ev.dataTransfer.setData("text/plain", `${kind}:${spec.key}`);
        ev.dataTransfer.effectAllowed = "copy";
    }

    onCanvasDragOver(ev) {
        if (this.state.editing) {
            ev.preventDefault();
            ev.dataTransfer.dropEffect = "copy";
        }
    }

    onCanvasDrop(ev) {
        if (!this.state.editing) {
            return;
        }
        ev.preventDefault();
        const [kind, key] = ev.dataTransfer.getData("text/plain").split(":");
        const pos = this.canvasPercent(ev);
        if (kind === "fixture") {
            const spec = this.fixtureSpec(key);
            if (spec) {
                this.addFixture(spec, pos.x, pos.y);
            }
        } else {
            const spec = this.paletteSpec(key);
            if (spec) {
                this.addElement(spec, pos.x, pos.y);
            }
        }
    }

    // ------------------------------------------------------------------
    // View mode
    // ------------------------------------------------------------------

    async openElement(element) {
        if (this.state.editing) {
            return;
        }
        const action = await this.orm.call("dental.floor.plan", "action_open_element", [element.key]);
        if (action) {
            this.action.doAction(action);
        }
    }

    onFixtureClick(fx, ev) {
        if (this.state.editing) {
            this.select("fixture", fx, ev);
        } else if (fx.link_key) {
            this.openElement({ key: fx.link_key });
        }
    }

    openConfiguration() {
        this.action.doAction("dental_base.action_dental_clinic_configuration");
    }
}
