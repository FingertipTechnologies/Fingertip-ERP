{
    'name': 'Payslip PDF Preview',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Preview a payslip PDF inside Odoo instead of downloading it',
    'author': 'Fingertipplus Technologies',
    'license': 'AGPL-3',
    'depends': ['hr_payroll'],
    'data': ['views/hr_payslip_views.xml'],
    'assets': {
        'web.assets_backend': [
            'ft_payslip_preview/static/src/**/*',
        ],
    },
    'installable': True,
}
