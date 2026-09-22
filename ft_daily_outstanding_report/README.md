# Daily Outstanding Report

Sales → Configuration → Settings → Outstanding Reports. Enable Daily Outstanding
Report, select a contact with a valid email, and save. Settings belong to the
selected company; disabled by default.

The scheduler queues one HTML email per enabled company daily at 08:00 Asia/Kolkata
(02:30 UTC). Odoo's email queue and outgoing mail server deliver it; delivery can
be later if the server or mail queue is stopped. Duplicate runs on the same India
calendar date do not queue another message. Failed outgoing emails remain in the
standard Technical → Emails list for retry.

Two tables group documents by commercial customer and original currency:
- Pro Forma: non-cancelled quotations / sales orders, `amount_total` and the
  existing `balance_amount` (ProForma Balance), including advance tracker logic.
- Invoices: posted customer invoices, `amount_total` and `amount_residual`
  (Amount Due). Draft invoices, credit notes and receipts are excluded.

Only positive outstanding documents contribute to either table and its totals.
Currencies have separate totals. Empty sections show “No outstanding amounts.”
No changes are made to payments, balances, or accounting entries.

Install with the parent fingertip_accounting_addons directory on addons_path:

    ./19venv/bin/python odoo-bin -c community.conf -d ftp_accounting_sep22 -i ft_daily_outstanding_report --stop-after-init --no-http

Tests (use an available HTTP port):

    ./19venv/bin/python odoo-bin -c community.conf -d TEST_DATABASE -u ft_daily_outstanding_report --test-enable --test-tags /ft_daily_outstanding_report --stop-after-init --http-port=8029 --max-cron-threads=0

## Local backup installation notes

The local `ftp_accounting_sep22` backup was missing standard uniqueness indexes
required by Odoo's ORM. Installation restored unique indexes on
`ir_model_data(module, name)`, `ir_model_fields(model, name)`, and the `id` columns
of the following tables referenced by company/settings fields:

`ir_sequence`, `ir_ui_view`, `l10n_in_pan_entity`, `mail_alias_domain`, `mail_template`, `product_product`, `report_paperformat`, `res_company`, `res_country`, `res_currency`, `res_partner`, `res_users`, `resource_calendar`, `sale_order_template`.

PostgreSQL validated uniqueness when creating these indexes. No business records
were removed by these repairs. Module installation and its Odoo transaction test
passed with 0 failures and 0 errors; test changes were rolled back and no email
was transmitted.
