# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def action_attach_to_sale_order(self):
        """Open the wizard to attach this bank transaction to ProForma(s).

        Called from the injected "Attach to ProForma" button in the Bank
        Reconciliation widget. Standard reconciliation is untouched; this only
        opens a wizard that records a customer advance.
        """
        self.ensure_one()
        if self.is_reconciled:
            raise UserError(_(
                "This transaction is already reconciled. Undo the "
                "reconciliation before attaching it to a ProForma."))
        if self.amount <= 0:
            raise UserError(_(
                "Only received (incoming) amounts can be attached to a "
                "ProForma as a customer advance."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Attach to ProForma"),
            "res_model": "sale.advance.attach.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_statement_line_id": self.id,
            },
        }
