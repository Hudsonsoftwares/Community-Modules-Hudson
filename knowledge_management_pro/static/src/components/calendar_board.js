/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";

export class KnowledgeCalendarBoard extends Component {
    static template = xml`
        <div class="km_pro_calendar_board" style="display: flex; flex-direction: column; height: 100%; background: #212529; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
            
            <!-- Header (Kanban-style) -->
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid #343a40;">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <button t-on-click="addNewEventClick" style="background: #714B67; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer; font-weight: 500; font-size: 0.9rem;">New</button>
                    <div style="font-size: 1rem; color: #e0e0e0; display: flex; align-items: center; gap: 8px;">
                        <span>Calendar of <t t-esc="props.title || 'Items'"/></span>
                        <i class="fa fa-cog" style="font-size: 0.9rem; cursor: pointer; color: #a0a0a0;"></i>
                    </div>
                </div>
                <div style="display: flex; align-items: center;">
                    <div style="position: relative; width: 250px;">
                        <i class="fa fa-search" style="position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: #a0a0a0; font-size: 0.85rem;"></i>
                        <input type="text" placeholder="Search..." style="width: 100%; background: #1a1c1e; border: 1px solid #343a40; color: #e0e0e0; padding: 4px 30px; border-radius: 3px; outline: none; font-size: 0.85rem;"/>
                        <i class="fa fa-caret-down" style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); color: #a0a0a0; cursor: pointer; font-size: 0.85rem;"></i>
                    </div>
                </div>
                <div style="width: 50px;"></div>
            </div>

            <!-- Sub-Header (Navigation) -->
            <div style="display: flex; align-items: center; padding: 12px 16px; border-bottom: 1px solid #343a40; gap: 12px;">
                <div style="display: flex; border: 1px solid #495057; border-radius: 4px; overflow: hidden;">
                    <button t-on-click="prevWeek" style="background: #2b2b30; color: #e0e0e0; border: none; padding: 6px 12px; cursor: pointer; border-right: 1px solid #495057;"><i class="fa fa-arrow-left"></i></button>
                    <button t-on-click="nextWeek" style="background: #2b2b30; color: #e0e0e0; border: none; padding: 6px 12px; cursor: pointer;"><i class="fa fa-arrow-right"></i></button>
                </div>
                <div style="position: relative;">
                    <button style="background: #2b2b30; color: #e0e0e0; border: 1px solid #495057; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-weight: 500; display: flex; gap: 6px; align-items: center;">Week <i class="fa fa-caret-down"></i></button>
                </div>
                <button t-on-click="goToToday" style="background: #2b2b30; color: #e0e0e0; border: 1px solid #495057; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-weight: 500;">Today</button>
                
                <div style="font-weight: 600; color: #ffffff; font-size: 1.05rem; margin-left: 12px;">
                    <t t-esc="dateRangeText"/>
                </div>
            </div>

            <!-- Calendar Grid -->
            <div style="display: flex; flex-direction: column; flex: 1; overflow: hidden;">
                
                <!-- Days of Week Header -->
                <div style="display: flex; padding-left: 60px; border-bottom: 1px solid #343a40; background: #212529;">
                    <t t-foreach="weekDays" t-as="day" t-key="day.dateStr">
                        <div style="flex: 1; text-align: center; padding: 12px 0; display: flex; flex-direction: column; gap: 8px;">
                            <span style="font-size: 0.75rem; font-weight: 700; color: #a0a0a0;"><t t-esc="day.name"/></span>
                            <div style="display: flex; justify-content: center;">
                                <div t-att-style="'width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 50%; font-size: 1.2rem; ' + (day.isToday ? 'background: #d63939; color: white;' : 'color: #e0e0e0;')">
                                    <t t-esc="day.dayNum"/>
                                </div>
                            </div>
                        </div>
                    </t>
                </div>

                <!-- Week Grid Body -->
                <div class="km-calendar-scroll" style="flex: 1; overflow-y: auto; position: relative; background: #1e2124;" t-ref="scrollContainer">
                    <div style="display: flex; position: relative;">
                        <!-- Timeline left axis -->
                        <div style="width: 60px; min-width: 60px; display: flex; flex-direction: column;">
                            <t t-foreach="hours" t-as="hour" t-key="hour.val">
                                <div style="height: 60px; position: relative; border-right: 1px solid #343a40;">
                                    <span t-if="hour.val !== 0" style="position: absolute; top: -8px; right: 8px; font-size: 0.75rem; color: #a0a0a0;"><t t-esc="hour.label"/></span>
                                </div>
                            </t>
                        </div>
                        
                        <!-- Grid lines and cells -->
                        <div style="flex: 1; display: flex; position: relative;">
                            <t t-foreach="weekDays" t-as="day" t-key="day.dateStr">
                                <div style="flex: 1; border-right: 1px solid #343a40; display: flex; flex-direction: column; position: relative;">
                                    <t t-foreach="hours" t-as="hour" t-key="hour.val">
                                        <div t-on-click="() => this.onCellClick(day.dateStr, hour.val)" style="height: 60px; border-bottom: 1px solid #343a40; box-sizing: border-box; cursor: pointer; position: relative;">
                                            <!-- Event input if active -->
                                            <t t-if="state.addingEventCell === (day.dateStr + '-' + hour.val)">
                                                <div style="position: absolute; top: 0; left: 0; right: 0; background: #2b2b30; border: 1px solid #4da3ff; z-index: 10; padding: 4px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                                                    <input type="text" t-model="state.newEventTitle" 
                                                           t-on-keydown="(e) => e.key === 'Enter' and this.saveNewEvent()"
                                                           t-on-blur="cancelAddEvent"
                                                           placeholder="New event..." 
                                                           style="width: 100%; background: transparent; border: none; color: white; font-size: 0.85rem; outline: none;" 
                                                           autofocus="autofocus" />
                                                </div>
                                            </t>
                                        </div>
                                    </t>
                                    
                                    <!-- Render events for this day -->
                                    <t t-foreach="getEventsForDay(day.dateStr)" t-as="ev" t-key="ev.id">
                                        <div t-on-click.stop="() => this.onEventClick(ev)" 
                                             t-att-style="'position: absolute; left: 2px; right: 2px; top: ' + (ev.startHour * 60 + 1) + 'px; height: 58px; background: #714B67; border-left: 3px solid #99628b; color: white; padding: 4px 6px; border-radius: 3px; font-size: 0.85rem; overflow: hidden; cursor: pointer; z-index: 5; box-shadow: 0 1px 3px rgba(0,0,0,0.2);'">
                                            <div style="font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"><t t-esc="ev.title"/></div>
                                            <div style="font-size: 0.7rem; color: rgba(255,255,255,0.7);"><t t-esc="formatHour(ev.startHour)"/></div>
                                        </div>
                                    </t>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    static props = ["title", "initialData", "onChange"];

    setup() {
        const today = new Date();
        const startOfWeek = new Date(today);
        startOfWeek.setDate(today.getDate() - today.getDay());
        startOfWeek.setHours(0,0,0,0);
        
        this.state = useState({
            currentWeekStart: startOfWeek,
            events: [],
            addingEventCell: null,
            newEventTitle: "",
            addingDateStr: null,
            addingHour: null
        });

        if (this.props.initialData) {
            try {
                const parsed = JSON.parse(this.props.initialData);
                if (parsed.events) {
                    // Filter out old format events (no startHour)
                    this.state.events = parsed.events.filter(e => e.startHour !== undefined);
                }
            } catch (e) {
                console.error("Failed to parse calendar initial data", e);
            }
        }
    }

    get weekDays() {
        const start = new Date(this.state.currentWeekStart);
        const days = [];
        const today = new Date();
        const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
        const dayNames = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

        for (let i = 0; i < 7; i++) {
            const d = new Date(start);
            d.setDate(start.getDate() + i);
            const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
            days.push({
                name: dayNames[i],
                dayNum: d.getDate(),
                dateStr: dateStr,
                isToday: dateStr === todayStr
            });
        }
        return days;
    }

    get hours() {
        return Array.from({length: 24}, (_, i) => {
            if (i === 0) return { val: 0, label: '12am' };
            if (i < 12) return { val: i, label: i + 'am' };
            if (i === 12) return { val: 12, label: '12pm' };
            return { val: i, label: (i - 12) + 'pm' };
        });
    }

    formatHour(hour) {
        if (hour === 0) return '12am';
        if (hour < 12) return hour + 'am';
        if (hour === 12) return '12pm';
        return (hour - 12) + 'pm';
    }

    get dateRangeText() {
        const start = new Date(this.state.currentWeekStart);
        const end = new Date(start);
        end.setDate(start.getDate() + 6);
        
        const startMonth = start.toLocaleString('default', { month: 'long' });
        const endMonth = end.toLocaleString('default', { month: 'long' });
        const year = end.getFullYear();
        
        const firstJan = new Date(year, 0, 1);
        const days = Math.floor((start - firstJan) / (24 * 60 * 60 * 1000));
        const weekNumber = Math.ceil((days + firstJan.getDay() + 1) / 7);

        if (startMonth === endMonth) {
            return `${startMonth} ${year} Week ${weekNumber}`;
        } else {
            return `${startMonth} - ${endMonth} ${year} Week ${weekNumber}`;
        }
    }

    getEventsForDay(dateStr) {
        return this.state.events.filter(e => e.date === dateStr);
    }

    prevWeek() {
        const current = new Date(this.state.currentWeekStart);
        current.setDate(current.getDate() - 7);
        this.state.currentWeekStart = current;
    }

    nextWeek() {
        const current = new Date(this.state.currentWeekStart);
        current.setDate(current.getDate() + 7);
        this.state.currentWeekStart = current;
    }

    goToToday() {
        const today = new Date();
        const startOfWeek = new Date(today);
        startOfWeek.setDate(today.getDate() - today.getDay());
        startOfWeek.setHours(0,0,0,0);
        this.state.currentWeekStart = startOfWeek;
    }

    addNewEventClick() {
        // Quick add to today at 9am
        const today = new Date();
        const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
        this.onCellClick(todayStr, 9);
    }

    onCellClick(dateStr, hour) {
        const cellKey = dateStr + '-' + hour;
        if (this.state.addingEventCell === cellKey) return;
        this.state.addingEventCell = cellKey;
        this.state.addingDateStr = dateStr;
        this.state.addingHour = hour;
        this.state.newEventTitle = "";
    }

    cancelAddEvent() {
        setTimeout(() => {
            this.state.addingEventCell = null;
            this.state.addingDateStr = null;
            this.state.addingHour = null;
            this.state.newEventTitle = "";
        }, 150);
    }

    saveNewEvent() {
        if (this.state.newEventTitle.trim() && this.state.addingDateStr) {
            this.state.events.push({
                id: Math.random().toString(36).substr(2, 9),
                title: this.state.newEventTitle.trim(),
                date: this.state.addingDateStr,
                startHour: this.state.addingHour
            });
            this.triggerChange();
        }
        this.state.addingEventCell = null;
        this.state.addingDateStr = null;
        this.state.addingHour = null;
        this.state.newEventTitle = "";
    }

    onEventClick(ev) {
        if (confirm(`Delete event "${ev.title}"?`)) {
            this.state.events = this.state.events.filter(e => e.id !== ev.id);
            this.triggerChange();
        }
    }

    triggerChange() {
        if (this.props.onChange) {
            this.props.onChange(JSON.stringify({ events: this.state.events }));
        }
    }
}
