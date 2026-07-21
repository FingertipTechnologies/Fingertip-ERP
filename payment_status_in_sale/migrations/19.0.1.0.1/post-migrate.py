# -*- coding: utf-8 -*-
"""Recompute the stored `balance_amount` on existing sale orders.

A stored computed field is not automatically recomputed on upgrade when only
its compute logic/depends change (Odoo only recomputes newly added stored
fields). The balance_amount logic changed from the manual payment lines to the
actual posted-invoice payments, so existing records keep stale values until we
force a recompute here.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].search([])
    if orders:
        env.add_to_compute(env['sale.order']._fields['balance_amount'], orders)
        orders._recompute_recordset(['balance_amount'])
