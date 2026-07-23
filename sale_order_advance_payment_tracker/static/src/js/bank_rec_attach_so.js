/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { BankRecButtonList } from "@account_accountant/components/bank_reconciliation/button_list/button_list";

// Add an "Attach to Sales Order" entry to the bank statement line's action
// dropdown (the "⋮" menu), right after "Reconcile". It records the received
// amount as a customer advance against one or more Sales Orders. Standard
// reconciliation is untouched.
patch(BankRecButtonList.prototype, {
    get buttons() {
        const buttons = super.buttons;
        // Only offer it for incoming (received) amounts on unreconciled lines.
        if (this.statementLineData.is_reconciled || this.statementLineData.amount <= 0) {
            return buttons;
        }
        const attachButton = {
            label: _t("Attach to Sales Order"),
            action: this.attachToSalesOrder.bind(this),
            classes: "attach-so-btn",
        };
        // Rebuild the object so the new entry lands right after "reconcile"
        // (dropdown order follows insertion order). Falls back to the end.
        const result = {};
        let inserted = false;
        for (const [key, value] of Object.entries(buttons)) {
            result[key] = value;
            if (key === "reconcile") {
                result.attachSo = attachButton;
                inserted = true;
            }
        }
        if (!inserted) {
            result.attachSo = attachButton;
        }
        return result;
    },

    attachToSalesOrder() {
        this.action.doAction(
            "sale_order_advance_payment_tracker.action_sale_advance_attach_wizard",
            {
                additionalContext: {
                    default_statement_line_id: this.statementLineData.id,
                },
                onClose: () => {
                    this.props.statementLine.load();
                },
            }
        );
    },
});
