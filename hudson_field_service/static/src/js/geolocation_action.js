/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, useState } from "@odoo/owl";

export class FieldServiceTimerWidget extends Component {
    static template = "hudson_field_service.FieldServiceTimerWidget";
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: false, loadingAction: '' });
    }

    get record() {
        return this.props.record;
    }

    get orderState() {
        return this.record.data.state;
    }

    get isTimerRunning() {
        return this.record.data.is_timer_running;
    }

    get showStart() {
        return ['new', 'scheduled'].includes(this.orderState) && !this.isTimerRunning;
    }

    get showResume() {
        return this.orderState === 'paused' && !this.isTimerRunning;
    }

    get showPause() {
        return this.isTimerRunning;
    }

    get showStop() {
        return this.isTimerRunning;
    }

    /**
     * Fetch geolocation from the browser.
     * Returns {latitude, longitude} or {latitude: 0, longitude: 0} on failure.
     */
    _fetchLocation() {
        return new Promise((resolve) => {
            if (!navigator.geolocation) {
                resolve({ latitude: 0, longitude: 0 });
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    resolve({
                        latitude: position.coords.latitude,
                        longitude: position.coords.longitude,
                    });
                },
                (error) => {
                    console.warn("Geolocation failed, proceeding without location:", error);
                    resolve({ latitude: 0, longitude: 0 });
                },
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
            );
        });
    }

    async onClickStart() {
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.loadingAction = 'start';
        try {
            // Save the record first (in case there are unsaved changes)
            await this.record.save();

            // Fetch geolocation
            const loc = await this._fetchLocation();

            // Call the backend with location
            await this.orm.call(
                this.record.resModel,
                "action_start_timer_with_location",
                [this.record.resId],
                { latitude: loc.latitude, longitude: loc.longitude }
            );

            // Reload the form
            await this.action.doAction({ type: "ir.actions.client", tag: "reload" });
        } catch (error) {
            this.notification.add("Error: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.loading = false;
            this.state.loadingAction = '';
        }
    }

    async onClickResume() {
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.loadingAction = 'resume';
        try {
            await this.record.save();
            const loc = await this._fetchLocation();
            await this.orm.call(
                this.record.resModel,
                "action_resume_timer_with_location",
                [this.record.resId],
                { latitude: loc.latitude, longitude: loc.longitude }
            );
            await this.action.doAction({ type: "ir.actions.client", tag: "reload" });
        } catch (error) {
            this.notification.add("Error: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.loading = false;
            this.state.loadingAction = '';
        }
    }

    async onClickPause() {
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.loadingAction = 'pause';
        try {
            await this.record.save();
            // Pause opens the stop wizard — fetch location first then open wizard
            const loc = await this._fetchLocation();
            if (loc.latitude && loc.longitude) {
                await this.orm.call(
                    this.record.resModel,
                    "action_log_location",
                    [this.record.resId],
                    { latitude: loc.latitude, longitude: loc.longitude, event_label: "Paused" }
                );
            }
            const result = await this.orm.call(
                this.record.resModel,
                "action_pause_timer",
                [this.record.resId]
            );
            if (result && result.type) {
                await this.action.doAction(result, {
                    onClose: async () => {
                        await this.record.load();
                    }
                });
            }
        } catch (error) {
            this.notification.add("Error: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.loading = false;
            this.state.loadingAction = '';
        }
    }

    async onClickStop() {
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.loadingAction = 'stop';
        try {
            await this.record.save();
            // Fetch location first, log it, then open stop wizard
            const loc = await this._fetchLocation();
            if (loc.latitude && loc.longitude) {
                await this.orm.call(
                    this.record.resModel,
                    "action_log_location",
                    [this.record.resId],
                    { latitude: loc.latitude, longitude: loc.longitude, event_label: "Stopped" }
                );
            }
            const result = await this.orm.call(
                this.record.resModel,
                "action_stop_timer",
                [this.record.resId]
            );
            if (result && result.type) {
                await this.action.doAction(result, {
                    onClose: async () => {
                        await this.record.load();
                    }
                });
            }
        } catch (error) {
            this.notification.add("Error: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.loading = false;
            this.state.loadingAction = '';
        }
    }
}

export const fieldServiceTimerWidget = {
    component: FieldServiceTimerWidget,
};

registry.category("view_widgets").add("field_service_timer", fieldServiceTimerWidget);
// Keep old name registered so any cached views still work
registry.category("view_widgets").add("log_location_button", fieldServiceTimerWidget);
