# -*- coding: utf-8 -*-
{
    "name": "Sale Order Advance Payment Tracker",
    "version": "19.0.1.0.2",
    "category": "Sales",
    "summary": "Attach bank receipts to Sales Orders as customer advances before "
               "invoicing, then allocate them to the invoice later.",
    "description": """
Sale Order Advance Payment Tracker
==================================
Allows bank transactions received before invoice creation to be attached to
confirmed Sales Orders and tracked as customer advances until they are allocated
against the final invoice.

This module does NOT modify Odoo's standard accounting reconciliation. It adds:
 * an "Attach to Sales Order" action in the Bank Reconciliation widget,
 * a customer advance = a native inbound Customer Payment,
 * a link model tying each advance split to a Sales Order,
 * an "Allocate Advances to Invoice" button on the Sales Order that uses the
   native outstanding-credits reconciliation.
""",
    "author": "Fingertipplus Technologies",
    "company": "Fingertipplus Technologies Pvt Ltd",
    "depends": ["sale_management", "account_accountant", "payment_status_in_sale"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/sale_advance_attach_wizard_views.xml",
        "views/sale_advance_payment_views.xml",
        "views/sale_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sale_order_advance_payment_tracker/static/src/js/bank_rec_attach_so.js",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
