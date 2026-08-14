# -*- coding: utf-8 -*-
"""Recompute `balance_amount` after it switched to invoicing.

The balance is now the part of the order that has not been invoiced yet, so it
drops when an invoice is confirmed instead of when it is paid. Stored values
are forced to recompute since Odoo leaves them untouched when only the compute
logic changes.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].search([])
    if orders:
        env.add_to_compute(env['sale.order']._fields['balance_amount'], orders)
        orders._recompute_recordset(['balance_amount'])
