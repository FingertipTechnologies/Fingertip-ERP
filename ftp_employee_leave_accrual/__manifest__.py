# -*- coding: utf-8 -*-
{
    'name': 'Employee Leave Accrual Policy',
    'version': '19.0.1.2.0',
    'category': 'Human Resources/Time Off',
    'summary': 'Monthly casual and sick leave accrual for confirmed employees',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': ['hr', 'hr_holidays'],
    'data': [
        'data/hr_contract_type_data.xml',
        'data/ir_cron_data.xml',
        'data/ir_actions_server_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'demo': ['demo/leave_accrual_demo.xml'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
