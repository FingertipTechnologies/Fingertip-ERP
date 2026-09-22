from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDailyOutstanding(TransactionCase):
    def test_report_and_schedule(self):
        company = self.env.company
        self.env['res.company'].search([]).daily_outstanding_enabled = False
        partner = self.env['res.partner'].create({
            'name': 'Report <Customer>', 'email': 'report@example.com'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            company.write({'daily_outstanding_partner_id': False,
                           'daily_outstanding_enabled': True})
        company.write({'daily_outstanding_partner_id': partner.id,
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
        mail_domain = [('email_to', '=', partner.email_formatted)]
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
        company.daily_outstanding_enabled = False
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 9, 24, 2, 30)):
            company._cron_daily_outstanding_report()
        self.assertEqual(Mail.search_count(mail_domain), before + 1)
