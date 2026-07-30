/** @odoo-module **/
// Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS, loadCSS } from "@web/core/assets";


/**
 * FsLiveMap — Live Technician Map
 *
 * An OWL client action that renders a Leaflet.js map showing all field
 * service technicians who currently have a timer running.  The map
 * auto-refreshes every 60 seconds.  Clicking a pin or a sidebar card opens
 * the corresponding field service order in the form view.
 */
export class FsLiveMap extends Component {
    static template = "hudson_field_service.FsLiveMap";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.mapRef = useRef("mapContainer");

        this.state = useState({
            technicians: [],
            loading: true,
            error: null,
            lastUpdated: null,
            selectedId: null,
        });

        /** @type {L.Map|null} */
        this.map = null;
        /** @type {Record<number, L.Marker>} */
        this.markers = {};
        /** @type {number|null} */
        this.refreshTimer = null;

        onMounted(async () => {
            try {
                await this._initLeaflet();
                this._createMap();
                await this._loadTechnicians();
                // Auto-refresh every 60 s
                this.refreshTimer = setInterval(() => this._loadTechnicians(), 60000);
            } catch (e) {
                this.state.error = e.message || String(e);
                this.state.loading = false;
            }
        });

        onWillUnmount(() => {
            if (this.refreshTimer) {
                clearInterval(this.refreshTimer);
                this.refreshTimer = null;
            }
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
    }

    // ── Private helpers ───────────────────────────────────────────────

    async _initLeaflet() {
        await loadCSS("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css");
        await loadJS("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js");
    }

    _createMap() {
        const el = this.mapRef.el;
        if (!el) return;

        this.map = window.L.map(el, { zoomControl: true }).setView([20, 0], 2);

        // OpenStreetMap tile layer
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).addTo(this.map);
    }

    async _loadTechnicians() {
        if (!this.map) return;
        try {
            const data = await this.orm.call(
                "field.service.order",
                "search_read",
                [
                    [
                        ["timer_start", "!=", false],
                        ["current_latitude", "!=", 0],
                        ["current_longitude", "!=", 0],
                    ],
                ],
                {
                    fields: [
                        "id", "name", "title",
                        "user_id", "partner_id",
                        "current_latitude", "current_longitude",
                        "last_location_update", "state",
                    ],
                }
            );

            this.state.technicians = data;
            this.state.loading = false;
            this.state.lastUpdated = new Date();
            this._syncMarkers(data);
        } catch (e) {
            console.error("[FsLiveMap] Failed to load technicians:", e);
            this.state.error = e.message || "Failed to load technician locations";
            this.state.loading = false;
        }
    }

    _syncMarkers(technicians) {
        if (!this.map) return;

        const currentIds = new Set(technicians.map((t) => t.id));

        // Remove stale markers
        for (const idStr of Object.keys(this.markers)) {
            const id = parseInt(idStr);
            if (!currentIds.has(id)) {
                this.markers[id].remove();
                delete this.markers[id];
            }
        }

        // Add / update markers
        for (const tech of technicians) {
            const lat = tech.current_latitude;
            const lng = tech.current_longitude;
            if (!lat || !lng) continue;

            const pos = [lat, lng];
            const popup = this._buildPopup(tech);

            // Custom pin icon
            const icon = window.L.divIcon({
                className: "",
                html: this._buildPinHtml(tech),
                iconSize: [40, 50],
                iconAnchor: [20, 50],
                popupAnchor: [0, -54],
            });

            if (this.markers[tech.id]) {
                this.markers[tech.id]
                    .setLatLng(pos)
                    .setIcon(icon)
                    .getPopup()
                    .setContent(popup);
            } else {
                const marker = window.L.marker(pos, { icon })
                    .addTo(this.map)
                    .bindPopup(popup, { maxWidth: 260 });
                this.markers[tech.id] = marker;
            }
        }

        // Auto-fit bounds
        const markerArr = Object.values(this.markers);
        if (markerArr.length > 0) {
            const group = window.L.featureGroup(markerArr);
            this.map.fitBounds(group.getBounds().pad(0.3), { maxZoom: 14 });
        }
    }

    _buildPinHtml(tech) {
        const initials = this._getInitials(tech.user_id?.[1] || "?");
        return `
            <div style="
                width:40px; height:40px; border-radius:50% 50% 50% 0;
                transform: rotate(-45deg);
                background: linear-gradient(135deg, #017e84, #014d52);
                box-shadow: 0 3px 10px rgba(0,0,0,0.3);
                display:flex; align-items:center; justify-content:center;
                border: 2px solid white;
            ">
                <span style="
                    transform: rotate(45deg);
                    color: #fff; font-weight:700; font-size:13px;
                    font-family: sans-serif; line-height:1;
                ">${initials}</span>
            </div>
        `;
    }

    _buildPopup(tech) {
        const userName = tech.user_id?.[1] || "Unknown";
        const customerName = tech.partner_id?.[1] || "No customer";
        const orderRef = tech.name || "";
        const title = tech.title || "";
        const updated = tech.last_location_update
            ? `Updated: ${new Date(tech.last_location_update).toLocaleTimeString()}`
            : "";

        return `
            <div class="fs-map-popup">
                <strong>${this._escHtml(userName)}</strong>
                <div class="fs-popup-order">${this._escHtml(orderRef)} — ${this._escHtml(title)}</div>
                <div class="fs-popup-customer">👤 ${this._escHtml(customerName)}</div>
                <div class="fs-popup-updated">${this._escHtml(updated)}</div>
                <a href="/web#model=field.service.order&id=${tech.id}&view_type=form" target="_blank">
                    Open Order →
                </a>
            </div>
        `;
    }

    _getInitials(name) {
        return name
            .split(" ")
            .slice(0, 2)
            .map((w) => w[0]?.toUpperCase() || "")
            .join("");
    }

    _escHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    // ── Event handlers ────────────────────────────────────────────────

    async onRefresh() {
        this.state.loading = true;
        await this._loadTechnicians();
        this.notification.add("Map refreshed", { type: "info", sticky: false });
    }

    onTechClick(techId) {
        this.state.selectedId = techId;
        const marker = this.markers[techId];
        if (marker) {
            this.map.panTo(marker.getLatLng(), { animate: true });
            marker.openPopup();
        }
    }

    onOpenOrder(techId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "field.service.order",
            res_id: techId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get formattedLastUpdate() {
        if (!this.state.lastUpdated) return "";
        return this.state.lastUpdated.toLocaleTimeString();
    }

    getAvatarInitials(tech) {
        return this._getInitials(tech.user_id?.[1] || "?");
    }
}

registry.category("actions").add("fs_live_map", FsLiveMap);
