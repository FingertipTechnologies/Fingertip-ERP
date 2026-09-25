# -*- coding: utf-8 -*-
"""Draw up schedules for advances entered before they were generated on save.

Until this version the schedule was only created on approval, so an advance
sitting in Draft or Submitted had an empty Installment Schedule tab. Those
records are filled in here. Advances that already have lines are left alone,
and _generate_installments protects anything deducted or settled anyway.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    advances = env['hr.salary.advance'].search([
        ('state', 'in', ('draft', 'submitted', 'approved', 'running')),
        ('installment_ids', '=', False),
        ('advance_amount', '>', 0),
        ('monthly_installment', '>', 0),
    ])
    if advances:
        advances._generate_installments()
