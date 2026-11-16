/** @odoo-module **/

import { Component, proxy, signal, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

export class WfhLiveMapView extends Component {
    static template = "hudson_attendance_enhancement.WfhLiveMapView";

    setup() {
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.mapContainerRef = signal.ref();

        this.state = proxy({
            employees: [],
            logs: [],
            stats: {
                total: 0,
                active_now: 0,
                at_home: 0,
                near_home: 0,
                offsite: 0,
                at_home_pct: 0,
                offsite_pct: 0,
                avg_distance_home_m: 0,
                max_distance_home_m: 0,
                departments: [],
            },
            selectedEmployee: null,
            searchQuery: "",
            filterStatus: "all", // 'all' | 'at_home' | 'offsite'
            viewMode: "map", // 'map' | 'table' | 'graph'
            datePeriod: "live", // 'live' | 'today' | 'week' | 'month' | 'custom'
            customDateFrom: "",
            customDateTo: "",
            isLoading: false,
            lastRefreshed: "",
        });

        this.map = null;
        this.markers = {};
        this.homeCircles = {};
        this.refreshIntervalId = null;

        onMounted(async () => {
            if (this.state.viewMode === "map") {
                await this.initMap();
            }
            await this.loadEmployees();
            this.refreshIntervalId = setInterval(() => {
                if (this.state.datePeriod === "live") {
                    this.loadEmployees(true);
                }
            }, 30000);
        });

        onWillUnmount(() => {
            if (this.refreshIntervalId) {
                clearInterval(this.refreshIntervalId);
            }
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
    }

    async initMap(retries = 5) {
        if (!this.mapContainerRef()) {
            return;
        }
        if (!window.L) {
            if (retries > 0) {
                setTimeout(() => this.initMap(retries - 1), 200);
            }
            return;
        }

        if (this.map) {
            this.map.remove();
            this.map = null;
        }

        this.map = window.L.map(this.mapContainerRef(), {
            zoomControl: true,
        }).setView([25.2048, 55.2708], 5);

        window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(this.map);

        setTimeout(() => {
            if (this.map) {
                this.map.invalidateSize();
            }
        }, 200);
    }

    async setViewMode(mode) {
        this.state.viewMode = mode;
        if (mode === "map") {
            setTimeout(async () => {
                await this.initMap();
                this.updateMapMarkers();
            }, 100);
        }
    }

    async setDatePeriod(period) {
        this.state.datePeriod = period;
        await this.loadEmployees(false);
    }

    async onCustomDateChange() {
        if (this.state.customDateFrom && this.state.customDateTo) {
            await this.loadEmployees(false);
        }
    }

    async loadEmployees(isBackground = false) {
        if (!isBackground) {
            this.state.isLoading = true;
        }

        try {
            const params = {
                period: this.state.datePeriod,
                date_from: this.state.customDateFrom || false,
                date_to: this.state.customDateTo || false,
            };
            const result = await rpc("/hudson_attendance/get_live_wfh_employees", params);
            if (result) {
                this.state.employees = result.employees || [];
                this.state.logs = result.logs || [];
                this.state.stats = result.stats || this.state.stats;
            }
            this.state.lastRefreshed = new Date().toLocaleTimeString();

            if (this.state.viewMode === "map") {
                this.updateMapMarkers();
            }
        } catch (err) {
            console.error("Failed to load WFH employees data:", err);
            if (!isBackground) {
                this.notification.add(_t("Could not load remote employees data: ") + (err.message || _t("Server error")), { type: "danger" });
            }
        } finally {
            this.state.isLoading = false;
        }
    }

    get filteredEmployees() {
        const query = (this.state.searchQuery || "").toLowerCase();
        return this.state.employees.filter((emp) => {
            const matchesQuery = !query || 
                emp.name.toLowerCase().includes(query) || 
                (emp.department_name && emp.department_name.toLowerCase().includes(query));
            
            let matchesFilter = true;
            if (this.state.filterStatus === "at_home") {
                matchesFilter = emp.status === "at_home";
            } else if (this.state.filterStatus === "offsite") {
                matchesFilter = emp.status === "offsite" || emp.status === "near_home";
            }
            return matchesQuery && matchesFilter;
        });
    }

    getMarkerHtml(emp) {
        let badgeColor = "#198754";
        let pulseClass = "hudson-pulse-green";
        if (emp.status === "offsite") {
            badgeColor = "#dc3545";
            pulseClass = "hudson-pulse-red";
        } else if (emp.status === "near_home") {
            badgeColor = "#fd7e14";
            pulseClass = "hudson-pulse-orange";
        }

        return `
            <div class="hudson-employee-marker ${pulseClass}" style="--badge-color: ${badgeColor};">
                <img src="${emp.avatar_url}" alt="${emp.name}" class="hudson-marker-avatar"/>
                <span class="hudson-marker-badge" style="background-color: ${badgeColor};"></span>
            </div>
        `;
    }

    updateMapMarkers() {
        if (!this.map || !window.L) {
            return;
        }

        Object.values(this.markers).forEach(m => m.remove());
        Object.values(this.homeCircles).forEach(c => c.remove());
        this.markers = {};
        this.homeCircles = {};

        const bounds = [];

        this.filteredEmployees.forEach((emp) => {
            if (!emp.lat || !emp.lon) return;

            const icon = window.L.divIcon({
                html: this.getMarkerHtml(emp),
                className: 'hudson-marker-wrapper',
                iconSize: [44, 44],
                iconAnchor: [22, 22],
            });

            const marker = window.L.marker([emp.lat, emp.lon], { icon }).addTo(this.map);
            marker.on('click', () => {
                this.selectEmployee(emp);
            });

            this.markers[emp.id] = marker;
            bounds.push([emp.lat, emp.lon]);

            if (emp.home_lat && emp.home_lon) {
                const radius = Number(emp.home_radius || 150);
                const homeCircle = window.L.circle([emp.home_lat, emp.home_lon], {
                    radius: radius,
                    color: '#0d6efd',
                    fillColor: '#0d6efd',
                    fillOpacity: 0.14,
                    weight: 2,
                    dashArray: '4, 4'
                }).addTo(this.map);
                homeCircle.bindTooltip(`${emp.name} - Home Geofence (${radius} m)`, { sticky: true });
                this.homeCircles[emp.id] = homeCircle;
            }
        });

        if (bounds.length > 0 && !this.state.selectedEmployee) {
            this.map.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
        }
    }

    selectEmployee(emp) {
        this.state.selectedEmployee = emp;
        if (this.state.viewMode === "map" && this.map && emp.lat && emp.lon) {
            this.map.flyTo([emp.lat, emp.lon], 16, { animate: true, duration: 1 });
        }
    }

    closeDrawer() {
        this.state.selectedEmployee = null;
    }

    openEmployeeRecord(employeeId) {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hr.employee',
            res_id: employeeId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openLocationHistory(employeeId) {
        this.actionService.doAction({
            name: _t("Location History"),
            type: 'ir.actions.act_window',
            res_model: 'hr.employee.location.log',
            views: [[false, 'list'], [false, 'form']],
            domain: [['employee_id', '=', employeeId]],
            context: { default_employee_id: employeeId },
            target: 'current',
        });
    }

    formatDistance(meters) {
        if (!meters && meters !== 0) return _t("N/A");
        if (meters < 1000) {
            return `${Math.round(meters)} m`;
        }
        return `${(meters / 1000).toFixed(2)} km`;
    }
}

registry.category("actions").add("wfh_live_map", WfhLiveMapView);
