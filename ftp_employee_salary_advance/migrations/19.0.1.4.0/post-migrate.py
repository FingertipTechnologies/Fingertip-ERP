# -*- coding: utf-8 -*-
"""Attach the recovery rule to structures created after this module.

Until now only the structures that existed at install time got the rule, so
for example the greytHR structure reserved installments but never deducted them.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.payroll.structure'].with_context(active_test=False).search([])._ftp_add_salary_advance_rule()
