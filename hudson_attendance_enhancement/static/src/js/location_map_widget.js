/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, useState, useRef, onMounted, onWillUnmount, useEffect } from "@odoo/owl";

export class LocationMapPickerWidget extends Component {
    static template = "hudson_attendance_enhancement.LocationMapPickerWidget";
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.notification = useService("notification");
        this.mapContainerRef = useRef("mapContainer");

        this.state = useState({
            searchQuery: "",
            searchResults: [],
            isSearching: false,
            isLocating: false,
        });

        this.map = null;
        this.marker = null;
        this.radiusCircle = null;

        onMounted(() => {
            this.initMap();
        });

        onWillUnmount(() => {
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });

        useEffect(
            (lat, lon, rad) => {
                this.syncMapWithRecord(lat, lon, rad);
            },
            () => [
                this.props.record.data.latitude,
                this.props.record.data.longitude,
                this.props.record.data.radius,
            ]
        );
    }

    get currentLat() {
        return this.props.record.data.latitude || 0.0;
    }

    get currentLon() {
        return this.props.record.data.longitude || 0.0;
    }

    get currentRadius() {
        return this.props.record.data.radius || 50.0;
    }

    getCustomIcon() {
        const markerHtml = `
            <div class="hudson-map-marker-pin">
                <svg viewBox="0 0 24 36" width="32" height="42" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 0C5.37 0 0 5.37 0 12C0 21 12 36 12 36C12 36 24 21 24 12C24 5.37 18.63 0 12 0Z" fill="#e02424"/>
                    <circle cx="12" cy="12" r="5" fill="#ffffff"/>
                </svg>
            </div>
        `;
        return window.L.divIcon({
            html: markerHtml,
            className: '',
            iconSize: [32, 42],
            iconAnchor: [16, 42],
            popupAnchor: [0, -38],
        });
    }

    initMap(retries = 5) {
        if (!this.mapContainerRef.el) {
            return;
        }
        if (!window.L) {
            if (retries > 0) {
                setTimeout(() => this.initMap(retries - 1), 200);
            }
            return;
        }

        let lat = this.currentLat;
        let lon = this.currentLon;
        let hasCoords = lat !== 0.0 || lon !== 0.0;

        const defaultLat = hasCoords ? lat : 25.2048; // Default to Dubai if unset
        const defaultLon = hasCoords ? lon : 55.2708;
        const defaultZoom = hasCoords ? 16 : 4;

        this.map = window.L.map(this.mapContainerRef.el).setView([defaultLat, defaultLon], defaultZoom);

        window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(this.map);

        const icon = this.getCustomIcon();

        this.marker = window.L.marker([defaultLat, defaultLon], {
            icon: icon,
            draggable: !this.props.readonly,
        }).addTo(this.map);

        this.radiusCircle = window.L.circle([defaultLat, defaultLon], {
            radius: this.currentRadius,
            color: '#0d6efd',
            fillColor: '#0d6efd',
            fillOpacity: 0.18,
            weight: 2,
        }).addTo(this.map);

        if (!this.props.readonly) {
            this.map.on('click', (e) => {
                this.updateCoordinates(e.latlng.lat, e.latlng.lng);
            });

            this.marker.on('dragend', (e) => {
                const latlng = e.target.getLatLng();
                this.updateCoordinates(latlng.lat, latlng.lng);
            });
        }

        setTimeout(() => {
            if (this.map) {
                this.map.invalidateSize();
            }
        }, 250);

        // If coordinates were empty initially, try auto-locating
        if (!hasCoords && navigator.geolocation) {
            this.onUseCurrentLocation();
        }
    }

    syncMapWithRecord(lat, lon, rad) {
        if (!this.map || !this.marker || !this.radiusCircle) {
            return;
        }
        if (!lat && !lon) {
            return;
        }
        const currentPos = this.marker.getLatLng();
        const latNum = Number(lat);
        const lonNum = Number(lon);
        const radNum = Number(rad || 50);

        if (Math.abs(currentPos.lat - latNum) > 0.000001 || Math.abs(currentPos.lng - lonNum) > 0.000001) {
            this.marker.setLatLng([latNum, lonNum]);
            this.radiusCircle.setLatLng([latNum, lonNum]);
            this.map.panTo([latNum, lonNum]);
        }
        if (this.radiusCircle.getRadius() !== radNum) {
            this.radiusCircle.setRadius(radNum);
        }
    }

    async updateCoordinates(lat, lon) {
        const roundedLat = parseFloat(Number(lat).toFixed(7));
        const roundedLon = parseFloat(Number(lon).toFixed(7));

        if (this.marker) {
            this.marker.setLatLng([roundedLat, roundedLon]);
        }
        if (this.radiusCircle) {
            this.radiusCircle.setLatLng([roundedLat, roundedLon]);
        }

        await this.props.record.update({
            latitude: roundedLat,
            longitude: roundedLon,
        });
    }

    async onSearchClick() {
        const query = (this.state.searchQuery || "").trim();
        if (!query) {
            return;
        }
        this.state.isSearching = true;
        this.state.searchResults = [];

        try {
            const results = await rpc('/hudson_attendance/search_location', { query });
            if (results && results.length > 0) {
                this.state.searchResults = results;
            } else {
                this.notification.add("No matching places found for: " + query, { type: "warning" });
            }
        } catch (error) {
            this.notification.add("Search request failed. Please check internet connection.", { type: "danger" });
        } finally {
            this.state.isSearching = false;
        }
    }

    onSearchKeyDown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onSearchClick();
        }
    }

    async selectSearchResult(result) {
        this.state.searchResults = [];
        this.state.searchQuery = result.display_name;

        await this.updateCoordinates(result.lat, result.lon);

        if (this.map) {
            this.map.setView([result.lat, result.lon], 16);
        }

        if (!this.props.record.data.name) {
            const shortName = result.display_name.split(',')[0].trim();
            await this.props.record.update({ name: shortName });
        }
    }

    onUseCurrentLocation() {
        if (!navigator.geolocation) {
            this.notification.add("Geolocation is not supported by your browser.", { type: "danger" });
            return;
        }

        this.state.isLocating = true;
        navigator.geolocation.getCurrentPosition(
            async (pos) => {
                const lat = pos.coords.latitude;
                const lon = pos.coords.longitude;
                await this.updateCoordinates(lat, lon);
                if (this.map) {
                    this.map.setView([lat, lon], 17);
                }
                this.state.isLocating = false;
                this.notification.add("Location detected from GPS.", { type: "info" });
            },
            (err) => {
                this.state.isLocating = false;
                // Only alert if clicked manually
                if (this.currentLat !== 0.0 || this.currentLon !== 0.0) {
                    this.notification.add("Could not retrieve GPS location: " + err.message, { type: "warning" });
                }
            },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    }
}

export const locationMapPicker = {
    component: LocationMapPickerWidget,
    fieldDependencies: [
        { name: "latitude", type: "float", readonly: false },
        { name: "longitude", type: "float", readonly: false },
        { name: "radius", type: "float", readonly: false },
        { name: "name", type: "char", readonly: false },
    ],
};

registry.category("view_widgets").add("location_map_picker", locationMapPicker);
