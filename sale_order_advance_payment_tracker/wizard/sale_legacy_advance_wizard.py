# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleLegacyAdvanceWizard(models.TransientModel):
    _name = "sale.legacy.advance.wizard"
    _description = "Map Existing Receivable Credit as Sale Order Advance"

    sale_order_id = fields.Many2one(
        "sale.order", string="Sales Order", required=True, readonly=True)
    partner_id = fields.Many2one(
        "res.partner", related="sale_order_id.partner_id", readonly=True)
    commercial_partner_id = fields.Many2one(
        "res.partner", related="partner_id.commercial_partner_id", readonly=True)
    company_id = fields.Many2one(
        "res.company", related="sale_order_id.company_id", readonly=True)
    currency_id = fields.Many2one(
        "res.currency", related="sale_order_id.currency_id", readonly=True)
    move_line_id = fields.Many2one(
        "account.move.line", string="Open Receivable Credit", required=True,
        help="A posted, unreconciled customer receivable credit from the "
             "historical payment or journal entry.")
    accounting_date = fields.Date(
        related="move_line_id.date", string="Accounting Date", readonly=True)
    journal_entry_id = fields.Many2one(
        "account.move", related="move_line_id.move_id",
        string="Journal Entry", readonly=True)
    amount = fields.Monetary(
        string="Advance Amount", compute="_compute_amount",
        currency_field="currency_id")

    @api.depends(
        "move_line_id.amount_residual",
        "move_line_id.amount_residual_currency",
        "currency_id")
    def _compute_amount(self):
        for wizard in self:
            line = wizard.move_line_id
            if not line:
                wizard.amount = 0.0
            elif line.currency_id and line.currency_id == wizard.currency_id:
                wizard.amount = abs(line.amount_residual_currency)
            elif line.company_currency_id == wizard.currency_id:
                wizard.amount = abs(line.amount_residual)
            else:
                wizard.amount = 0.0

    def action_confirm(self):
        self.ensure_one()
        order = self.sale_order_id
        line = self.move_line_id

        if order.state != "sale":
            raise UserError(_(
                "Only confirmed Sales Orders can receive a legacy advance."))
        if line.parent_state != "posted":
            raise UserError(_("The selected journal entry must be posted."))
        if line.company_id != order.company_id:
            raise UserError(_(
                "The journal item and Sales Order must belong to the same company."))
        if line.account_type != "asset_receivable" or line.credit <= 0:
            raise UserError(_(
                "Select a customer receivable credit journal item."))
        if line.reconciled or line.company_currency_id.is_zero(line.amount_residual):
            raise UserError(_(
                "The selected receivable credit has no open amount remaining."))
        if (line.partner_id.commercial_partner_id !=
                order.partner_id.commercial_partner_id):
            raise UserError(_(
                "The journal item customer must match the Sales Order customer."))
        line_currency = line.currency_id or line.company_currency_id
        if line_currency != order.currency_id:
            raise UserError(_(
                "The journal item currency (%(line_currency)s) must match the "
                "Sales Order currency (%(order_currency)s).",
                line_currency=line_currency.display_name,
                order_currency=order.currency_id.display_name))
        if self.env["sale.advance.payment"].search_count([
                ("move_line_id", "=", line.id)]):
            raise UserError(_(
                "This receivable credit is already mapped as a Sales Order advance."))

        self.env["sale.advance.payment"].create({
            "sale_order_id": order.id,
            "payment_id": line.payment_id.id,
            "statement_line_id": line.statement_line_id.id,
            "move_line_id": line.id,
            "amount": self.amount,
            "partner_id": order.partner_id.id,
            "currency_id": order.currency_id.id,
            "company_id": order.company_id.id,
        })
        return {"type": "ir.actions.act_window_close"}
