# -*- coding: utf-8 -*-
from odoo import api, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Time Off makes the manager's user the employee's Time Off approver and
    # adds it to an internal group. A portal user cannot join that group, so
    # creating or editing an employee whose manager logs in on the portal
    # would fail. Portal managers approve on the portal through the Manager
    # field instead, so they are never set as the back-office approver.

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('parent_id') and 'leave_manager_id' not in vals \
                    and self.browse(vals['parent_id']).sudo().user_id.share:
                vals['leave_manager_id'] = False
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('leave_manager_id') and self.env['res.users'].browse(vals['leave_manager_id']).sudo().share:
            vals = dict(vals, leave_manager_id=False)
        return super().write(vals)

    def _compute_leave_manager(self):
        super()._compute_leave_manager()
        for employee in self:
            if employee.leave_manager_id.sudo().share:
                employee.leave_manager_id = False
