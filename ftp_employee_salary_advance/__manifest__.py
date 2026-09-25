# -*- coding: utf-8 -*-
{
    'name': 'Employee Salary Advance',
    'version': '19.0.1.3.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Salary advances recovered automatically through payslips',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    # hr_contract does not exist in Odoo 19: contracts are hr.version, which
    # comes from hr. hr_payroll pulls in hr and hr_work_entry_enterprise.
    'depends': ['hr', 'hr_payroll', 'mail'],
    'data': [
        'security/salary_advance_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/payroll_data.xml',
        'views/hr_salary_advance_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_payslip_views.xml',
        'views/menus.xml',
    ],
    'demo': ['demo/salary_advance_demo.xml'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
