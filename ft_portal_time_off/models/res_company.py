# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    ft_time_off_hr_ids = fields.Many2many(
        'hr.employee', 'ft_time_off_hr_employee_rel', 'company_id', 'employee_id',
        string='HR for Time Off',
        help='They approve or refuse anyone\'s time off on the portal and get an email for every request, '
             'decision and withdrawal.')
    ft_time_off_email_from = fields.Char(
        string='Time Off Emails From', default='Fingertip Time Off <support@fingertipplus.com>',
        help='Sender of the portal time off emails. Replies go to the HR for Time Off.')
