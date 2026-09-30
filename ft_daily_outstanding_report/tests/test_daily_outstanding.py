from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import email_split


@tagged('post_install', '-at_install')
class TestDailyOutstanding(TransactionCase):
    def test_report_and_schedule(self):
        company = self.env.company
        self.env['res.company'].search([]).daily_outstanding_enabled = False
        partner = self.env['res.partner'].create({
            'name': 'Report <Customer>', 'email': 'report@example.com'})
        second = self.env['res.partner'].create({'name': 'Second', 'email': 'second@example.com'})
        duplicate = self.env['res.partner'].create({'name': 'Duplicate', 'email': partner.email})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            company.write({'daily_outstanding_partner_ids': [(5, 0, 0)],
                           'daily_outstanding_enabled': True})
        company.write({'daily_outstanding_partner_ids': [(6, 0, (partner | second | duplicate).ids)],
                       'daily_outstanding_enabled': True,
                       'daily_outstanding_last_date': False})
        product = self.env['product.product'].create({'name': 'Report Service', 'type': 'service'})
        orders = self.env['sale.order'].create([{
            'partner_id': partner.id, 'company_id': company.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1,
                                  'price_unit': amount, 'tax_ids': [(5, 0, 0)]})],
        } for amount in (100, 200, 400)])
        orders[2].action_cancel()
        rows = company._outstanding_rows('sale.order',
            [('state', 'in', ['draft', 'sent', 'sale']), ('id', 'in', orders.ids)], 'balance_amount')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['total'], 300)
        self.assertEqual(rows[0]['outstanding'], 300)
        journal = self.env['account.journal'].search(
            [('company_id', '=', company.id), ('type', '=', 'bank')], limit=1)
        # The database default receivable may be archived; post against an active one.
        partner.with_company(company).property_account_receivable_id = self.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        tomorrow = date.today() + timedelta(days=1)
        payments = self.env['account.payment'].create([{
            'partner_id': partner.id, 'company_id': company.id, 'journal_id': journal.id,
            'payment_type': 'inbound', 'partner_type': 'customer',
            'amount': amount, 'date': tomorrow + timedelta(days=days), 'memo': memo,
        } for amount, days, memo in ((50, 0, 'Older <Memo>'), (70, 1, 'Newest memo'),
                                     (90, 2, 'Unposted-memo'))])
        payments[:2].action_post()
        self.assertEqual(len(company._recent_payment_rows(limit=1)), 1)
        rows = company._recent_payment_rows()
        self.assertEqual([row['memo'] for row in rows[:2]], ['Newest memo', 'Older <Memo>'])
        self.assertEqual(rows[0]['amount'], 70)
        self.assertEqual(rows[0]['partner'], partner)
        self.assertNotIn('Unposted-memo', [row['memo'] for row in rows])
        body = company._daily_outstanding_body(datetime(2026, 9, 23).date())
        self.assertEqual(str(body).count('<table'), 3)
        self.assertIn('Report &lt;Customer&gt;', body)
        self.assertIn('Older &lt;Memo&gt;', body)
        self.assertIn(payments[1].name, body)
        self.assertNotIn('Unposted-memo', body)
        mail_domain = [('model', '=', 'res.company'), ('res_id', '=', company.id)]
        Mail = self.env['mail.mail']
        before = Mail.search_count(mail_domain)
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 9, 23, 2, 29)):
            company._cron_daily_outstanding_report()
        self.assertEqual(Mail.search_count(mail_domain), before)
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 9, 23, 2, 30)):
            company._cron_daily_outstanding_report()
            company._cron_daily_outstanding_report()
        self.assertEqual(Mail.search_count(mail_domain), before + 1)
        self.assertEqual(Mail.search(mail_domain, order='id desc', limit=1).state, 'outgoing')
        queued = Mail.search(mail_domain, order='id desc', limit=1)
        self.assertEqual(queued.model, 'res.company')
        self.assertEqual(queued.res_id, company.id)
        # Reproduce the exact post-SMTP delegated write, without transmitting mail.
        queued.with_user(self.env.ref('base.user_admin')).sudo(False).write({
            'state': 'sent', 'message_id': '<outstanding-regression@example.com>',
            'failure_type': False, 'failure_reason': False,
        })
        self.assertEqual(queued.state, 'sent')
        self.assertEqual(email_split(queued.email_to), ['report@example.com', 'second@example.com'])
        company.daily_outstanding_enabled = False
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 9, 24, 2, 30)):
            company._cron_daily_outstanding_report()
        self.assertEqual(Mail.search_count(mail_domain), before + 1)

    def test_recent_receipts_include_bank_transactions(self):
        company = self.env.company
        partner = self.env['res.partner'].create({'name': 'Bank Customer', 'email': 'bank@example.com'})
        partner.with_company(company).property_account_receivable_id = self.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        journal = self.env['account.journal'].search(
            [('company_id', '=', company.id), ('type', '=', 'bank')], limit=1)
        base = date.today() + timedelta(days=10)

        def bank_line(amount, memo, days):
            return self.env['account.bank.statement.line'].create({
                'journal_id': journal.id, 'date': base + timedelta(days=days),
                'payment_ref': memo, 'partner_id': partner.id, 'amount': amount})

        pending = bank_line(300, 'Pending bank credit', 0)
        bank_line(-200, 'Supplier debit', 1)
        payment = self.env['account.payment'].create({
            'partner_id': partner.id, 'company_id': company.id, 'journal_id': journal.id,
            'payment_type': 'inbound', 'partner_type': 'customer', 'amount': 70,
            'date': base + timedelta(days=2), 'memo': 'Registered payment'})
        payment.action_post()
        rows = company._recent_receipt_rows()
        found = [(row['source'], row['memo']) for row in rows]
        self.assertIn(('bank', 'Pending bank credit'), found)
        self.assertIn(('payment', 'Registered payment'), found)
        self.assertNotIn(('bank', 'Supplier debit'), found)
        self.assertEqual(found[0], ('payment', 'Registered payment'))     # newest first
        self.assertEqual(rows[0]['partner_name'], 'Bank Customer')
        self.assertEqual(len(company._recent_receipt_rows(limit=1)), 1)
        body = company._daily_outstanding_body(date.today())
        self.assertEqual(str(body).count('<table'), 3)
        self.assertIn('Pending bank credit', body)
        self.assertIn('<td>Bank</td>', body)
        self.assertIn('<td>Payment</td>', body)
        if not hasattr(pending, 'set_line_bank_statement_line'):
            return  # matching a transaction needs the enterprise bank reconciliation
        # Matched to an invoice: still a bank receipt. The database default income
        # account may be archived, so name an active one.
        income_account = self.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'invoice_date': base,
            'invoice_line_ids': [(0, 0, {'name': 'Service', 'quantity': 1, 'price_unit': 400,
                                         'account_id': income_account.id, 'tax_ids': [(5, 0, 0)]})]})
        invoice.action_post()
        matched = bank_line(400, 'Matched to invoice', 3)
        matched.set_line_bank_statement_line(invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable').ids)
        self.assertTrue(matched.is_reconciled)
        # Matched to the registered payment: listed once, as the payment.
        outstanding = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == payment.outstanding_account_id)
        if outstanding:
            bank_line(70, 'Matched to payment', 4).set_line_bank_statement_line(outstanding.ids)
        # Bank interest: not a customer receipt.
        interest = bank_line(50, 'Bank interest', 5)
        income = self.env['account.account'].search(
            [('account_type', '=', 'income_other'), ('company_ids', 'in', company.id)], limit=1)
        if income:
            suspense = interest.move_id.line_ids.filtered(
                lambda line: line.account_id == journal.suspense_account_id)
            interest.set_account_bank_statement_line(suspense.id, income.id)
        found = [(row['source'], row['memo']) for row in company._recent_receipt_rows()]
        self.assertIn(('bank', 'Matched to invoice'), found)
        self.assertNotIn(('bank', 'Matched to payment'), found)
        self.assertEqual(found.count(('payment', 'Registered payment')), 1)
        if income:
            self.assertNotIn(('bank', 'Bank interest'), found)

    def test_enable_through_settings(self):
        company = self.env.company
        company.write({'daily_outstanding_enabled': False,
                       'daily_outstanding_partner_ids': [(5, 0, 0)]})
        partner = self.env['res.partner'].create({
            'name': 'Valid Recipient', 'email': 'valid@example.com'})
        settings = self.env['res.config.settings'].create({
            'company_id': company.id,
            'daily_outstanding_enabled': True,
            'daily_outstanding_partner_ids': [(6, 0, partner.ids)],
        })
        settings.set_values()
        self.assertTrue(company.daily_outstanding_enabled)
        self.assertEqual(company.daily_outstanding_partner_ids, partner)
