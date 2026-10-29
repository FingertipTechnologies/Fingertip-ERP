# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.tools import formataddr

MAIL_TEMPLATES = {
    'request': 'ft_portal_time_off.mail_template_leave_request',
    'decided_employee': 'ft_portal_time_off.mail_template_leave_decided_employee',
    'decided_approvers': 'ft_portal_time_off.mail_template_leave_decided_approvers',
    'withdrawn': 'ft_portal_time_off.mail_template_leave_withdrawn',
}


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    ft_portal_refuse_reason = fields.Text(
        string='Reason for Refusal', readonly=True,
        help='Written by the manager or HR who refused it on the portal; the employee sees it there.')

    def message_post(self, **kwargs):
        # A decision on the portal sends its own email with the reason; Odoo's
        # "has been accepted/refused" message stays in the chatter only.
        if self.env.context.get('ft_portal_quiet'):
            kwargs.pop('partner_ids', None)
        return super().message_post(**kwargs)

    # ------------------------------------------------------------------
    # Portal emails
    # ------------------------------------------------------------------
    def _ft_approver_employees(self):
        """Who is told about this request: the employee's manager and the HR
        for Time Off; with no manager, the administrator as well."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        approvers = employee.parent_id | employee.company_id.ft_time_off_hr_ids
        return approvers - employee

    def _ft_mail_addresses(self, employees, exclude=()):
        emails = []
        for employee in employees.sudo():
            email = (employee.work_email or '').strip()
            if email and email.lower() not in {e.lower() for e in emails} and email.lower() not in exclude:
                emails.append(formataddr((employee.name, email)))
        return emails

    def _ft_mail_to(self, kind):
        """Comma-separated recipients for a portal email (used by the templates)."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        if kind == 'decided_employee':
            return ','.join(self._ft_mail_addresses(employee))
        decider = self.env.context.get('ft_decider_email', '').lower()
        exclude = {decider, (employee.work_email or '').strip().lower()}
        emails = self._ft_mail_addresses(self._ft_approver_employees(), exclude)
        if not employee.parent_id:
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            if admin and admin.sudo().email and admin.sudo().email.lower() not in exclude \
                    and admin.sudo().email.lower() not in ','.join(emails).lower():
                emails.append(formataddr((admin.sudo().name, admin.sudo().email)))
        return ','.join(emails)

    def _ft_mail_reply_to(self):
        self.ensure_one()
        return ','.join(self._ft_mail_addresses(self.employee_id.sudo().company_id.ft_time_off_hr_ids))

    def _ft_mail_values(self):
        """What the email templates show about this request."""
        self.ensure_one()
        service = self.env['ft.portal.time.off'].sudo()
        values = service._leave_values(self)
        free = {t['id']: t['free'] for t in service._leave_types(self.employee_id) if not t['unpaid']}
        values['balance_after'] = free.get(self.holiday_status_id.id)
        values['balance_label'] = None if values['balance_after'] is None else (
            ('Short by %s' % service._format_days(-values['balance_after'])) if values['balance_after'] < 0
            else service._format_days(values['balance_after']))
        values['base_url'] = self.get_base_url()
        return values

    def _ft_send_mail(self, kind, **context):
        """Queue a portal email; nothing is sent when nobody is to receive it."""
        template = self.env.ref(MAIL_TEMPLATES[kind]).sudo()
        for leave in self.sudo():
            leave = leave.with_context(**context)
            if leave._ft_mail_to(kind):
                template.with_context(**context).send_mail(leave.id, force_send=False)
