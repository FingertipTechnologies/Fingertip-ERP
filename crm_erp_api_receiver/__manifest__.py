{
    "name": "CRM/PMS Customer API Receiver",
    "version": "19.0.1.0.0",
    "category": "Accounting/CRM",
    "summary": "CRM customer upsert and ERP-owned historical code matching",
    "author": "Custom Development",
    "license": "LGPL-3",
    "depends": ["base", "contacts"],
    "external_dependencies": {"python": ["requests"]},
    "data": ["data/ir_sequence.xml", "data/cron.xml",
             "views/res_config_settings_views.xml",
             "views/res_partner_views.xml"],
    "installable": True,
    "application": True
}
