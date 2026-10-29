# -*- coding: utf-8 -*-
from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._ft_link_employees()
        return users

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
