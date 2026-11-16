/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, proxy, signal, useProps, onMounted, onWillUnmount } from "@odoo/owl";
import { useLayoutEffect } from "@web/owl2/utils";

export class EmployeeHomeMapPickerWidget extends Component {
    static template = "hudson_attendance_enhancement.EmployeeHomeMapPickerWidget";
    props = useProps({ ...standardWidgetProps });

    setup() {
        this.notification = useService("notification");
        this.mapContainerRef = signal.ref();

        this.state = proxy({
            searchQuery: "",
            searchResults: [],
            isSearching: false,
            isLocating: false,
            isFetchingAddress: false,
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

        useLayoutEffect(
            (lat, lon, rad) => {
                this.syncMapWithRecord(lat, lon, rad);
            },
            () => [
                this.props.record.data.home_latitude,
                this.props.record.data.home_longitude,
                this.props.record.data.home_radius,
            ]
        );
    }

    get currentLat() {
        return this.props.record.data.home_latitude || 0.0;
    }

    get currentLon() {
        return this.props.record.data.home_longitude || 0.0;
    }

    get currentRadius() {
        return this.props.record.data.home_radius || 150.0;
    }

    get homeAddressName() {
        return this.props.record.data.home_address_name || "";
    }

    getCustomIcon() {
        const markerHtml = `
            <div class="hudson-home-marker-pin">
                <svg viewBox="0 0 24 36" width="34" height="44" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 0C5.37 0 0 5.37 0 12C0 21 12 36 12 36C12 36 24 21 24 12C24 5.37 18.63 0 12 0Z" fill="#198754"/>
                    <circle cx="12" cy="12" r="5" fill="#ffffff"/>
                </svg>
            </div>
        `;
        return window.L.divIcon({
            html: markerHtml,
            className: '',
            iconSize: [34, 44],
            iconAnchor: [17, 44],
            popupAnchor: [0, -40],
        });
    }

    initMap(retries = 5) {
        if (!this.mapContainerRef()) {
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
        const defaultZoom = hasCoords ? 16 : 5;

        this.map = window.L.map(this.mapContainerRef()).setView([defaultLat, defaultLon], defaultZoom);

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
            color: '#198754',
            fillColor: '#198754',
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
        const radNum = Number(rad || 150);

        if (Math.abs(currentPos.lat - latNum) > 0.000001 || Math.abs(currentPos.lng - lonNum) > 0.000001) {
            this.marker.setLatLng([latNum, lonNum]);
            this.radiusCircle.setLatLng([latNum, lonNum]);
            this.map.panTo([latNum, lonNum]);
        }
        if (this.radiusCircle.getRadius() !== radNum) {
            this.radiusCircle.setRadius(radNum);
        }
    }

    async updateCoordinates(lat, lon, addressName = null) {
        const roundedLat = parseFloat(Number(lat).toFixed(7));
        const roundedLon = parseFloat(Number(lon).toFixed(7));

        if (this.marker) {
            this.marker.setLatLng([roundedLat, roundedLon]);
        }
        if (this.radiusCircle) {
            this.radiusCircle.setLatLng([roundedLat, roundedLon]);
        }

        const vals = {
            home_latitude: roundedLat,
            home_longitude: roundedLon,
        };
        if (addressName) {
            vals.home_address_name = addressName;
        }

        await this.props.record.update(vals);
    }

    async onFetchPrivateAddress() {
        const data = this.props.record.data;
        const street = data.private_street || "";
        const street2 = data.private_street2 || "";
        const city = data.private_city || "";
        const stateName = data.private_state_id ? data.private_state_id[1] : "";
        const zip = data.private_zip || "";
        const countryName = data.private_country_id ? data.private_country_id[1] : "";

        const parts = [street, street2, city, stateName, zip, countryName].map(p => (p || "").trim()).filter(Boolean);

        if (parts.length === 0) {
            this.notification.add(_t("No private address found in the 'Personal Information' tab. Please fill in the employee's private address first."), { type: "warning" });
            return;
        }

        const fullQuery = parts.join(", ");
        this.state.isFetchingAddress = true;
        this.state.searchQuery = fullQuery;

        try {
            const results = await rpc('/hudson_attendance/search_location', { query: fullQuery });
            if (results && results.length > 0) {
                const res = results[0];
                await this.updateCoordinates(res.lat, res.lon, fullQuery);
                if (this.map) {
                    this.map.setView([res.lat, res.lon], 16);
                }
                this.notification.add(_t("Home location pinpointed from Private Address: ") + fullQuery, { type: "success" });
            } else {
                // Try fallback to city + country
                const fallbackParts = [city, countryName].filter(Boolean);
                if (fallbackParts.length > 0) {
                    const fbQuery = fallbackParts.join(", ");
                    const fbResults = await rpc('/hudson_attendance/search_location', { query: fbQuery });
                    if (fbResults && fbResults.length > 0) {
                        const fb = fbResults[0];
                        await this.updateCoordinates(fb.lat, fb.lon, fullQuery);
                        if (this.map) {
                            this.map.setView([fb.lat, fb.lon], 15);
                        }
                        this.notification.add(_t("Located vicinity from Private Address. You can click or drag marker to pinpoint exact residence."), { type: "info" });
                        return;
                    }
                }
                this.notification.add(_t("Could not automatically locate '") + fullQuery + _t("'. Please search or click on the map directly."), { type: "warning" });
            }
        } catch (error) {
            this.notification.add(_t("Address search error: ") + (error.message || _t("Server error")), { type: "danger" });
        } finally {
            this.state.isFetchingAddress = false;
        }
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
                this.notification.add(_t("No places found for: ") + query, { type: "warning" });
            }
        } catch (error) {
            this.notification.add(_t("Search request failed. Please check internet connection."), { type: "danger" });
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

        await this.updateCoordinates(result.lat, result.lon, result.display_name);

        if (this.map) {
            this.map.setView([result.lat, result.lon], 16);
        }
    }

    onUseCurrentLocation() {
        if (!navigator.geolocation) {
            this.notification.add(_t("Geolocation is not supported by your browser."), { type: "danger" });
            return;
        }

        this.state.isLocating = true;
        navigator.geolocation.getCurrentPosition(
            async (pos) => {
                const lat = pos.coords.latitude;
                const lon = pos.coords.longitude;
                await this.updateCoordinates(lat, lon, _t("Detected from Current GPS"));
                if (this.map) {
                    this.map.setView([lat, lon], 17);
                }
                this.state.isLocating = false;
                this.notification.add(_t("Home location updated to your current GPS position."), { type: "info" });
            },
            (err) => {
                this.state.isLocating = false;
                this.notification.add(_t("Could not retrieve GPS location: ") + err.message, { type: "warning" });
            },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    }
}

export const employeeHomeMapPicker = {
    component: EmployeeHomeMapPickerWidget,
    fieldDependencies: [
        { name: "home_latitude", type: "float", readonly: false },
        { name: "home_longitude", type: "float", readonly: false },
        { name: "home_address_name", type: "char", readonly: false },
        { name: "home_radius", type: "float", readonly: false },
        { name: "private_street", type: "char" },
        { name: "private_street2", type: "char" },
        { name: "private_city", type: "char" },
        { name: "private_state_id", type: "many2one" },
        { name: "private_zip", type: "char" },
        { name: "private_country_id", type: "many2one" },
    ],
};

registry.category("view_widgets").add("employee_home_map_picker", employeeHomeMapPicker);
