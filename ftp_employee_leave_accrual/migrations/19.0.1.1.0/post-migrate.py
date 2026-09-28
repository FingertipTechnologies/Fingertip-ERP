# -*- coding: utf-8 -*-
"""Apply HR's clarifications to databases already running the policy.

Two things moved: casual carry-forward is capped at 10 days a year rather than
unlimited, and maternity/paternity leave now exist with a two-year service
rule. Companies that had deliberately set their own cap are left alone.
"""
from odoo import api, SUPERUSER_ID

from odoo.addons.ftp_employee_leave_accrual.models.leave_policy_setup import (
    setup_leave_policy,
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        # 0.0 was the old default, meaning "no cap"; take it as unset.
        if not company.ftp_casual_max_carryover:
            company.ftp_casual_max_carryover = 10.0
        # Creates the parental types and re-applies the cap to the plan.
        setup_leave_policy(env, company)
