# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleAdvanceAttachWizard(models.TransientModel):
    _name = "sale.advance.attach.wizard"
    _description = "Attach Bank Transaction to Sale Order(s)"

    statement_line_id = fields.Many2one(
        "account.bank.statement.line", string="Bank Transaction",
        required=True, readonly=True)
    partner_id = fields.Many2one(
        "res.partner", string="Customer", required=True,
        compute="_compute_partner_id", store=True, readonly=False)
    commercial_partner_id = fields.Many2one(
        "res.partner", string="Commercial Entity",
        related="partner_id.commercial_partner_id")
    currency_id = fields.Many2one(
        "res.currency", string="Currency",
        related="statement_line_id.currency_id")
    amount = fields.Monetary(
        string="Transaction Amount", related="statement_line_id.amount",
        currency_field="currency_id")
    company_id = fields.Many2one(
        "res.company", related="statement_line_id.company_id")
    allocation_line_ids = fields.One2many(
        "sale.advance.attach.wizard.line", "wizard_id", string="Allocations")
    allocated_total = fields.Monetary(
        string="Allocated Total", compute="_compute_allocated_total",
        currency_field="currency_id")
    difference = fields.Monetary(
        string="Difference (must be 0)", compute="_compute_allocated_total",
        currency_field="currency_id")

    @api.depends("statement_line_id")
    def _compute_partner_id(self):
        for wiz in self:
            wiz.partner_id = wiz.statement_line_id.partner_id

    @api.depends("allocation_line_ids.amount", "amount")
    def _compute_allocated_total(self):
        for wiz in self:
            wiz.allocated_total = sum(wiz.allocation_line_ids.mapped("amount"))
            wiz.difference = wiz.amount - wiz.allocated_total

    def action_confirm(self):
        self.ensure_one()
        line = self.statement_line_id
        currency = self.currency_id or self.env.company.currency_id

        # ---- validations ----------------------------------------------------
        if line.is_reconciled:
            raise UserError(_("This transaction is already reconciled."))
        if not self.partner_id:
            raise UserError(_("Select the customer for this advance."))
        if not self.allocation_line_ids:
            raise UserError(_("Add at least one Sale Order allocation."))
        if currency.compare_amounts(self.allocated_total, self.amount) != 0:
            raise UserError(_(
                "The allocated total (%(alloc)s) must equal the transaction "
                "amount (%(amt)s).",
                alloc=self.allocated_total, amt=self.amount))
        for alloc in self.allocation_line_ids:
            order = alloc.sale_order_id
            if alloc.amount <= 0:
                raise UserError(_("Allocation amounts must be positive."))
            if order.state != "sale":
                raise UserError(_(
                    "Sale Order %s must be confirmed before attaching an "
                    "advance.", order.name))
            if order.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError(_(
                    "Sale Order %(order)s does not belong to customer "
                    "%(partner)s.",
                    order=order.name, partner=self.partner_id.display_name))

        # ---- make sure the bank line carries the partner (native helper) ----
        if not line.partner_id:
            line.set_partner_bank_statement_line(self.partner_id.id)

        # ---- one inbound customer payment per SO split ----------------------
        # A dedicated payment per allocation keeps each advance's receivable
        # line independent, so it can be reconciled and flagged per order.
        Payment = self.env["account.payment"]
        advance_vals = []
        liquidity_line_ids = []
        for alloc in self.allocation_line_ids:
            payment = Payment.create({
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_id.id,
                "amount": alloc.amount,
                "currency_id": currency.id,
                "date": line.date,
                "journal_id": line.journal_id.id,
                "memo": _("Advance for %s", alloc.sale_order_id.name),
            })
            payment.action_post()
            # (liquidity=outstanding receipts, counterpart=receivable, writeoff)
            liquidity_lines, counterpart_lines, _writeoff = payment._seek_for_lines()
            liquidity_line_ids += liquidity_lines.ids
            advance_vals.append({
                "sale_order_id": alloc.sale_order_id.id,
                "payment_id": payment.id,
                "statement_line_id": line.id,
                "move_line_id": counterpart_lines[:1].id,
                "amount": alloc.amount,
                "partner_id": self.partner_id.id,
                "currency_id": currency.id,
                "company_id": (self.company_id or self.env.company).id,
            })

        # ---- reconcile the bank line to the payment(s) via the native path --
        if liquidity_line_ids:
            line.set_line_bank_statement_line(liquidity_line_ids)

        self.env["sale.advance.payment"].create(advance_vals)
        return {"type": "ir.actions.act_window_close"}


class SaleAdvanceAttachWizardLine(models.TransientModel):
    _name = "sale.advance.attach.wizard.line"
    _description = "Attach Bank Transaction to Sale Order - Allocation Line"

    wizard_id = fields.Many2one(
        "sale.advance.attach.wizard", string="Wizard", required=True,
        ondelete="cascade")
    sale_order_id = fields.Many2one(
        "sale.order", string="Sale Order", required=True)
    amount = fields.Monetary(string="Amount", required=True)
    currency_id = fields.Many2one(
        "res.currency", related="wizard_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", related="wizard_id.partner_id")
