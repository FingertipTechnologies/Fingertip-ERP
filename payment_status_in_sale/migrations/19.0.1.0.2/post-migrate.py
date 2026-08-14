# -*- coding: utf-8 -*-
"""Recompute the stored `balance_amount` after the shared-invoice fix.

An invoice billing several sale orders used to be counted in full on each of
them, so every order reported the combined paid amount and a wrong (often
negative) balance. The compute now takes only this order's share of such an
invoice; stored values need forcing since Odoo does not recompute a stored
field when only its logic changes.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].search([])
    if orders:
        env.add_to_compute(env['sale.order']._fields['balance_amount'], orders)
        orders._recompute_recordset(['balance_amount'])
