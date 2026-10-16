{
    'name': 'Accounting Activities',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Accounting > Activities: log of chatter activities with customer, '
               'date and remark across Sales Orders, Invoices and Payments.',
    'description': """
Adds an "Activities" top menu in Accounting, right after Vendors: a log of the
activities (calls, emails, to-dos) from the chatter of Sales Orders / Pro formas,
Invoices, Credit Notes, Vendor Bills, Journal Entries, Payments and Customers.
Shows pending and done activities with customer, date, note and the remark
entered when marking them done, with Today / This Week filters.
Clicking a line opens the source document.
""",
    'author': 'Fingertipplus Technologies',
    'depends': ['sale_management', 'account_accountant'],
    'data': [
        'views/mail_activity_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
