/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";

export class BankRecActionDropdown extends Component {
    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onReconcile() {
        const domain = [
            ['account_id.reconcile', '=', true],
            ['reconciled', '=', false],
            ['move_id.state', '=', 'posted'],
            ['journal_id.type', 'not in', ['bank', 'cash']]
        ];
        
        const amount = this.props.record.data.amount;
        if (amount < 0) {
            domain.push(['amount_residual', '<', 0]);
        } else if (amount > 0) {
            domain.push(['amount_residual', '>', 0]);
        }
        
        this.env.services.dialog.add(SelectCreateDialog, {
            resModel: "account.move.line",
            title: "Search: Journal Items to Match",
            domain: domain,
            multiSelect: true,
            noCreate: true,
            onSelected: async (resIds) => {
                if (resIds.length > 0) {
                    await this.orm.call(
                        "account.bank.statement.line",
                        "action_hudson_reconcile_items",
                        [[this.props.record.resId], resIds]
                    );
                    window.location.reload();
                }
            }
        });
    }

    async onUploadBills() {
        const action = await this.orm.call(
            "account.bank.statement.line",
            "action_hudson_upload_bills",
            [[this.props.record.resId]]
        );
        if (action) {
            this.action.doAction(action);
        }
    }

    async onDelete() {
        // Call unlink directly or via a method
        await this.orm.unlink("account.bank.statement.line", [this.props.record.resId]);
        // Reload the view
        this.props.record.model.load();
    }
    
    async onInternalTransfers() {
        await this.orm.call(
            "account.bank.statement.line",
            "action_hudson_internal_transfer",
            [[this.props.record.resId]]
        );
        window.location.reload();
    }
    
    async onManageModels() {
        this.env.services.action.doAction("account.action_account_reconcile_model");
    }
}

BankRecActionDropdown.template = "hudson_accounting_enhancements.BankRecActionDropdown";
BankRecActionDropdown.components = { Dropdown, DropdownItem };

export const bankRecActionDropdown = {
    component: BankRecActionDropdown,
};

registry.category("fields").add("bank_rec_action_dropdown", bankRecActionDropdown);

import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

function hudsonSetPartnerAction(env, action) {
    env.services.dialog.add(SelectCreateDialog, {
        resModel: "res.partner",
        title: "Search: Partner",
        onSelected: async (resIds) => {
            if (resIds.length > 0) {
                const partnerId = resIds[0];
                const statementLineId = action.context.default_statement_line_id;
                await env.services.orm.write("account.bank.statement.line", [statementLineId], {
                    partner_id: partnerId
                });
                // Reload window to reflect changes
                window.location.reload();
            }
        }
    });
}
registry.category("actions").add("hudson_set_partner", hudsonSetPartnerAction);

function hudsonSetAccountAction(env, action) {
    env.services.dialog.add(SelectCreateDialog, {
        resModel: "account.account",
        title: "Search: Account",
        onSelected: async (resIds) => {
            if (resIds.length > 0) {
                const accountId = resIds[0];
                const statementLineId = action.context.default_statement_line_id;
                await env.services.orm.write("account.bank.statement.line", [statementLineId], {
                    hudson_account_id: accountId
                });
                window.location.reload();
            }
        }
    });
}
registry.category("actions").add("hudson_set_account", hudsonSetAccountAction);
