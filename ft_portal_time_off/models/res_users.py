# -*- coding: utf-8 -*-
from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._ft_link_employees()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals and not self.env.context.get('ft_active_sync'):
            self._ft_sync_employees_active()
        return res

    def _ft_sync_employees_active(self):
        """Archiving or restoring a portal login does the same to its employee,
        the way HR's Archive / Restore buttons would (no departure window)."""
        Employee = self.env['hr.employee'].sudo().with_context(
            active_test=False, ft_active_sync=True, no_wizard=True)
        for user in self.sudo():
            if not user._is_portal():
                continue
            employees = Employee.search([('user_id', '=', user.id), ('active', '!=', user.active)])
            if user.active:
                employees.action_unarchive()
            else:
                employees.action_archive()

    def _ft_link_employees(self):
        """Make each portal user the Related User of the employee whose work
        contact they log in as, so the employee portal knows who they are.

        Access granted from Contacts (or Settings > Users) creates the user on
        the work contact but leaves the employee without a user. Back-office
        users are left alone; they are linked on the employee by hand.
        """
        Employee = self.env['hr.employee'].sudo()
        for user in self.sudo():
            if not user.active or not user._is_portal() \
                    or Employee.with_context(active_test=False).search_count([('user_id', '=', user.id)]):
                continue
            employee = Employee.search([('work_contact_id', '=', user.partner_id.id), ('user_id', '=', False)])
            if len(employee) == 1:
                employee.user_id = user
