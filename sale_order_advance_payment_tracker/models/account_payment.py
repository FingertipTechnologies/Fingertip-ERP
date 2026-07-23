# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    sale_advance_payment_ids = fields.One2many(
        "sale.advance.payment", "payment_id",
        string="Sale Order Advances",
        help="Sale Order advance allocations backed by this payment.")
