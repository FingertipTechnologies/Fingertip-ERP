# -*- coding: utf-8 -*-
"""Recompute paid/balance figures after the shared-invoice fix.

An invoice billing several sale orders used to add its full payment to each of
them, inflating `paid_amount` and pushing `balance_amount` negative. Both now
count only this order's share of the invoice, so existing stored values must be
forced to recompute.
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
