{
    'name': 'Payment Reminders',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Daily email reminders for unpaid invoices and pro formas',
    'description': """
Daily (except Sunday, 10:00 AM India) email reminders until an invoice or a
confirmed sales order (pro forma) is paid:

* 3 days and 1 day before the due date (a Sunday moves to Saturday);
* every alternate day after the due date (day 1, 3, 5 ...), Sundays skipped.

Stop Reminder (Yes/No) on the invoice, the sales order and the customer.
""",
    'author': 'Fingertipplus Technologies',
    'license': 'AGPL-3',
    'depends': ['account', 'sale_management', 'mail', 'payment_status_in_sale', 'custom_invoice'],
    'data': [
        'data/mail_template_data.xml',
        'data/ir_cron.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
}
