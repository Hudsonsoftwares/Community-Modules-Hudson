/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";

export class KnowledgeCalendarMockup extends Component {
    setup() {
        this.state = useState({
            currentDate: new Date(),
        });
    }
}

KnowledgeCalendarMockup.template = xml`
    <div class="km_pro_calendar_view" style="display: flex; flex-direction: column; height: 100%; background: #242426; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        <!-- Header -->
        <div class="km_pro_calendar_header" style="display: flex; align-items: center; padding: 12px 16px; border-bottom: 1px solid #36363a; gap: 16px; background: #2a2a2c;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <button style="background: #3f3f46; color: white; border: none; padding: 6px 10px; border-radius: 4px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center;"><i class="fa fa-arrow-left"></i></button>
                <button style="background: #3f3f46; color: white; border: none; padding: 6px 10px; border-radius: 4px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center;"><i class="fa fa-arrow-right"></i></button>
                <button style="background: transparent; color: #e0e0e0; border: 1px solid #3f3f46; padding: 6px 12px; border-radius: 4px; font-weight: 600; cursor: pointer;">Today</button>
            </div>
            <h3 style="margin: 0; font-size: 1.1rem; font-weight: 600; color: #ffffff;">August 2026 Week 34</h3>
        </div>
        
        <!-- Days Header -->
        <div style="display: flex; border-bottom: 1px solid #36363a; background: #242426; margin-left: 60px;">
            <div style="flex: 1; text-align: center; padding: 12px 0; border-right: 1px solid #36363a;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">SUN</div>
                <div style="font-size: 1.2rem; margin-top: 4px;">16</div>
            </div>
            <div style="flex: 1; text-align: center; padding: 12px 0; border-right: 1px solid #36363a;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">MON</div>
                <div style="font-size: 1.2rem; margin-top: 4px;">17</div>
            </div>
            <div style="flex: 1; text-align: center; padding: 12px 0; border-right: 1px solid #36363a;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">TUE</div>
                <div style="font-size: 1.2rem; margin-top: 4px; display: inline-block; background: #ea5455; color: white; width: 32px; height: 32px; line-height: 32px; border-radius: 50%;">18</div>
            </div>
            <div style="flex: 1; text-align: center; padding: 12px 0; border-right: 1px solid #36363a;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">WED</div>
                <div style="font-size: 1.2rem; margin-top: 4px;">19</div>
            </div>
            <div style="flex: 1; text-align: center; padding: 12px 0; border-right: 1px solid #36363a;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">THU</div>
                <div style="font-size: 1.2rem; margin-top: 4px;">20</div>
            </div>
            <div style="flex: 1; text-align: center; padding: 12px 0; border-right: 1px solid #36363a;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">FRI</div>
                <div style="font-size: 1.2rem; margin-top: 4px;">21</div>
            </div>
            <div style="flex: 1; text-align: center; padding: 12px 0;">
                <div style="font-size: 0.75rem; text-transform: uppercase; color: #a0a0a0; font-weight: 600;">SAT</div>
                <div style="font-size: 1.2rem; margin-top: 4px;">22</div>
            </div>
        </div>
        
        <!-- Grid Body -->
        <div style="flex: 1; overflow-y: auto; display: flex; background: #242426; position: relative;">
            <!-- Times Column -->
            <div style="width: 60px; flex-shrink: 0; border-right: 1px solid #36363a; position: relative;">
                <t t-foreach="[6,7,8,9,10,11,12]" t-as="hour" t-key="hour">
                    <div style="height: 60px; text-align: right; padding-right: 8px; color: #a0a0a0; font-size: 0.8rem; box-sizing: border-box; display: flex; flex-direction: column; justify-content: flex-end;">
                        <span style="transform: translateY(50%); background: #242426; padding: 0 4px;"><t t-esc="hour"/><t t-esc="hour == 12 ? 'pm' : 'am'"/></span>
                    </div>
                </t>
            </div>
            <!-- Days Grid Columns -->
            <div style="flex: 1; position: relative; display: flex;">
                <!-- Horizontal grid lines -->
                <div style="position: absolute; inset: 0; pointer-events: none;">
                    <t t-foreach="[1,2,3,4,5,6,7]" t-as="row" t-key="row">
                        <div style="height: 60px; border-bottom: 1px solid #36363a; box-sizing: border-box;"></div>
                    </t>
                </div>
                
                <t t-foreach="[0,1,2,3,4,5,6]" t-as="col" t-key="col">
                    <div style="flex: 1; border-right: 1px solid #36363a; position: relative;">
                        <!-- Red line current time marker on Tuesday -->
                        <t t-if="col == 2">
                            <div style="position: absolute; left: 0; right: 0; top: 390px; height: 1px; background: #ea5455; z-index: 2;">
                                <div style="position: absolute; left: -4px; top: -4px; width: 8px; height: 8px; border-radius: 50%; background: #ea5455;"></div>
                            </div>
                        </t>
                    </div>
                </t>
            </div>
        </div>
    </div>
`;
