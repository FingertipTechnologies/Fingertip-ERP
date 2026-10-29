# -*- coding: utf-8 -*-
{
    'name': 'Employee Portal: My Account and Time Off',
    'version': '19.0.1.2.0',
    'category': 'Human Resources/Time Off',
    'summary': 'Employee portal: My account dashboard; leave applied for and approved on the portal',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': ['portal', 'mail', 'hr_holidays', 'ftp_employee_leave_accrual'],
    'data': [
        'data/mail_templates.xml',
        'views/hr_views.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ft_portal_time_off/static/src/scss/time_off.scss',
            'ft_portal_time_off/static/src/js/time_off.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
