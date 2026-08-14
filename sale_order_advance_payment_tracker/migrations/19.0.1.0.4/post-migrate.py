# -*- coding: utf-8 -*-
"""Recompute `balance_amount` after it switched to invoicing.

The balance is now the order total minus what has been invoiced and minus the
advances not allocated to an invoice yet, so it drops when an invoice is
confirmed rather than when it is paid. `paid_amount` keeps its meaning (cash
actually received) but is recomputed too, as both share the same helpers.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env["sale.order"].search([])
    if orders:
        fnames = ["paid_amount", "balance_amount"]
        for fname in fnames:
            env.add_to_compute(env["sale.order"]._fields[fname], orders)
        orders._recompute_recordset(fnames)
