from datetime import date, datetime, timedelta

from odoo.tests import TransactionCase, tagged

from odoo.addons.ft_payment_reminder.models.payment_reminder_mixin import (
    format_indian_amount, reminder_kind)


@tagged('post_install', '-at_install')
class TestPaymentReminder(TransactionCase):

    def test_schedule(self):
        due = date(2026, 11, 20)  # Friday
        self.assertFalse(reminder_kind(due, due), 'nothing on the due date')
        self.assertEqual(reminder_kind(due, date(2026, 11, 17)), 'before')
        self.assertEqual(reminder_kind(due, date(2026, 11, 19)), 'before')
        self.assertFalse(reminder_kind(due, date(2026, 11, 18)))
        self.assertEqual(reminder_kind(due, date(2026, 11, 21)), 'overdue')  # +1
        self.assertFalse(reminder_kind(due, date(2026, 11, 22)))  # +2
        self.assertEqual(reminder_kind(due, date(2026, 11, 23)), 'overdue')  # +3
        self.assertFalse(reminder_kind(due, date(2026, 11, 29)), '+9 is a Sunday: skipped')
        self.assertEqual(reminder_kind(due, date(2026, 12, 1)), 'overdue')  # +11 Tue
        self.assertFalse(reminder_kind(due, date(2026, 11, 30)))  # +10 even

    def test_sunday_before_due_moves_to_saturday(self):
        due = date(2026, 11, 24)  # Tuesday: 3 days before = Sat 21, 1 day before = Mon 23
        self.assertEqual(reminder_kind(due, date(2026, 11, 21)), 'before')
        due = date(2026, 11, 23)  # Monday: 1 day before = Sunday 22 -> Saturday 21
        self.assertEqual(reminder_kind(due, date(2026, 11, 21)), 'before')
        self.assertFalse(reminder_kind(due, date(2026, 11, 22)))
        due = date(2026, 11, 25)  # Wednesday: 3 days before = Sunday 22 -> Saturday 21
        self.assertEqual(reminder_kind(due, date(2026, 11, 21)), 'before')

    def test_indian_amount(self):
        inr = self.env.ref('base.INR')
        self.assertEqual(format_indian_amount(123456.5, inr, self.env), '₹1,23,456.50')
        self.assertEqual(format_indian_amount(12345678, inr, self.env), '₹1,23,45,678.00')
        self.assertEqual(format_indian_amount(999, inr, self.env), '₹999.00')

    def _customer(self, **vals):
        return self.env['res.partner'].create(dict(
            name='Reminder Test Customer', email='customer@example.com', **vals))

    def _invoice(self, partner, due):
        product = self.env['product.product'].create({'name': 'Reminder Service', 'list_price': 1000})
        income = self.env['account.account'].search([
            ('account_type', '=', 'income'), ('active', '=', True),
            ('company_ids', 'in', self.env.company.id)], limit=1)
        receivable = self.env['account.account'].search([
            ('account_type', '=', 'asset_receivable'), ('active', '=', True),
            ('company_ids', 'in', self.env.company.id)], limit=1)
        partner.property_account_receivable_id = receivable
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_date': due, 'invoice_date_due': due,
            'invoice_user_id': self.env.user.id,
            'invoice_line_ids': [(0, 0, {'product_id': product.id, 'price_unit': 1000,
                                         'quantity': 1, 'tax_ids': [(6, 0, [])],
                                         'account_id': income.id})],
        })
        move.action_post()
        move.invoice_date_due = due
        return move

    def _mails(self, record):
        return self.env['mail.mail'].search([('model', '=', record._name), ('res_id', '=', record.id)])

    def test_invoice_overdue_email(self):
        today = date(2026, 11, 21)  # Saturday
        partner = self._customer()
        move = self._invoice(partner, today - timedelta(days=1))
        self.env['account.move']._ft_run_reminders(today)
        mail = self._mails(move)
        self.assertEqual(len(mail), 1)
        self.assertIn('Reminder Outstanding Invoice', mail.subject)
        self.assertIn(move.name, mail.body_html)
        self.assertIn('is overdue', mail.body_html)
        self.assertEqual(mail.recipient_ids, partner)
        self.assertTrue(mail.attachment_ids, 'Custom Invoice PDF attached')
        self.assertEqual(move.ft_reminder_last_date, today)
        # second run the same day: nothing more
        self.env['account.move']._ft_run_reminders(today)
        self.assertEqual(len(self._mails(move)), 1)
        # +2: not an alternate day
        self.env['account.move']._ft_run_reminders(today + timedelta(days=1))
        self.assertEqual(len(self._mails(move)), 1)

    def test_before_due_email(self):
        today = date(2026, 11, 17)
        move = self._invoice(self._customer(), today + timedelta(days=3))
        self.env['account.move']._ft_run_reminders(today)
        mail = self._mails(move)
        self.assertEqual(len(mail), 1)
        self.assertIn('Due on 20-Nov-2026', mail.subject)
        self.assertIn('will be due by', mail.body_html)

    def test_stop_reminder(self):
        today = date(2026, 11, 21)
        move = self._invoice(self._customer(), today - timedelta(days=1))
        move.ft_stop_reminder = 'yes'
        stopped_partner = self._customer(ft_stop_reminder='yes')
        move2 = self._invoice(stopped_partner, today - timedelta(days=1))
        self.env['account.move']._ft_run_reminders(today)
        self.assertFalse(self._mails(move))
        self.assertFalse(self._mails(move2))

    def test_no_email_and_sunday(self):
        today = date(2026, 11, 21)
        move = self._invoice(self.env['res.partner'].create({'name': 'No Mail'}),
                             today - timedelta(days=1))
        self.env['account.move']._ft_run_reminders(today)
        self.assertFalse(self._mails(move))
        self.assertIn('no email', move.ft_reminder_last_status)
        move2 = self._invoice(self._customer(), date(2026, 11, 21))  # +1 = Sunday 22
        self.assertEqual(self.env['account.move']._ft_run_reminders(date(2026, 11, 22)), 0)
        self.assertFalse(self._mails(move2))

    def test_paid_invoice_not_reminded(self):
        today = date(2026, 11, 21)
        move = self._invoice(self._customer(), today - timedelta(days=1))
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create({})._create_payments()
        self.env['account.move']._ft_run_reminders(today)
        self.assertFalse(self._mails(move))

    def test_proforma(self):
        partner = self._customer()
        product = self.env['product.product'].create({'name': 'Reminder Product', 'list_price': 500})
        term = self.env['account.payment.term'].create({
            'name': 'Reminder 10 days', 'line_ids': [(0, 0, {'value': 'percent', 'value_amount': 100, 'nb_days': 10})]})
        order = self.env['sale.order'].create({
            'partner_id': partner.id, 'payment_term_id': term.id,
            'date_order': datetime(2026, 11, 10, 6, 0),
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 2,
                                   'price_unit': 500, 'tax_ids': [(6, 0, [])]})],
        })
        order.action_confirm()
        order.date_order = datetime(2026, 11, 10, 6, 0)
        self.assertEqual(order._ft_reminder_due_date(), date(2026, 11, 20))
        self.env['sale.order']._ft_run_reminders(date(2026, 11, 17))
        mail = self._mails(order)
        self.assertEqual(len(mail), 1)
        self.assertIn('Reminder Proforma %s Due on 20-Nov-2026' % order.name, mail.subject)
        self.assertIn('₹1,000.00', mail.body_html)
        self.assertTrue(mail.attachment_ids)
        # no payment terms: due on the order date
        order.payment_term_id = False
        self.assertEqual(order._ft_reminder_due_date(), date(2026, 11, 10))
