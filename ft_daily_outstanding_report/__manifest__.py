{
    'name': 'Daily Outstanding Report',
    'version': '19.0.1.1.1',
    'category': 'Sales',
    'summary': 'Daily customer pro forma and invoice outstanding email at 8 AM IST',
    'author': 'Fingertipplus Technologies',
    'license': 'AGPL-3',
    'depends': ['payment_status_in_sale'],
    'data': ['views/res_config_settings_views.xml', 'data/ir_cron.xml'],
    'installable': True,
}
