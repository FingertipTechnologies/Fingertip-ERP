{
    'name': 'Sales Forecast',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Sales > Forecast: expected amounts per customer and date, '
               'with list, form and graph views.',
    'description': """
Adds a "Forecast" top menu in Sales, next to Activities: expected amounts recorded by
customer and date, with a description. The list, form and graph views can be filtered by
This Month, Next Month, Next 3 / 6 Months, This Financial Year (April to March) and Past,
and grouped by customer, month, quarter or year.
""",
    'author': 'Fingertipplus Technologies',
    'depends': ['sale_management'],
    'data': [
        'security/ir.model.access.csv',
        'security/ft_sales_forecast_security.xml',
        'views/ft_sales_forecast_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
