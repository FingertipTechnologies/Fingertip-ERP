# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Technologies (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from odoo import api, fields, models, _
import json


class SaleOrder(models.Model):
    """ Extend the base Sale Order model to add custom fields and behaviors
    for Sale Order Payment Status. """
    _inherit = "sale.order"
    _description = 'Sale order'

    payment_status = fields.Char(string="Payment Status",
                                 compute="_compute_payment_status",
                                 help="Field to check the payment status of the"
                                      " sale order")
    payment_details = fields.Binary(string="Payment Details",
                                    compute="_compute_payment_details",
                                    help="Shows the payment done details "
                                         "including date and amount")
    amount_due = fields.Float(string="Amount Due",
                              compute='_compute_amount_due',
                              help="Shows the amount that in due for the "
                                   "corresponding sale order")
    invoice_state = fields.Char(string="Invoice State",
                                compute="_compute_invoice_state",
                                help="Field to check the invoice state of "
                                     "sale order")
    project_status = fields.Many2one('project.project.stage', string="Project Status")
    payment_ids = fields.One2many('sale.payment', 'sale_id', string="Payments")

    total_payment = fields.Monetary(
        string="Total Payment",
        compute='_compute_total_payment',
        store=True
    )

    balance_amount = fields.Monetary(
        string="Balance Amount",
        compute='_compute_balance_amount',
        store=True
    )

    @api.depends('payment_ids.amount')
    def _compute_total_payment(self):
        for order in self:
            order.total_payment = sum(order.payment_ids.mapped('amount'))

    def _get_invoice_share(self, invoice):
        """This order's signed (invoiced, paid) share of `invoice`.

        A single invoice may bill several sale orders at once. Counting the
        whole invoice on each of them makes every order report the combined
        amount, so the invoice is split by the lines that come from this
        order: share = this order's lines / all the invoice's product lines.
        Credit notes are returned negative so callers can just add them up.
        """
        self.ensure_one()
        lines = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product')
        invoice_lines_total = sum(lines.mapped('price_total'))
        if not invoice_lines_total:
            return 0.0, 0.0
        order_share = 0.0
        for line in lines:
            orders = line.sale_line_ids.order_id
            if self in orders:
                # A line billing several orders (rare) is split evenly rather
                # than claimed in full by each of them.
                order_share += line.price_total / len(orders)
        ratio = order_share / invoice_lines_total
        sign = -1 if invoice.move_type == 'out_refund' else 1
        paid = invoice.amount_total - invoice.amount_residual
        return sign * invoice.amount_total * ratio, sign * paid * ratio

    def _get_invoiced_and_paid(self):
        """Signed (invoiced, paid) totals over this order's posted invoices,
        each one limited to the part that belongs to this order."""
        self.ensure_one()
        invoiced = paid = 0.0
        for invoice in self.invoice_ids.filtered(
                lambda m: m.state == 'posted'
                and m.move_type in ('out_invoice', 'out_refund')):
            invoice_share, paid_share = self._get_invoice_share(invoice)
            invoiced += invoice_share
            paid += paid_share
        return invoiced, paid

    @api.depends('amount_total', 'invoice_ids.state', 'invoice_ids.move_type',
                 'invoice_ids.amount_total', 'invoice_ids.amount_residual',
                 'invoice_ids.payment_state',
                 'invoice_ids.invoice_line_ids.price_total',
                 'invoice_ids.invoice_line_ids.sale_line_ids')
    def _compute_balance_amount(self):
        """Balance left on the order = order total minus what has already been
        invoiced to the customer (credit notes give the amount back).

        The balance drops as soon as an invoice is confirmed, not when it is
        paid: confirming the invoice is what commits that part of the order.
        How much of the invoiced amount is still unpaid is `amount_due`, and
        the cash actually received is `paid_amount`."""
        for order in self:
            order.balance_amount = order.amount_total - order._get_invoiced_and_paid()[0]


    @api.depends('invoice_ids')
    def _compute_payment_status(self):
        """ The function will compute the payment status of the sale order, if
        an invoice is created for the corresponding sale order.Payment status
        will be either in paid,not paid,partially paid, reversed etc. """
        for order in self:
            order.payment_status = 'No invoice'
            posted_invoices = order.invoice_ids.filtered(
                lambda x: x.state == 'posted')
            if not posted_invoices:
                order.payment_status = 'No invoice'
            else:
                payment_states = posted_invoices.mapped('payment_state')
                status_length = len(payment_states)
                if order.amount_due > 0:
                    if 'not_paid' in payment_states and status_length == payment_states.count('not_paid'):
                        order.payment_status = 'Not Paid'
                    elif 'partial' in payment_states or 'not_paid' in payment_states:
                        order.payment_status = 'Partially Paid'
                elif order.amount_due <= 0:  # Changed to <= 0 to handle overpayments or credit notes
                    if 'paid' in payment_states and status_length == payment_states.count(
                            'paid'):
                        order.payment_status = 'Paid'
                    elif 'in_payment' in payment_states and status_length == payment_states.count(
                            'in_payment'):
                        order.payment_status = 'In Payment'
                elif 'reversed' in payment_states and status_length == payment_states.count(
                        'reversed'):
                    order.payment_status = 'Reversed'

    @api.depends('invoice_ids')
    def _compute_invoice_state(self):
        """ The function will compute the state of the invoice , Once an invoice
        is existing in a sale order. """
        for rec in self:
            rec.invoice_state = 'No invoice'
            for order in rec.invoice_ids:
                if order.state == 'posted':
                    rec.invoice_state = 'posted'
                elif order.state != 'posted':
                    rec.invoice_state = 'draft'
                else:
                    rec.invoice_state = 'No invoice'

    @api.depends('invoice_ids')
    def _compute_amount_due(self):
        """The function is used to compute the amount due from the invoice and
        if payment is registered, accounting for exchange rate differences and
        credit notes. Only this order's share of each invoice counts, so an
        invoice covering several orders is not due in full on each of them."""
        for rec in self:
            total_invoiced, total_paid = rec._get_invoiced_and_paid()
            rec.amount_due = total_invoiced - total_paid

    def action_open_business_doc(self):
        """ This method is intended to be used in the context of an
        account.move record.
        It retrieves the associated payment record and opens it in a new window.

        :return: A dictionary describing the action to be performed.
        :rtype: dict """
        name = _("Journal Entry")
        move = self.env['account.move'].browse(self.id)
        res_model = 'account.payment'
        payments = move.payment_ids
        res_id = payments.id
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_model': res_model,
            'res_id': res_id,
            'target': 'current',
        }

    def js_remove_outstanding_partial(self, partial_id):
        """ Called by the 'payment' widget to remove a reconciled entry to the
        present invoice.

        :param partial_id: The id of an existing partial reconciled with the
        current invoice.
        """
        self.ensure_one()
        partial = self.env['account.partial.reconcile'].browse(partial_id)
        return partial.unlink()

    @api.depends('invoice_ids')
    def _compute_payment_details(self):
        """ Compute the payment details from invoices and added into the sale
        order form view. """
        for rec in self:
            payment = []
            rec.payment_details = False
            if rec.invoice_ids:
                for line in rec.invoice_ids:
                    if line.invoice_payments_widget:
                        for pay in line.invoice_payments_widget['content']:
                            payment.append(pay)
                for line in rec.invoice_ids:
                    if line.invoice_payments_widget:
                        payment_line = line.invoice_payments_widget
                        payment_line['content'] = payment
                        rec.payment_details = payment_line
                        break
                    rec.payment_details = False

    def action_register_payment(self):
        """ Open the account.payment.register wizard to pay the selected journal
         entries.
        :return: An action opening the account.payment.register wizard.
        """
        self.ensure_one()
        return {
            'name': _('Register Payment'),
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'context': {
                'active_model': 'account.move',
                'active_ids': self.invoice_ids.ids,
            },
            'target': 'new',
            'type': 'ir.actions.act_window',
        }

class SalePayment(models.Model):
    _name = 'sale.payment'
    _description = 'Sale Payment'

    sale_id = fields.Many2one('sale.order', string="Sale Order", ondelete='cascade')
    date = fields.Date(string="Date", related='payment_id.date')

    payment_id = fields.Many2one('account.payment', string="Payment")
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company, store=True)
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        related='company_id.currency_id',
        store=True
    )
    amount = fields.Monetary(string="Amount",related='payment_id.amount')
    payment_domain = fields.Char(
        compute="_compute_payment_domain",
        readonly=True,
        store=False,
    )

    @api.depends('sale_id')
    def _compute_payment_domain(self):
        for rec in self:
            if rec.sale_id and rec.sale_id.partner_id:
                rec.payment_domain = json.dumps([
                    ('partner_id', '=', rec.sale_id.partner_id.id)
                ])
            else:
                rec.payment_domain = json.dumps([])

