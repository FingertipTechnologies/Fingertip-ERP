# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    ft_portal_visible = fields.Boolean(
        string='Show on Employee Portal',
        help='Employees can apply for this type on the portal. A type that needs an '
             'allocation is only offered to employees who have one.')
