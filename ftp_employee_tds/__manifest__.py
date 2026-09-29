# -*- coding: utf-8 -*-
{
    'name': 'Automatic TDS Computation (India)',
    'version': '19.0.2.0.1',
    'category': 'Human Resources/Payroll',
    'summary': 'Work out monthly TDS automatically instead of typing it in',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': ['hr_payroll', 'l10n_in_hr_payroll'],
    'data': [
        'data/ir_cron_data.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
