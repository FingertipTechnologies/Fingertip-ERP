from odoo import models, fields, api

DEFAULT_BANK_NOTE = """<p><b>Please transfer to below Bank Details</b><br/>
Bank Name : <b>HDFC Bank Ltd</b><br/>
HDFC Bank Current a/c No : <b>50200018112854</b><br/>
Beneficiary Name : <b>FINGERTIPPLUS TECHNOLOGIES PVT LTD</b><br/>
Bank IFSC Code : <b>HDFC0001208</b><br/>
Bank Address : 70/2, Millers Boulevard, Millers Road, Bangalore-560052<br/>
Branch and Branch Code : Millers Road Branch and 1208<br/>
Bank State / Province : Karnataka, India</p>"""


class AccountMove(models.Model):
    _inherit = 'account.move'

    narration = fields.Html(
        string="Terms and Conditions",
        compute='_compute_narration',
        store=True, readonly=True, precompute=True)

    total_hours = fields.Float(
        string="Total Hours",
        compute="_compute_total_hours",
        store=True
    )

    cgst_amount = fields.Monetary(
        string="CGST Amount",
        compute="_compute_gst_amounts",
        store=True
    )

    sgst_amount = fields.Monetary(
        string="SGST Amount",
        compute="_compute_gst_amounts",
        store=True
    )

    amount_in_words = fields.Char(
        string="Amount in Words",
        compute="_compute_amount_in_words"
    )

    # Customer-invoice move types that should be rounded to the nearest rupee.
    _CASH_ROUNDING_MOVE_TYPES = ('out_invoice', 'out_refund', 'out_receipt')

    @api.model
    def default_get(self, fields_list):
        """Default the cash rounding to 'Round Off (Nearest Rupee)' for new
        customer invoices/credit notes. This covers both manual creation and
        invoices generated from a sale order (which create the move with
        default_move_type='out_invoice' in context)."""
        res = super().default_get(fields_list)
        if 'invoice_cash_rounding_id' in fields_list and not res.get(
                'invoice_cash_rounding_id'):
            move_type = self.env.context.get('default_move_type')
            if (move_type in self._CASH_ROUNDING_MOVE_TYPES
                    and self.env.company.country_code == 'IN'):
                rounding = self.env.ref(
                    'custom_invoice.cash_rounding_round_off',
                    raise_if_not_found=False)
                if rounding:
                    res['invoice_cash_rounding_id'] = rounding.id
        return res

    @api.depends('company_id')
    def _compute_narration(self):
        for move in self:
            move.narration = DEFAULT_BANK_NOTE

    @api.depends('invoice_line_ids.hours')
    def _compute_total_hours(self):
        for move in self:
            move.total_hours = sum(move.invoice_line_ids.mapped('hours'))

    @api.depends('amount_untaxed', 'amount_tax')
    def _compute_gst_amounts(self):
        for move in self:
            # Assuming CGST + SGST split equally
            gst = move.amount_tax / 2
            move.cgst_amount = gst
            move.sgst_amount = gst

    
    @api.depends('amount_total', 'currency_id')
    def _compute_amount_in_words(self):
        for move in self:
            if move.currency_id:
                move.amount_in_words = (
                    move.currency_id.amount_to_text(move.amount_total)
                    + " Only"
                )
            else:
                move.amount_in_words = ""
