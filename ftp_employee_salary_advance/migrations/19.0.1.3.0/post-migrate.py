# -*- coding: utf-8 -*-
"""Give installments settled by hand their own status.

Ticking Already Paid used to leave the line's status at Pending. The balance
was right, but the Status column read "Pending" next to a lit-up toggle, which
looks like the money is still owed. Those rows are corrected here.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    stale = env['hr.salary.advance.installment'].search([
        ('already_paid', '=', True),
        ('state', '=', 'pending'),
    ])
    if stale:
        stale.write({'state': 'paid'})
