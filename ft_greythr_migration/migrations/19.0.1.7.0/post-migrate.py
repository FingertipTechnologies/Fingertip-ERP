# -*- coding: utf-8 -*-
"""Move IFSC codes out of the BIC field into the new dedicated one.

Until now there was no IFSC field, so Indian bank records kept the IFSC in
`res.bank.bic`. Anything already sitting in `bic` that has the shape of an
IFSC is copied across. Values that look like genuine SWIFT codes are left
alone, and `bic` is never cleared, so anything still reading it keeps working.
"""
import re

from odoo import api, SUPERUSER_ID

IFSC_PATTERN = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    banks = env['res.bank'].with_context(active_test=False).search([
        ('bic', '!=', False),
        ('ifsc_code', '=', False),
    ])
    for bank in banks:
        code = (bank.bic or '').strip().upper()
        # Only IFSC-shaped values are copied, so the constraint cannot trip
        # part-way through and abort the upgrade.
        if IFSC_PATTERN.match(code):
            bank.ifsc_code = code
