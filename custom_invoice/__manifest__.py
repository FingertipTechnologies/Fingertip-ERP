{
    "name": "Custom Invoice Report",
    "version": "19.0.1.0.1",
    "category": "Accounting",
    "summary": "Custom PDF Invoice for account.move",
    "depends": ["account", "sale", "l10n_in", "l10n_in_sale"],
    "data": [
        "data/cash_rounding.xml",
        "views/account_move_views.xml",
        "report/invoice_report.xml",
        "report/standard_invoice_inherit.xml",
        "report/standard_sale_inherit.xml",
    ],
    "installable": True,
    "application": False,
}
