"""Contract PF shows the amount the payslip deducts under the 25,000 gross ceiling.

Payslips use 12% of gross up to 25,000 from September 2026, but Apply to Payroll
kept writing 12% of basic up to 15,000 (1,800) on the contract, which is what the
Salary tab, CTC breakup and CTC Excel show. Rewrite it on every contract version
in force today or later.
"""
from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
    today = fields.Date.context_today(env['hr.version'])
    versions = env['hr.version'].with_context(active_test=False).search([('greythr_ctc_id', '!=', False)])
    for v in versions:
        later = v.employee_id.version_ids.filtered(lambda o: o.date_version > v.date_version)
        if later and min(later.mapped('date_version')) <= today:
            continue  # superseded before today: its payslips are done, leave it as it was
        v.greythr_ctc_id._greythr_write_contract_pf(v)
