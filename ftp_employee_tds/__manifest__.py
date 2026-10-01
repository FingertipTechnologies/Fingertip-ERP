# -*- coding: utf-8 -*-
{
    'name': 'Automatic TDS Computation (India)',
    'version': '19.0.3.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Work out monthly TDS automatically instead of typing it in',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': ['hr_payroll', 'l10n_in_hr_payroll', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/tds_slab_set_data.xml',
        'views/tds_slab_set_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
