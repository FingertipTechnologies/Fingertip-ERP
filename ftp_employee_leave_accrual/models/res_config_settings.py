# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .leave_policy_setup import setup_leave_policy


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ftp_leave_accrual_enabled = fields.Boolean(
        related='company_id.ftp_leave_accrual_enabled', readonly=False)
    ftp_casual_leave_type_id = fields.Many2one(
        related='company_id.ftp_casual_leave_type_id', readonly=False)
    ftp_sick_leave_type_id = fields.Many2one(
        related='company_id.ftp_sick_leave_type_id', readonly=False)
    ftp_casual_accrual_plan_id = fields.Many2one(
        related='company_id.ftp_casual_accrual_plan_id', readonly=False)
    ftp_sick_accrual_plan_id = fields.Many2one(
        related='company_id.ftp_sick_accrual_plan_id', readonly=False)
    ftp_eligible_contract_type_ids = fields.Many2many(
        related='company_id.ftp_eligible_contract_type_ids', readonly=False)
    ftp_casual_monthly_accrual = fields.Float(
        related='company_id.ftp_casual_monthly_accrual', readonly=False)
    ftp_sick_monthly_accrual = fields.Float(
        related='company_id.ftp_sick_monthly_accrual', readonly=False)
    ftp_casual_max_carryover = fields.Float(
        related='company_id.ftp_casual_max_carryover', readonly=False)
    ftp_maternity_leave_type_id = fields.Many2one(
        related='company_id.ftp_maternity_leave_type_id', readonly=False)
    ftp_paternity_leave_type_id = fields.Many2one(
        related='company_id.ftp_paternity_leave_type_id', readonly=False)
    ftp_parental_min_service_years = fields.Integer(
        related='company_id.ftp_parental_min_service_years', readonly=False)
    ftp_maternity_days = fields.Float(
        related='company_id.ftp_maternity_days', readonly=False)
    ftp_paternity_days = fields.Float(
        related='company_id.ftp_paternity_days', readonly=False)

    def action_setup_leave_policy(self):
        """Build anything missing and point the settings at it."""
        self.ensure_one()
        setup_leave_policy(self.env, self.company_id)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_generate_missing_allocations(self):
        self.ensure_one()
        created = self.env['hr.employee']._cron_ensure_leave_allocations()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': self.env._(
                    "%(count)s missing leave allocation(s) created.",
                    count=created),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
