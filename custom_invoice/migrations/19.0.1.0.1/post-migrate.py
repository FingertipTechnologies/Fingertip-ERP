# -*- coding: utf-8 -*-
"""Apply nearest-rupee cash rounding to existing DRAFT customer invoices.

Posted invoices are intentionally excluded: they are locked, reconciled and
already reported (GST), so re-rounding them would break accounting. Writing
invoice_cash_rounding_id on a draft move triggers account.move's line sync
(_sync_rounding_lines), which recomputes the rounding line and totals.
"""
from odoo import api, SUPERUSER_ID

CUSTOMER_MOVE_TYPES = ('out_invoice', 'out_refund', 'out_receipt')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rounding = env.ref('custom_invoice.cash_rounding_round_off',
                       raise_if_not_found=False)
    if not rounding:
        return
    drafts = env['account.move'].search([
        ('state', '=', 'draft'),
        ('move_type', 'in', CUSTOMER_MOVE_TYPES),
        ('invoice_cash_rounding_id', '=', False),
    ])
    if drafts:
        # Write per-record so a single bad move can't abort the whole batch.
        for move in drafts:
            move.invoice_cash_rounding_id = rounding

    # Recompute stored sale-order totals so existing orders reflect the new
    # nearest-rupee rounding. The new invoice_cash_rounding_id field gets its
    # default on existing rows automatically, but amount_* are stored and are
    # not recomputed just because the compute logic changed, so force it here.
    orders = env['sale.order'].search([])
    if orders:
        for fname in ('amount_untaxed', 'amount_tax', 'amount_total'):
            env.add_to_compute(env['sale.order']._fields[fname], orders)
        orders._recompute_recordset(['amount_untaxed', 'amount_tax',
                                     'amount_total'])
