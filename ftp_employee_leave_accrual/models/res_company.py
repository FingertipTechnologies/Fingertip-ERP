# -*- coding: utf-8 -*-
"""The policy lives on the company, so a multi-company database keeps its
leave types, plans and eligibility separate per company."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    ftp_leave_accrual_enabled = fields.Boolean(
        string='Enable Automatic Leave Allocation', default=True,
        help="When off, no allocation is created automatically. Existing "
             "allocations and balances are untouched.")
    ftp_casual_leave_type_id = fields.Many2one(
        'hr.leave.type', string='Casual Leave Time Off Type',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]")
    ftp_sick_leave_type_id = fields.Many2one(
        'hr.leave.type', string='Sick Leave Time Off Type',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]")
    ftp_casual_accrual_plan_id = fields.Many2one(
        'hr.leave.accrual.plan', string='Casual Leave Accrual Plan',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]")
    ftp_sick_accrual_plan_id = fields.Many2one(
        'hr.leave.accrual.plan', string='Sick Leave Accrual Plan',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]")
    # Reuses the existing status field rather than adding a second one: the
    # contract type is what already carries Probation, Intern and the rest.
    ftp_eligible_contract_type_ids = fields.Many2many(
        'hr.contract.type', 'ftp_company_eligible_contract_type_rel',
        'company_id', 'contract_type_id', string='Eligible Employee Status',
        help="Only employees whose Contract Type is one of these get the "
             "monthly accrual. Leave Probation, Intern and Consultant out.")
    ftp_casual_monthly_accrual = fields.Float(
        string='Casual Leave Monthly Accrual', default=1.0)
    ftp_sick_monthly_accrual = fields.Float(
        string='Sick Leave Monthly Accrual', default=0.5)
    ftp_casual_max_carryover = fields.Float(
        string='Casual Leave Maximum Carry Forward', default=10.0,
        help="Maximum casual leave days carried past 1 April. Company policy "
             "is 10. Zero means no cap. Sick leave never carries over.")

    # --- Maternity and paternity: granted on the event, not accrued ---
    ftp_maternity_leave_type_id = fields.Many2one(
        'hr.leave.type', string='Maternity Leave Time Off Type',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]")
    ftp_paternity_leave_type_id = fields.Many2one(
        'hr.leave.type', string='Paternity Leave Time Off Type',
        domain="['|', ('company_id', '=', False), ('company_id', '=', id)]")
    ftp_parental_min_service_years = fields.Integer(
        string='Maternity & Paternity Minimum Service (Years)', default=2,
        help="Years of service before maternity OR paternity leave may be "
             "taken. Applies to both. Zero switches the check off.")
    ftp_maternity_days = fields.Float(
        string='Maternity Leave Maximum (Calendar Days)', default=180.0,
        help="Longest maternity leave that may be requested, measured in "
             "calendar days. 180 is the six months in the policy. Zero "
             "switches the limit off.")
    ftp_paternity_days = fields.Float(
        string='Paternity Leave Maximum (Calendar Days)', default=3.0,
        help="Longest paternity leave that may be requested, measured in "
             "calendar days. Zero switches the limit off.")
