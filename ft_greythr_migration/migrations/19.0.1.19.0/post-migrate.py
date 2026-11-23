"""Pay-run "employer cost" = cost to company (CTC_TOTAL), no longer net pay.

greytHR history payslips get the new CTC_TOTAL line; every payslip of the two
greytHR structures then has employer_cost refreshed from the rules now counted.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    structures = [env.ref(x, raise_if_not_found=False) for x in (
        'ft_greythr_migration.greythr_history_structure', 'ft_greythr_migration.greythr_structure')]
    structures = [s.id for s in structures if s]
    slips = env['hr.payslip'].with_context(active_test=False).search([('struct_id', 'in', structures)])
    slips._ft_backfill_employer_cost()
