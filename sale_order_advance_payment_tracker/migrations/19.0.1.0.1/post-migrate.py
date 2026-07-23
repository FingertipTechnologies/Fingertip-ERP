# -*- coding: utf-8 -*-
"""Recompute stored paid_amount / balance_amount on existing sale orders.

balance_amount is a pre-existing stored field (from payment_status_in_sale);
changing its compute to also net off advances does not auto-recompute existing
rows, so force it here. paid_amount is new and gets computed on install, but we
recompute it too for consistency.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env["sale.order"].search([])
    if not orders:
        return
    fields_to_recompute = ["paid_amount", "balance_amount"]
    for fname in fields_to_recompute:
        env.add_to_compute(env["sale.order"]._fields[fname], orders)
    orders._recompute_recordset(fields_to_recompute)
