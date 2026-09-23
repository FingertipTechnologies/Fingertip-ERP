# Daily Outstanding Report

Sales → Configuration → Settings → Outstanding Reports. Enable Daily Outstanding
Report, select contacts with valid email addresses, and save. Settings belong to the
selected company; disabled by default.

The scheduler queues one HTML email per enabled company, addressed to all selected recipients daily at 08:00 Asia/Kolkata
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

Settings save regression fixed in 19.0.1.1.1: enable flag and recipients are saved together. Both settings-save and scheduling tests pass. The local backup also required a unique ID index on res_config_settings for the settings recipient relation.

Version 19.0.1.1.2 links new report messages to their company so an authorized
administrator can save the delegated Message-ID / Sent status after SMTP delivery.
The regression test performs that write as the normal administrator without sudo
and without transmitting an email. Existing unlinked emails are not modified:
verify delivery before any retry, since a status-write failure can occur after
SMTP has accepted the email. Deploy the updated module and restart/upgrade it in
the affected environment for newly generated emails to use the fix.
The local backup's missing `mail_message` primary key was also restored (validated
by PostgreSQL), because Odoo's message access SQL relies on that primary key for
its GROUP BY query. This repair did not change message contents or delivery status.

Version 19.0.1.1.3 queues one message with all distinct recipient email addresses in
To. Recipients can see the other To addresses. The report is rendered once using
the company contact’s language (English fallback).
