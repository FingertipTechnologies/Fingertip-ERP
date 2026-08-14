# -*- coding: utf-8 -*-
"""Clear stored ProForma balances on cancelled Sales Orders."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env["sale.order"].search([("state", "=", "cancel")])
    if orders:
        env.add_to_compute(env["sale.order"]._fields["balance_amount"], orders)
        orders._recompute_recordset(["balance_amount"])
