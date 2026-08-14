# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleAdvancePayment(models.Model):
    """Link between a customer advance (account.payment) and a Sale Order.

    One record per (payment, sale order) split. Created when a bank transaction
    is attached to one or more Sales Orders during Bank Reconciliation, and used
    later to allocate the advance against the eventual invoice.
    """
    _name = "sale.advance.payment"
    _description = "Sale Order Advance Payment"
    _order = "id desc"

    name = fields.Char(string="Reference", compute="_compute_name")
    sale_order_id = fields.Many2one(
        "sale.order", string="Sale Order", required=True, ondelete="cascade",
        index=True)
    payment_id = fields.Many2one(
        "account.payment", string="Customer Payment",
        ondelete="cascade", index=True,
        help="The inbound customer payment created from the bank transaction. "
             "It is empty for migrated journal entries without a payment record.")
    statement_line_id = fields.Many2one(
        "account.bank.statement.line", string="Bank Transaction",
        ondelete="set null",
        help="The source bank statement line this advance came from.")
    move_line_id = fields.Many2one(
        "account.move.line", string="Receivable Credit Line",
        ondelete="set null",
        help="The payment's receivable credit journal item, reconciled against "
             "the invoice when the advance is allocated.")
    amount = fields.Monetary(string="Advance Amount", required=True)
    partner_id = fields.Many2one("res.partner", string="Customer")
    currency_id = fields.Many2one(
        "res.currency", string="Currency",
        default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company)
    state = fields.Selection(
        selection=[
            ("received", "Received"),
            ("allocated", "Allocated"),
        ],
        string="Status", compute="_compute_state", store=True, index=True,
        help="Received: the advance's receivable credit is still open (not yet "
             "applied to an invoice).\n"
             "Allocated: it has been reconciled against an invoice (via this "
             "module's button or Odoo's native outstanding-credits flow).")

    @api.depends("move_line_id.reconciled")
    def _compute_state(self):
        for rec in self:
            rec.state = "allocated" if (
                rec.move_line_id and rec.move_line_id.reconciled) else "received"

    @api.depends(
        "sale_order_id.name", "payment_id.name", "move_line_id.move_id.name",
        "amount")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s - %s" % (
                rec.sale_order_id.name or "",
                rec.payment_id.name or rec.move_line_id.move_id.name or "",
            )

    @api.constrains("move_line_id")
    def _check_move_line_mapped_once(self):
        for advance in self.filtered("move_line_id"):
            if self.search_count([
                    ("move_line_id", "=", advance.move_line_id.id),
                    ("id", "!=", advance.id)]) > 0:
                raise ValidationError(_(
                    "A receivable journal item can only be mapped to one "
                    "Sales Order advance."))

    def _get_open_amount(self):
        """Return this advance's open residual in its own currency."""
        self.ensure_one()
        line = self.move_line_id
        if not line:
            return 0.0
        if line.currency_id and line.currency_id == self.currency_id:
            return abs(line.amount_residual_currency)
        if line.company_currency_id == self.currency_id:
            return abs(line.amount_residual)
        return line.company_currency_id._convert(
            abs(line.amount_residual), self.currency_id, self.company_id,
            line.date or fields.Date.context_today(self))
