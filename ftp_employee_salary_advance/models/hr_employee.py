# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    salary_advance_ids = fields.One2many(
        'hr.salary.advance', 'employee_id', string='Salary Advances',
        groups='hr.group_hr_user')
    salary_advance_count = fields.Integer(
        string='Salary Advance Count', compute='_compute_salary_advance_figures',
        groups='hr.group_hr_user')
    salary_advance_running_count = fields.Integer(
        string='Running Advances', compute='_compute_salary_advance_figures',
        groups='hr.group_hr_user')
    salary_advance_balance = fields.Monetary(
        string='Advance Balance', compute='_compute_salary_advance_figures',
        currency_field='currency_id', groups='hr.group_hr_user')

    @api.depends('salary_advance_ids.state', 'salary_advance_ids.remaining_amount')
    def _compute_salary_advance_figures(self):
        for employee in self:
            advances = employee.salary_advance_ids
            live = advances.filtered(lambda a: a.state in ('approved', 'running'))
            employee.salary_advance_count = len(advances)
            employee.salary_advance_running_count = len(live)
            employee.salary_advance_balance = sum(live.mapped('remaining_amount'))

    def action_open_salary_advances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salary Advances'),
            'res_model': 'hr.salary.advance',
            'view_mode': 'list,form,pivot',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
