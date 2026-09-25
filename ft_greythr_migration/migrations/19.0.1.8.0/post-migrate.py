# -*- coding: utf-8 -*-
"""Fill in the confirmation date for employees already on probation.

trial_date_end is a stored field that existed before this version, so adding
a compute to it does not make Odoo recompute the rows that are already there
-- a stored value is only computed on rows where the column is new. Employees
sitting on probation today would keep an empty date and never be picked up by
the cron, so the compute is forced here for exactly those rows.
"""
from odoo import api, SUPERUSER_ID

PROBATION_TYPE = 'l10n_in_hr_payroll.l10n_in_contract_type_probation'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    probation = env.ref(PROBATION_TYPE, raise_if_not_found=False)
    if not probation:
        return
    versions = env['hr.version'].sudo().search([
        ('contract_type_id', '=', probation.id),
        ('trial_date_end', '=', False),
        ('contract_date_start', '!=', False),
    ])
    if versions:
        field = env['hr.version']._fields['trial_date_end']
        env.add_to_compute(field, versions)
        versions._recompute_recordset(['trial_date_end'])
