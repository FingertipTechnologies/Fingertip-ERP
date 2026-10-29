# -*- coding: utf-8 -*-
from . import controllers
from . import models


def post_init_hook(env):
    """Show the Fingertip leave types on the portal.

    Casual, sick, maternity and paternity leave are the ones the accrual
    module is configured with; Loss of Pay and Restricted Holiday are found by
    name. HR can change the selection on each leave type afterwards.
    """
    types = env['hr.leave.type']
    for company in env['res.company'].search([]):
        types |= (company.ftp_casual_leave_type_id | company.ftp_sick_leave_type_id
                  | company.ftp_maternity_leave_type_id | company.ftp_paternity_leave_type_id)
    types |= types.search([('name', 'in', ['Loss of Pay (LOP)', 'Restricted Holiday'])])
    types.write({'ft_portal_visible': True})
    # Portal users given access from Contacts before the module was installed.
    env['res.users'].search([('share', '=', True)])._ft_link_employees()
