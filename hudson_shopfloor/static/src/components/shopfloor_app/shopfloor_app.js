/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ShopFloorApp extends Component {
    static template = "hudson_shopfloor.ShopFloorApp";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            workcenters: [],
            selectedWorkcenter: null,
            mos: [],
            activeWoId: null,
            currentTime: new Date(),
            
            // Employee Operator tracking
            employees: [],
            activeEmployee: null,
            showPinModal: false,
            pendingEmployee: null,
            pinError: false,
            pinInput: "",
        });

        onWillStart(async () => {
            await this.loadEmployees();
            await this.loadWorkcenters();
        });

        this.timerInterval = setInterval(() => {
            this.state.currentTime = new Date();
        }, 1000);

        onWillDestroy(() => {
            clearInterval(this.timerInterval);
        });
    }
    
    async loadEmployees() {
        // Fetch employees that have an associated user
        this.state.employees = await this.orm.searchRead("hr.employee", [["user_id", "!=", false]], ["name", "user_id"]);
    }

    async loadWorkcenters() {
        const workcenters = await this.orm.searchRead("mrp.workcenter", [], ["name", "code"]);
        
        const counts = await this.orm.call(
            "mrp.workorder", 
            "read_group",
            [
                [["state", "in", ["ready", "progress", "pending"]]], 
                ["workcenter_id"], 
                ["workcenter_id"]
            ]
        );
        
        const countMap = {};
        let totalCount = 0;
        for (let c of counts) {
            const wcId = c.workcenter_id[0];
            countMap[wcId] = c.workcenter_id_count;
            totalCount += c.workcenter_id_count;
        }

        this.state.workcenters = [
            { id: 'overview', name: 'Overview', count: totalCount },
            ...workcenters.map(wc => ({
                ...wc,
                count: countMap[wc.id] || 0
            }))
        ];

        if (this.state.workcenters.length > 0) {
            await this.selectWorkcenter(this.state.workcenters[0].id);
        }
    }

    async selectWorkcenter(workcenterId) {
        this.state.selectedWorkcenter = workcenterId;
        this.state.activeWoId = null;
        await this.loadMOs(workcenterId);
    }

    async loadMOs(workcenterId) {
        let domain = [["state", "in", ["ready", "progress", "pending"]]];
        if (workcenterId !== 'overview') {
            domain.push(["workcenter_id", "=", workcenterId]);
        }
        
        const activeWos = await this.orm.searchRead("mrp.workorder", domain, ["production_id"]);
        
        if (activeWos.length === 0) {
            this.state.mos = [];
            return;
        }

        const productionIds = [...new Set(activeWos.map(wo => wo.production_id[0]))];
        
        // Filter MOs based on the active employee's linked User ID
        let moDomain = [["id", "in", productionIds]];
        if (this.state.activeEmployee) {
            moDomain.push(["user_id", "=", this.state.activeEmployee.user_id[0]]);
        }
        const validMos = await this.orm.searchRead("mrp.production", moDomain, ["id"]);
        const validMoIds = validMos.map(m => m.id);

        if (validMoIds.length === 0) {
            this.state.mos = [];
            return;
        }

        const allWosDomain = [["production_id", "in", validMoIds]];
        const fields = ["name", "production_id", "product_id", "qty_producing", "qty_production", "state", "workcenter_id", "date_start", "duration"];
        const allWos = await this.orm.searchRead("mrp.workorder", allWosDomain, fields);

        const grouped = {};
        for (let wo of allWos) {
            const moId = wo.production_id[0];
            if (!grouped[moId]) {
                grouped[moId] = {
                    id: moId,
                    name: wo.production_id[1],
                    product_id: wo.product_id,
                    qty_producing: wo.qty_producing,
                    qty_production: wo.qty_production,
                    workorders: [],
                    showOptions: false,
                };
            }
            grouped[moId].workorders.push(wo);
        }

        Object.values(grouped).forEach(mo => {
            mo.workorders.sort((a, b) => a.id - b.id);
        });

        this.state.mos = Object.values(grouped);
    }

    // -- Employee PIN Methods --
    
    clickEmployee(emp) {
        if (this.state.activeEmployee && this.state.activeEmployee.id === emp.id) {
            // Already logged in as this person, maybe prompt to logout
            return;
        }
        this.state.pendingEmployee = emp;
        this.state.pinInput = "";
        this.state.pinError = false;
        this.state.showPinModal = true;
    }
    
    closePinModal() {
        this.state.showPinModal = false;
        this.state.pendingEmployee = null;
        this.state.pinInput = "";
        this.state.pinError = false;
    }
    
    addPinDigit(digit) {
        this.state.pinInput += digit.toString();
        this.state.pinError = false;
    }
    
    clearPin() {
        this.state.pinInput = "";
        this.state.pinError = false;
    }
    
    async submitPin() {
        try {
            const isValid = await this.orm.call("hr.employee", "check_shopfloor_pin", [this.state.pendingEmployee.id, this.state.pinInput]);
            if (isValid) {
                this.state.activeEmployee = this.state.pendingEmployee;
                this.closePinModal();
                await this.loadMOs(this.state.selectedWorkcenter); // Reload to filter
            } else {
                this.state.pinError = true;
                this.state.pinInput = "";
            }
        } catch (e) {
            console.error("Error verifying PIN:", e);
            this.state.pinError = true;
        }
    }
    
    async logoutEmployee() {
        this.state.activeEmployee = null;
        await this.loadMOs(this.state.selectedWorkcenter);
    }

    // -- Workorder Methods --

    openOperation(woId) {
        this.state.activeWoId = woId;
    }

    closeOperation() {
        this.state.activeWoId = null;
    }

    get activeWo() {
        if (!this.state.activeWoId) return null;
        for (let mo of this.state.mos) {
            const wo = mo.workorders.find(w => w.id === this.state.activeWoId);
            if (wo) return wo;
        }
        return null;
    }

    formatDuration(dateStartStr, initialDurationMin) {
        if (!dateStartStr) return "0m 0s";
        
        const initialMs = initialDurationMin * 60 * 1000;
        const dateStart = new Date(dateStartStr.replace(' ', 'T') + 'Z');
        const elapsedMs = this.state.currentTime - dateStart;
        
        const totalMs = initialMs + Math.max(0, elapsedMs);
        const totalSecs = Math.floor(totalMs / 1000);
        
        const m = Math.floor(totalSecs / 60);
        const s = totalSecs % 60;
        return `${m}m ${s}s`;
    }

    async actionStartWorkorder(workorderId) {
        await this.orm.call("mrp.workorder", "button_start", [[workorderId]]);
        await this.loadMOs(this.state.selectedWorkcenter);
        this.state.activeWoId = workorderId;
    }

    async actionCloseProduction(workorderId) {
        await this.orm.call("mrp.workorder", "button_finish", [[workorderId]]);
        this.state.activeWoId = null;
        await this.loadMOs(this.state.selectedWorkcenter);
    }

    async actionScrap(workorderId) {
        const action = await this.orm.call("mrp.workorder", "button_scrap", [[workorderId]]);
        if (action) {
            this.action.doAction(action);
        }
    }

    toggleOptions(moId) {
        const mo = this.state.mos.find(m => m.id === moId);
        if (mo) {
            mo.showOptions = !mo.showOptions;
        }
    }
}

registry.category("actions").add("hudson_shopfloor.shopfloor_app", ShopFloorApp);
