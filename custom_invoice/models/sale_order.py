from odoo import models, fields, api
from datetime import datetime

DEFAULT_BANK_NOTE = """<p><b>Please transfer to below Bank Details</b><br/>
Bank Name : <b>HDFC Bank Ltd</b><br/>
HDFC Bank Current a/c No : <b>50200018112854</b><br/>
Beneficiary Name : <b>FINGERTIPPLUS TECHNOLOGIES PVT LTD</b><br/>
Bank IFSC Code : <b>HDFC0001208</b><br/>
Bank Address : 70/2, Millers Boulevard, Millers Road, Bangalore-560052<br/>
Branch and Branch Code : Millers Road Branch and 1208<br/>
Bank State / Province : Karnataka, India</p>"""


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    note = fields.Html(
        string="Terms and conditions",
        compute='_compute_note',
        store=True, readonly=True, precompute=True)

    invoice_cash_rounding_id = fields.Many2one(
        'account.cash.rounding',
        string="Cash Rounding",
        default=lambda self: self.env.ref(
            'custom_invoice.cash_rounding_round_off', raise_if_not_found=False),
        help="If set, the order total is rounded to this precision (nearest "
             "rupee). The same rounding is carried over to the invoice.")

    @api.depends('partner_id')
    def _compute_note(self):
        for order in self:
            order.note = DEFAULT_BANK_NOTE

    @api.depends('order_line.price_subtotal', 'currency_id', 'company_id',
                 'payment_term_id', 'invoice_cash_rounding_id')
    def _compute_amounts(self):
        """Same computation as the base sale order, but passing the order's
        cash rounding to the tax engine so the stored total is rounded to the
        nearest rupee while keeping untaxed + tax = total consistent."""
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order._get_priced_lines()
            base_lines = [line._prepare_base_line_for_taxes_computation()
                          for line in order_lines]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
                cash_rounding=order.invoice_cash_rounding_id or None,
            )
            order.amount_untaxed = tax_totals['base_amount_currency']
            order.amount_tax = tax_totals['tax_amount_currency']
            order.amount_total = tax_totals['total_amount_currency']

    @api.depends_context('lang')
    @api.depends('order_line.price_subtotal', 'currency_id', 'company_id',
                 'payment_term_id', 'invoice_cash_rounding_id')
    def _compute_tax_totals(self):
        """Feed the same cash rounding into the tax-totals breakdown widget so
        the form's tax summary matches the rounded header total."""
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order._get_priced_lines()
            base_lines = [line._prepare_base_line_for_taxes_computation()
                          for line in order_lines]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            order.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
                cash_rounding=order.invoice_cash_rounding_id or None,
            )

    def _prepare_invoice(self):
        """Carry the order's cash rounding onto the invoice so both documents
        round identically."""
        values = super()._prepare_invoice()
        values['invoice_cash_rounding_id'] = self.invoice_cash_rounding_id.id
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                now = datetime.now()

                year = now.year % 100
                next_year = (now.year + 1) % 100

                prefix = f"FTPPL/PI/{year:02d}-{next_year:02d}/"

                seq = self.env['ir.sequence'].next_by_code('sale.order') or '001'

                vals['name'] = prefix + seq

        return super().create(vals_list)
