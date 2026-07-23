# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    advance_payment_ids = fields.One2many(
        "sale.advance.payment", "sale_order_id", string="Advances")
    advance_payment_count = fields.Integer(
        string="Advance Count", compute="_compute_advance_amounts")
    amount_advance_received = fields.Monetary(
        string="Advance Received", compute="_compute_advance_amounts",
        store=True,
        help="Total customer advances attached to this order (received before "
             "or independently of invoicing).")
    amount_advance_allocated = fields.Monetary(
        string="Advance Allocated", compute="_compute_advance_amounts",
        store=True, help="Advances already applied to a customer invoice.")
    amount_advance_remaining = fields.Monetary(
        string="Remaining Balance", compute="_compute_advance_amounts",
        store=True,
        help="Order total minus advances received (indicative coverage).")
    paid_amount = fields.Monetary(
        string="Paid Amount", compute="_compute_paid_amount", store=True,
        help="Total paid on this order: payments received through posted "
             "invoices plus customer advances not yet allocated to an invoice.")

    @api.depends("amount_total",
                 "invoice_ids.state", "invoice_ids.move_type",
                 "invoice_ids.amount_total", "invoice_ids.amount_residual",
                 "invoice_ids.payment_state",
                 "advance_payment_ids.amount",
                 "advance_payment_ids.move_line_id.amount_residual")
    def _compute_paid_amount(self):
        """Total money received against the order, without double counting.

        - Invoice payments: posted invoices' (total - residual), refunds reduce.
          Once an advance is reconciled to an invoice (by either flow), it has
          already lowered that invoice's residual, so it is counted here.
        - Unallocated advances: the still-open residual of each advance's
          receivable credit line, i.e. cash received but not yet applied to any
          invoice. Reading the residual (not our status flag) keeps this correct
          whether the advance was applied via our button or the native flow.
        """
        for order in self:
            invoice_paid = 0.0
            for invoice in order.invoice_ids.filtered(
                    lambda m: m.state == "posted"):
                if invoice.move_type == "out_invoice":
                    invoice_paid += invoice.amount_total - invoice.amount_residual
                elif invoice.move_type == "out_refund":
                    invoice_paid -= invoice.amount_total - invoice.amount_residual
            advance_unallocated = 0.0
            for adv in order.advance_payment_ids:
                if adv.move_line_id:
                    advance_unallocated += abs(adv.move_line_id.amount_residual)
            order.paid_amount = invoice_paid + advance_unallocated

    @api.depends("amount_total", "paid_amount")
    def _compute_balance_amount(self):
        """Override of payment_status_in_sale: the balance now nets off both
        invoice payments and unallocated customer advances (via paid_amount)."""
        for order in self:
            order.balance_amount = order.amount_total - order.paid_amount

    @api.depends("amount_total", "advance_payment_ids.amount",
                 "advance_payment_ids.move_line_id.amount_residual")
    def _compute_advance_amounts(self):
        for order in self:
            advances = order.advance_payment_ids
            received = sum(advances.mapped("amount"))
            # Allocated = the reconciled portion of each advance (amount minus
            # the still-open residual of its receivable credit line).
            allocated = 0.0
            for adv in advances:
                if adv.move_line_id:
                    allocated += adv.amount - abs(adv.move_line_id.amount_residual)
            order.amount_advance_received = received
            order.amount_advance_allocated = allocated
            order.amount_advance_remaining = order.amount_total - received
            order.advance_payment_count = len(advances)

    def action_view_advances(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Advances"),
            "res_model": "sale.advance.payment",
            "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"create": False},
        }

    def action_allocate_advances_to_invoice(self):
        """Allocate this order's received advances to its open customer
        invoice(s) using Odoo's native outstanding-credit reconciliation.

        For each received advance, reconcile its receivable credit line against
        the order's posted, not-fully-paid customer invoices (oldest first),
        capped at each invoice's residual. Standard reconciliation is used as-is.
        """
        self.ensure_one()
        advances = self.advance_payment_ids.filtered(
            lambda a: a.move_line_id and not a.move_line_id.reconciled)
        if not advances:
            raise UserError(_("There are no unallocated advances to allocate."))
        invoices = self.invoice_ids.filtered(
            lambda m: m.move_type == "out_invoice" and m.state == "posted"
            and m.payment_state not in ("paid", "in_payment", "reversed"))
        if not invoices:
            raise UserError(_(
                "There is no open posted customer invoice on this order to "
                "allocate the advances to. Create and post the invoice first."))
        invoices = invoices.sorted(key=lambda m: (m.invoice_date or m.date, m.id))
        for advance in advances:
            for invoice in invoices:
                if advance.move_line_id.reconciled:
                    break
                if invoice.amount_residual <= 0:
                    continue
                # Native allocation: reconcile the advance's receivable credit
                # line with the invoice's receivable debit line. The advance's
                # `state` recomputes from the reconciliation automatically.
                invoice.js_assign_outstanding_line(advance.move_line_id.id)
        return True
