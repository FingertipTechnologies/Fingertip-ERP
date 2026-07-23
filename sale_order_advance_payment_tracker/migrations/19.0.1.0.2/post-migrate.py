# -*- coding: utf-8 -*-
"""Recompute advance/paid/balance figures with the residual-based logic.

`sale.advance.payment.state` became a computed field driven by the receivable
line's reconciliation, and the sale-order paid/balance/allocated figures now
read that residual instead of the old status flag. Force a recompute so existing
records reflect advances that were applied through the native invoice flow.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    advances = env["sale.advance.payment"].search([])
    if advances:
        env.add_to_compute(
            env["sale.advance.payment"]._fields["state"], advances)
        advances._recompute_recordset(["state"])

    orders = env["sale.order"].search([])
    if orders:
        fnames = [
            "amount_advance_received", "amount_advance_allocated",
            "amount_advance_remaining", "paid_amount", "balance_amount",
        ]
        for fname in fnames:
            env.add_to_compute(env["sale.order"]._fields[fname], orders)
        orders._recompute_recordset(fnames)
