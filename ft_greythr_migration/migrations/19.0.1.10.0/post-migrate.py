# -*- coding: utf-8 -*-
"""Recompute the special allowance where the gross overshot the wage.

Only versions that actually carry one of the add-on components are touched, so
a hand-entered special allowance on an employee with no meal, phone, internet
or transport is left exactly as it is. The stored value is cleared first,
because l10n_in_fixed_allowance is a stored compute with readonly=False -- a
value somebody typed sticks until the field is forced to recompute.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    versions = env['hr.version'].sudo().search([
        ('greythr_ctc_id', '=', False),
        ('l10n_in_basic_salary_amount', '>', 0),
        '|', '|', '|',
        ('l10n_in_meal_voucher_amount', '>', 0),
        ('l10n_in_phone_subscription', '>', 0),
        ('l10n_in_internet_subscription', '>', 0),
        ('l10n_in_company_transport', '>', 0),
    ])
    if not versions:
        return
    fields_to_redo = ['l10n_in_fixed_allowance', 'l10n_in_gross_salary']
    for name in fields_to_redo:
        # Recompute in order: the gross is stored and depends on the residual,
        # and forcing only the residual leaves the gross showing the old total.
        env.add_to_compute(env['hr.version']._fields[name], versions)
        versions._recompute_recordset([name])
        versions.flush_recordset()
