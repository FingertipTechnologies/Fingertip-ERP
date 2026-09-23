from datetime import datetime
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
        body = company._daily_outstanding_body(datetime(2026, 9, 23).date())
        self.assertEqual(str(body).count('<table'), 2)
        self.assertIn('Report &lt;Customer&gt;', body)
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
