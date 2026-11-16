/** @odoo-module **/
// Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import { loadCSS, loadJS } from "@web/core/assets";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { usePopover } from "@web/core/popover/popover_hook";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { usePager } from "@web/search/pager_hook";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { Component, markRaw, onMounted, onWillStart, onWillUnmount, onWillUpdateProps, proxy, signal, useProps } from "@odoo/owl";
import { FsSlotPopover } from "../fs_schedule/fs_schedule_view";

const { DateTime } = luxon;

const COLORS = ["#017e84", "#714b67", "#e8543e", "#0d6efd", "#f0ad4e", "#198754", "#d63384", "#6f42c1", "#20c997", "#fd7e14", "#0dcaf0", "#6c757d"];
// Google Maps directions: at most 9 stops between origin and destination
const MAX_WAYPOINTS = 9;
// Mapbox Directions: at most 25 coordinates per request
const MAPBOX_MAX_COORDS = 25;
const MAPBOX_API = "https://api.mapbox.com";
const BANNER_KEY = "hudson_planning.fs_map.mapbox_banner_closed";

function sessionGet(key) {
    try {
        return window.sessionStorage.getItem(key);
    } catch {
        return null;
    }
}

function sessionSet(key, value) {
    try {
        window.sessionStorage.setItem(key, value);
    } catch {
        // private window / blocked storage: the banner just comes back
    }
}

/**
 * Map view of the shifts (``fs_map``), like Online's Planning map: the shifts
 * are pinned at their customer's address, coloured by group (resource by
 * default), with a side panel listing the groups and a Google Maps route per
 * group. Hovering a group or a shift of the panel highlights its pins.
 *
 * With a Mapbox token (Settings > Mapbox), the map uses Mapbox tiles and draws
 * the driving route of each group through its shifts in time order, with the
 * distance and travel time of each leg; a leg can be switched to one of the
 * other paths Mapbox proposes.
 */
export class FsMapController extends Component {
    static template = "hudson_planning.FsMapView";
    static components = { Layout, SearchBar, CogMenu };
    props = useProps();

    rootRef = signal.ref();
    mapRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.searchBarToggler = useSearchBarToggler();
        this.popover = usePopover(FsSlotPopover, { position: "top" });

        this.state = proxy({
            records: [],
            groups: [],
            groupFieldString: "",
            total: 0,
            offset: 0,
            limit: this.props.archInfo.limit,
            expanded: {},
            error: false,
            loading: true,
            // Mapbox
            mapboxToken: false,
            canSetMapboxToken: false,
            mapboxStatus: "none", // none | checking | valid | invalid
            mapboxError: "",
            bannerClosed: sessionGet(BANNER_KEY) === "1",
            routes: {},          // group id -> {legs: [...], error}
            routing: false,
            // Highlight
            hoverGroup: null,    // group id
            hoverRecords: [],    // record ids
            selectedLeg: null,   // {group, index}
        });
        this.map = null;
        this.tileLayer = null;
        this.markerLayers = [];
        this.markers = {};         // record id -> marker
        this.routeLayers = {};     // group id -> [polyline per leg]
        this.alternativeLayers = [];
        this.routeGeneration = 0;

        usePager(() => ({
            offset: this.state.offset,
            limit: this.state.limit,
            total: this.state.total,
            onUpdate: async ({ offset, limit }) => {
                this.state.offset = offset;
                this.state.limit = limit;
                await this.load();
            },
        }));
        useSetupAction({ rootRef: this.rootRef });

        onWillStart(async () => {
            this.isManager = await user.hasGroup("hudson_planning.group_planning_manager");
            await this.load(this.props);
        });
        onWillUpdateProps(async (nextProps) => {
            this.state.offset = 0;
            await this.load(nextProps);
        });
        onMounted(async () => {
            try {
                await loadCSS("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css");
                await loadJS("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js");
                const L = window.L;
                this.map = L.map(this.mapRef(), { zoomControl: true }).setView([20, 0], 2);
                // A popover anchored to a pin would stay behind when the map moves
                this.map.on("movestart zoomstart", () => this.popover.close());
                this.map.on("popupopen", (ev) => {
                    for (const link of ev.popup.getElement()?.querySelectorAll("[data-slot-id]") || []) {
                        link.addEventListener("click", (e) => {
                            e.preventDefault();
                            const marker = this.markers[parseInt(link.dataset.slotId)];
                            this.map.closePopup();
                            this.openSlotPopover(parseInt(link.dataset.slotId), marker?.getElement());
                        });
                    }
                });
                setTimeout(() => this.map && this.map.invalidateSize(), 200);
                await this.setupTiles();
                this.renderMap();
            } catch (e) {
                this.state.error = e.message || String(e);
            }
        });
        onWillUnmount(() => {
            this.routeGeneration++;
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
    }

    // -------------------------------------------------------------------------
    // Data
    // -------------------------------------------------------------------------

    async load(props = this.props) {
        this.state.loading = true;
        const data = await this.orm.call("fs.planning.slot", "get_map_view_data", [
            props.domain,
            props.groupBy.length ? props.groupBy : [this.props.archInfo.defaultGroupBy],
            this.state.offset,
            this.state.limit,
        ], { context: props.context });
        this.state.records = data.records;
        this.state.groups = data.groups;
        this.state.groupFieldString = data.group_field_string;
        this.state.total = data.total;
        this.state.canSetMapboxToken = data.can_set_mapbox_token;
        if (data.mapbox_token !== this.state.mapboxToken) {
            this.state.mapboxToken = data.mapbox_token;
            this.state.mapboxStatus = "none";
            if (this.map) {
                await this.setupTiles();
            }
        }
        // Few groups: all open (like Online), many: closed
        const open = data.groups.length <= 6;
        this.state.expanded = Object.fromEntries(data.groups.map((g) => [this.groupId(g), open]));
        this.state.hoverGroup = null;
        this.state.hoverRecords = [];
        this.state.selectedLeg = null;
        this.state.loading = false;
        this.renderMap();
    }

    groupId(group) {
        return String(group.key);
    }

    groupColor(group) {
        const index = this.state.groups.findIndex((g) => g.key === group.key);
        return COLORS[Math.max(index, 0) % COLORS.length];
    }

    groupRecords(group) {
        return this.state.records.filter((r) => r.group_key === group.key);
    }

    isExpanded(group) {
        return this.state.expanded[this.groupId(group)];
    }

    isLocated(record) {
        return Boolean(record.latitude || record.longitude);
    }

    get locatedCount() {
        return this.state.records.filter((r) => this.isLocated(r)).length;
    }

    get showMapboxBanner() {
        return !this.state.mapboxToken && !this.state.bannerClosed;
    }

    recordTime(record) {
        const start = deserializeDateTime(record.date_start);
        const end = deserializeDateTime(record.date_end);
        const sameDay = start.hasSame(end, "day");
        return `${start.toFormat("ccc d MMM")}, ${start.toLocaleString(DateTime.TIME_SIMPLE)} - ${
            sameDay ? "" : end.toFormat("d MMM") + ", "
        }${end.toLocaleString(DateTime.TIME_SIMPLE)}`;
    }

    // -------------------------------------------------------------------------
    // Routes (Mapbox)
    // -------------------------------------------------------------------------

    /** Stops of the group's route: its located shifts in time order, the
     * shifts in a row at the same address being one stop. */
    _groupStops(group) {
        const stops = [];
        for (const record of this.groupRecords(group)) {
            if (!this.isLocated(record)) {
                continue;
            }
            const last = stops[stops.length - 1];
            if (last && last.lat === record.latitude && last.lng === record.longitude) {
                last.recordIds.push(record.id);
            } else {
                stops.push({ lat: record.latitude, lng: record.longitude, recordIds: [record.id] });
            }
        }
        return stops;
    }

    groupRoute(group) {
        const route = this.state.routes[this.groupId(group)];
        return route && route.legs.length ? route : null;
    }

    /** Distance (m) and duration (s) of the group's route, on the chosen paths. */
    routeTotals(group) {
        const route = this.groupRoute(group);
        if (!route) {
            return null;
        }
        let distance = 0;
        let duration = 0;
        for (const leg of route.legs) {
            const path = leg.paths[leg.selected];
            distance += path.distance;
            duration += path.duration;
        }
        return { distance, duration, stops: route.legs.length + 1 };
    }

    /** Leg of the group's route arriving at the record (first shift of its stop). */
    recordLeg(group, record) {
        const route = this.groupRoute(group);
        if (!route) {
            return null;
        }
        const index = route.legs.findIndex((leg) => leg.toRecordId === record.id);
        return index >= 0 ? { leg: route.legs[index], index } : null;
    }

    routeError(group) {
        const route = this.state.routes[this.groupId(group)];
        return (route && route.error) || "";
    }

    legPath(leg) {
        return leg.paths[leg.selected];
    }

    isLegSelected(group, index) {
        const selected = this.state.selectedLeg;
        return Boolean(selected && selected.group === this.groupId(group) && selected.index === index);
    }

    formatDistance(meters) {
        const km = meters / 1000;
        // A decimal under 100 km: the paths of a drive often differ by little
        return km < 100 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
    }

    formatDuration(seconds) {
        const minutes = Math.max(Math.round(seconds / 60), 1);
        if (minutes < 60) {
            return `${minutes} min`;
        }
        return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
    }

    async _mapbox(path, params = {}) {
        const query = new URLSearchParams({ ...params, access_token: this.state.mapboxToken });
        const response = await fetch(`${MAPBOX_API}${path}?${query}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.message || `${response.status} ${response.statusText}`);
        }
        return data;
    }

    /** Check the token once: a wrong token gives empty tiles and no routes. */
    async _checkMapboxToken() {
        if (!this.state.mapboxToken) {
            this.state.mapboxStatus = "none";
            return false;
        }
        this.state.mapboxStatus = "checking";
        try {
            const data = await this._mapbox("/tokens/v2");
            if (data.code !== "TokenValid") {
                throw new Error(data.code || _t("invalid token"));
            }
            this.state.mapboxStatus = "valid";
            return true;
        } catch (e) {
            this.state.mapboxStatus = "invalid";
            this.state.mapboxError = e.message || String(e);
            return false;
        }
    }

    async setupTiles() {
        const L = window.L;
        const useMapbox = await this._checkMapboxToken();
        if (!this.map) {
            return;
        }
        if (this.tileLayer) {
            this.tileLayer.remove();
        }
        if (useMapbox) {
            this.tileLayer = L.tileLayer(
                `${MAPBOX_API}/styles/v1/mapbox/streets-v12/tiles/512/{z}/{x}/{y}@2x?access_token=${encodeURIComponent(this.state.mapboxToken)}`,
                {
                    tileSize: 512,
                    zoomOffset: -1,
                    maxZoom: 20,
                    attribution: '&copy; <a href="https://www.mapbox.com/about/maps/" target="_blank">Mapbox</a> '
                        + '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> '
                        + '<a href="https://apps.mapbox.com/feedback/" target="_blank"><strong>Improve this map</strong></a>',
                }
            );
        } else {
            this.tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            });
        }
        this.tileLayer.addTo(this.map);
    }

    /** Driving route of each group through its stops, one Mapbox request per
     * 25 stops; each leg keeps its own geometry to be switched separately. */
    async computeRoutes() {
        const generation = ++this.routeGeneration;
        this.state.routes = {};
        if (this.state.mapboxStatus !== "valid") {
            return;
        }
        const groups = this.state.groups.filter((g) => this._groupStops(g).length > 1);
        if (!groups.length) {
            return;
        }
        this.state.routing = true;
        await Promise.all(groups.map(async (group) => {
            const stops = this._groupStops(group);
            const legs = [];
            let error = "";
            try {
                for (let i = 0; i < stops.length - 1; i += MAPBOX_MAX_COORDS - 1) {
                    const chunk = stops.slice(i, i + MAPBOX_MAX_COORDS);
                    const coords = chunk.map((s) => `${s.lng},${s.lat}`).join(";");
                    const data = await this._mapbox(`/directions/v5/mapbox/driving/${coords}`, {
                        geometries: "geojson",
                        overview: "false",
                        steps: "true",
                    });
                    const route = data.routes && data.routes[0];
                    if (!route) {
                        throw new Error(data.message || data.code || _t("no route found"));
                    }
                    route.legs.forEach((leg, index) => {
                        const coordinates = [];
                        for (const step of leg.steps) {
                            coordinates.push(...step.geometry.coordinates);
                        }
                        const from = chunk[index];
                        const to = chunk[index + 1];
                        legs.push({
                            fromRecordId: from.recordIds[from.recordIds.length - 1],
                            toRecordId: to.recordIds[0],
                            from: [from.lng, from.lat],
                            to: [to.lng, to.lat],
                            paths: [{ coordinates: markRaw(coordinates), distance: leg.distance, duration: leg.duration }],
                            selected: 0,
                            alternativesLoaded: false,
                            loadingAlternatives: false,
                        });
                    });
                }
            } catch (e) {
                error = e.message || String(e);
            }
            if (generation === this.routeGeneration) {
                this.state.routes[this.groupId(group)] = { legs: error ? [] : legs, error };
            }
        }));
        if (generation === this.routeGeneration) {
            this.state.routing = false;
            this.renderRoutes();
        }
    }

    /** The other paths Mapbox proposes for a leg (at most 3 in all). */
    async _loadAlternatives(leg) {
        if (leg.alternativesLoaded || leg.loadingAlternatives) {
            return;
        }
        leg.loadingAlternatives = true;
        try {
            const coords = `${leg.from[0]},${leg.from[1]};${leg.to[0]},${leg.to[1]}`;
            const data = await this._mapbox(`/directions/v5/mapbox/driving/${coords}`, {
                geometries: "geojson",
                overview: "full",
                alternatives: "true",
            });
            const paths = (data.routes || []).map((route) => ({
                coordinates: markRaw(route.geometry.coordinates),
                distance: route.distance,
                duration: route.duration,
            }));
            if (paths.length) {
                // Keep the path shown so far selected: the closest one
                const current = leg.paths[leg.selected];
                let selected = 0;
                let best = Infinity;
                paths.forEach((path, index) => {
                    const gap = Math.abs(path.distance - current.distance) + Math.abs(path.duration - current.duration);
                    if (gap < best) {
                        best = gap;
                        selected = index;
                    }
                });
                leg.paths = paths;
                leg.selected = selected;
            }
            leg.alternativesLoaded = true;
        } catch (e) {
            this.notification.add(_t("Mapbox could not propose other paths: %s", e.message || String(e)), { type: "warning" });
        } finally {
            leg.loadingAlternatives = false;
        }
    }

    fastestPathIndex(leg) {
        let fastest = 0;
        leg.paths.forEach((path, index) => {
            if (path.duration < leg.paths[fastest].duration) {
                fastest = index;
            }
        });
        return fastest;
    }

    // -------------------------------------------------------------------------
    // Map
    // -------------------------------------------------------------------------

    renderMap() {
        if (!this.map) {
            return;
        }
        this.renderMarkers();
        this.renderRoutes();
        this.computeRoutes();
    }

    renderMarkers() {
        const L = window.L;
        for (const layer of this.markerLayers) {
            layer.remove();
        }
        this.markerLayers = [];
        this.markers = {};
        // One pin per address and group, with the number of shifts there
        const places = new Map();
        for (const record of this.state.records) {
            if (!this.isLocated(record)) {
                continue;
            }
            const key = `${record.latitude.toFixed(5)},${record.longitude.toFixed(5)},${record.group_key}`;
            if (!places.has(key)) {
                places.set(key, []);
            }
            places.get(key).push(record);
        }
        for (const records of places.values()) {
            const first = records[0];
            const group = this.state.groups.find((g) => g.key === first.group_key);
            const marker = L.marker([first.latitude, first.longitude], {
                icon: L.divIcon({
                    className: "o_fs_map_marker",
                    html: this._pinHtml(records.length > 1 ? String(records.length) : "", this.groupColor(group)),
                    iconSize: [30, 40],
                    iconAnchor: [15, 40],
                    popupAnchor: [0, -40],
                }),
                riseOnHover: true,
            });
            if (records.length > 1) {
                marker.bindPopup(this._popupHtml(records), { maxWidth: 300 });
            } else {
                marker.on("click", () => this.openSlotPopover(first.id, marker.getElement()));
            }
            const ids = records.map((r) => r.id);
            marker.on("mouseover", () => {
                this.state.hoverRecords = ids;
                this.applyHighlight();
            });
            marker.on("mouseout", () => {
                this.state.hoverRecords = [];
                this.applyHighlight();
            });
            marker.addTo(this.map);
            this.markerLayers.push(marker);
            for (const record of records) {
                this.markers[record.id] = marker;
            }
        }
        if (this.markerLayers.length) {
            this.map.fitBounds(L.featureGroup(this.markerLayers).getBounds().pad(0.2), { maxZoom: 13 });
        }
    }

    renderRoutes() {
        if (!this.map) {
            return;
        }
        const L = window.L;
        for (const layers of Object.values(this.routeLayers)) {
            layers.forEach((layer) => layer.remove());
        }
        for (const layer of this.alternativeLayers) {
            layer.remove();
        }
        this.routeLayers = {};
        this.alternativeLayers = [];
        for (const group of this.state.groups) {
            const route = this.groupRoute(group);
            if (!route) {
                continue;
            }
            const gid = this.groupId(group);
            const color = this.groupColor(group);
            this.routeLayers[gid] = route.legs.map((leg, index) => {
                const path = leg.paths[leg.selected];
                const line = L.polyline(path.coordinates.map(([lng, lat]) => [lat, lng]), {
                    color,
                    weight: 5,
                    opacity: 0.8,
                    lineJoin: "round",
                }).addTo(this.map);
                line.bindTooltip(
                    `${this._esc(group.name)}: ${this.formatDistance(path.distance)} · ${this.formatDuration(path.duration)}`,
                    { sticky: true }
                );
                line.on("click", () => this.selectLeg(group, index));
                line.on("mouseover", () => {
                    this.state.hoverGroup = gid;
                    this.applyHighlight();
                });
                line.on("mouseout", () => {
                    this.state.hoverGroup = null;
                    this.applyHighlight();
                });
                return line;
            });
            // The other paths of the selected leg, to switch to
            if (this.state.selectedLeg && this.state.selectedLeg.group === gid) {
                const leg = route.legs[this.state.selectedLeg.index];
                leg?.paths.forEach((path, index) => {
                    if (index === leg.selected) {
                        return;
                    }
                    const alt = L.polyline(path.coordinates.map(([lng, lat]) => [lat, lng]), {
                        color: "#6c757d",
                        weight: 5,
                        opacity: 0.6,
                        dashArray: "8, 8",
                    }).addTo(this.map);
                    alt.bindTooltip(
                        `${_t("Other path")}: ${this.formatDistance(path.distance)} · ${this.formatDuration(path.duration)} (${_t("click to use it")})`,
                        { sticky: true }
                    );
                    alt.on("click", () => this.choosePath(group, this.state.selectedLeg.index, index));
                    alt.bringToBack();
                    this.alternativeLayers.push(alt);
                });
            }
        }
        this.applyHighlight();
    }

    /** Highlight the pins and route of the hovered group / shifts, dim the others. */
    applyHighlight() {
        if (!this.map) {
            return;
        }
        const hoverGroup = this.state.hoverGroup;
        const selectedGroup = this.state.selectedLeg && this.state.selectedLeg.group;
        const focusGroup = hoverGroup ?? selectedGroup;
        const hoverRecords = new Set(this.state.hoverRecords);
        const active = new Set();
        // A hovered shift is highlighted alone, else the hovered group's
        for (const record of this.state.records) {
            if (hoverRecords.size ? hoverRecords.has(record.id) : hoverGroup !== null && String(record.group_key) === hoverGroup) {
                const marker = this.markers[record.id];
                if (marker) {
                    active.add(marker);
                }
            }
        }
        const anyActive = active.size > 0;
        for (const marker of this.markerLayers) {
            const el = marker.getElement();
            if (!el) {
                continue;
            }
            const isActive = active.has(marker);
            el.classList.toggle("o_fs_map_marker_active", isActive);
            el.classList.toggle("o_fs_map_marker_dim", anyActive && !isActive);
            marker.setZIndexOffset(isActive ? 1000 : 0);
        }
        for (const [gid, layers] of Object.entries(this.routeLayers)) {
            const focused = focusGroup === gid;
            layers.forEach((line, index) => {
                const selectedLeg = selectedGroup === gid && this.state.selectedLeg.index === index;
                line.setStyle({
                    weight: selectedLeg ? 8 : focused ? 6 : 5,
                    opacity: focusGroup === null || focusGroup === undefined || focused ? 0.85 : 0.25,
                });
                if (focused) {
                    line.bringToFront();
                }
            });
        }
    }

    _pinHtml(label, color) {
        return `<div class="o_fs_map_pin" style="background:${color}"><span>${this._esc(label)}</span></div>`;
    }

    _popupHtml(records) {
        const first = records[0];
        const items = records.map((r) => `
            <div class="o_fs_map_popup_record">
                <a href="#" data-slot-id="${r.id}"><strong>${this._esc(r.name)}</strong></a>
                <div class="text-muted">${this._esc(this.recordTime(r))}</div>
            </div>`).join("");
        const url = this._directionsUrl([first]);
        return `
            <div class="o_fs_map_popup">
                <div class="fw-bold">${this._esc(first.partner_name)}</div>
                <div class="text-muted mb-2">${this._esc(first.address)}</div>
                ${items}
                <a class="btn btn-sm btn-secondary mt-2" target="_blank" rel="noopener" href="${url}">${this._esc(_t("Navigate to"))}</a>
            </div>`;
    }

    _esc(value) {
        const div = document.createElement("div");
        div.textContent = value == null ? "" : String(value);
        return div.innerHTML;
    }

    _directionsUrl(records) {
        const stops = records.map((r) => `${r.latitude},${r.longitude}`);
        const destination = stops[stops.length - 1];
        const waypoints = stops.slice(0, -1).slice(0, MAX_WAYPOINTS);
        let url = `https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=${encodeURIComponent(destination)}`;
        if (waypoints.length) {
            url += `&waypoints=${encodeURIComponent(waypoints.join("|"))}`;
        }
        return url;
    }

    // -------------------------------------------------------------------------
    // Shift popover (same as the schedule)
    // -------------------------------------------------------------------------

    async openSlotPopover(slotId, target) {
        if (!target || !target.isConnected) {
            this.openRecord(slotId);
            return;
        }
        const data = await this.orm.call("fs.planning.slot", "get_popover_data", [[slotId]]);
        if (!target.isConnected) {
            return;
        }
        this.popover.open(target, {
            data,
            onEdit: () => {
                this.popover.close();
                this.dialog.add(FormViewDialog, {
                    resModel: this.props.resModel,
                    resId: slotId,
                    title: _t("Edit Shift"),
                    context: this.props.context,
                    onRecordSaved: () => this.load(),
                }, {
                    onClose: () => this.load(),
                });
            },
            onAction: (action) => this._runSlotAction(slotId, action),
            onDelete: () => this._deleteSlot(slotId),
        });
    }

    async _runSlotAction(slotId, action) {
        this.popover.close();
        const args = [[slotId]];
        if (action.geolocate) {
            const { latitude, longitude } = await this._fetchLocation();
            args.push(latitude, longitude);
        }
        const result = await this.orm.call("fs.planning.slot", action.method, args);
        if (result && typeof result === "object" && result.type) {
            await this.actionService.doAction(result, { onClose: () => this.load() });
            return;
        }
        await this.load();
    }

    _fetchLocation() {
        return new Promise((resolve) => {
            if (!navigator.geolocation) {
                resolve({ latitude: 0, longitude: 0 });
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
                () => resolve({ latitude: 0, longitude: 0 }),
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
            );
        });
    }

    _deleteSlot(slotId) {
        this.popover.close();
        this.dialog.add(ConfirmationDialog, {
            body: _t("Are you sure you want to delete this shift?"),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("fs.planning.slot", [slotId]);
                await this.load();
            },
            cancel: () => {},
        });
    }

    // -------------------------------------------------------------------------
    // Handlers
    // -------------------------------------------------------------------------

    toggleGroup(group) {
        const id = this.groupId(group);
        this.state.expanded[id] = !this.state.expanded[id];
    }

    onGroupHover(group) {
        this.state.hoverGroup = group ? this.groupId(group) : null;
        this.applyHighlight();
    }

    onRecordHover(record) {
        this.state.hoverRecords = record ? [record.id] : [];
        this.applyHighlight();
    }

    isRecordHighlighted(record) {
        return this.state.hoverRecords.includes(record.id);
    }

    /** Google Maps route through the group's addresses, in time order. */
    navigateGroup(group) {
        const located = this.groupRecords(group).filter((r) => this.isLocated(r));
        if (located.length) {
            window.open(this._directionsUrl(located), "_blank", "noopener");
        }
    }

    navigateAll() {
        const located = this.state.records.filter((r) => this.isLocated(r));
        if (located.length) {
            window.open(this._directionsUrl(located), "_blank", "noopener");
        }
    }

    /** Show the group's whole route. */
    focusGroupRoute(group) {
        const layers = this.routeLayers[this.groupId(group)];
        if (layers && layers.length && this.map) {
            this.map.fitBounds(window.L.featureGroup(layers).getBounds().pad(0.15));
        }
    }

    /** Select a leg of a route: its other paths are proposed. */
    async selectLeg(group, index) {
        const gid = this.groupId(group);
        if (this.isLegSelected(group, index)) {
            this.state.selectedLeg = null;
            this.renderRoutes();
            return;
        }
        this.state.selectedLeg = { group: gid, index };
        this.state.expanded[gid] = true;
        const leg = this.state.routes[gid]?.legs[index];
        if (!leg) {
            return;
        }
        this.renderRoutes();
        const line = this.routeLayers[gid]?.[index];
        if (line && this.map) {
            this.map.fitBounds(line.getBounds().pad(0.3), { maxZoom: 15 });
        }
        await this._loadAlternatives(leg);
        if (this.state.selectedLeg && this.state.selectedLeg.group === gid && this.state.selectedLeg.index === index) {
            this.renderRoutes();
        }
    }

    choosePath(group, legIndex, pathIndex) {
        const leg = this.state.routes[this.groupId(group)]?.legs[legIndex];
        if (leg) {
            leg.selected = pathIndex;
            this.renderRoutes();
        }
    }

    onRecordClick(record, ev) {
        const marker = this.markers[record.id];
        if (marker && this.map) {
            const target = ev.currentTarget;
            if (!this.map.getBounds().contains(marker.getLatLng())) {
                this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 12), { animate: false });
            }
            const el = marker.getElement();
            this.openSlotPopover(record.id, el && el.isConnected ? el : target);
        } else {
            this.openSlotPopover(record.id, ev.currentTarget);
        }
    }

    openRecord(resId) {
        this.props.selectRecord(resId);
    }

    onClickNew() {
        this.props.createRecord();
    }

    closeMapboxBanner() {
        this.state.bannerClosed = true;
        sessionSet(BANNER_KEY, "1");
    }

    openMapboxSettings() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("Settings"),
            res_model: "res.config.settings",
            views: [[false, "form"]],
            target: "inline",
            context: { module: "hudson_planning", bin_size: false },
        });
    }
}

class FsMapArchParser {
    parse(arch) {
        const limit = parseInt(arch.getAttribute("limit") || "80");
        return {
            defaultGroupBy: arch.getAttribute("default_group_by") || "resource_id",
            limit: limit > 0 ? limit : 80,
            canCreate: arch.getAttribute("create") !== "0" && arch.getAttribute("create") !== "false",
        };
    }
}

export const fsMapView = {
    type: "fs_map",
    Controller: FsMapController,
    ArchParser: FsMapArchParser,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
    props: (genericProps, view) => ({
        ...genericProps,
        archInfo: new view.ArchParser().parse(genericProps.arch),
    }),
};

registry.category("views").add("fs_map", fsMapView);
