# -*- coding: utf-8 -*-
"""Carry the children education allowance onto its new salary-component field.

The amount used to be read straight off the applied greytHR CTC, as one of the
EXTRA_EARNINGS. It now lives on hr.version like the other salary components, so
anyone with an applied CTC has the value copied across here. Without this the
allowance would silently drop to zero on the next payslip.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    versions = env['hr.version'].sudo().search([('greythr_ctc_id', '!=', False)])
    touched = env['hr.version'].sudo()
    for record in versions:
        amount = record.greythr_ctc_id.full_children_education_allowance
        if amount:
            record.ft_children_education_allowance = amount
            touched |= record
    # The stored gross used to pick this up through the CTC extras and now picks
    # it up from the field, so force it for the records that carry a value.
    if touched:
        field = env['hr.version']._fields['l10n_in_gross_salary']
        env.add_to_compute(field, touched)
        touched._recompute_recordset(['l10n_in_gross_salary'])
