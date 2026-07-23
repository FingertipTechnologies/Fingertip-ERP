# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def action_attach_to_sale_order(self):
        """Open the wizard to attach this bank transaction to Sale Order(s).

        Called from the injected "Attach to Sales Order" button in the Bank
        Reconciliation widget. Standard reconciliation is untouched; this only
        opens a wizard that records a customer advance.
        """
        self.ensure_one()
        if self.is_reconciled:
            raise UserError(_(
                "This transaction is already reconciled. Undo the "
                "reconciliation before attaching it to a Sales Order."))
        if self.amount <= 0:
            raise UserError(_(
                "Only received (incoming) amounts can be attached to a Sales "
                "Order as a customer advance."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Attach to Sales Order"),
            "res_model": "sale.advance.attach.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_statement_line_id": self.id,
            },
        }
