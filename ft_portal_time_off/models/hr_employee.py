# -*- coding: utf-8 -*-
from odoo import Command, api, models
from odoo.exceptions import AccessError, RedirectWarning
from odoo.tools import email_normalize


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

    # ------------------------------------------------------------------
    # Portal logins
    # ------------------------------------------------------------------
    def action_ft_create_portal_users_confirmation(self):
        raise RedirectWarning(
            message=self.env._(
                "%s employees will get a portal login on their work email and an invitation email "
                "to set their password. Do you wish to continue?", len(self)),
            action=self.env.ref('ft_portal_time_off.action_hr_employee_create_portal_users').id,
            button_text=self.env._('Confirm'),
            additional_context={'selected_ids': self.ids},
        )

    def action_ft_create_portal_users(self):
        """Give each employee a portal login on their work email, linked to the
        employee, with Odoo's portal invitation to set the password."""
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(self.env._("Only users who manage access rights can create portal users."))
        _ = self.env._
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        invited, linked, skipped, has_user = [], [], [], 0
        for employee in self.sudo():
            email = email_normalize(employee.work_email)
            partner = employee.work_contact_id
            user = partner.with_context(active_test=False).user_ids[:1]
            if employee.user_id:
                has_user += 1
            elif not email or not partner:
                skipped.append(_("%s has no work email", employee.name))
            elif Users.search_count([('login', '=', email), ('partner_id', '!=', partner.id)]):
                skipped.append(_("%(employee)s: %(email)s is already another user's login",
                                 employee=employee.name, email=email))
            elif user and user._is_internal():
                skipped.append(_("%s already has a back-office user; set it as Related User", employee.name))
            elif user and user.active and user._is_portal():
                user._ft_link_employees()
                linked.append(employee.name)
            else:
                wizard = self.env['portal.wizard'].sudo().create({'partner_ids': [Command.set(partner.ids)]})
                wizard.user_ids.email = email
                wizard.user_ids.action_grant_access()
                invited.append(employee.name)

        lines = []
        if invited:
            lines.append(_("Invited: %s", ", ".join(invited)))
        if linked:
            lines.append(_("Already had portal access, now linked: %s", ", ".join(linked)))
        if skipped:
            lines.append(_("Skipped: %s", "; ".join(skipped)))
        if has_user:
            lines.append(_("%s already had a user", has_user))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Portal Users"),
                'type': 'warning' if skipped else 'success',
                'sticky': bool(skipped),
                'message': " | ".join(lines),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
