import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.tools import format_amount

_logger = logging.getLogger(__name__)

INDIA_TZ = pytz.timezone('Asia/Kolkata')
SUNDAY = 6
DAYS_BEFORE_DUE = (3, 1)
STOP_SELECTION = [('no', 'No'), ('yes', 'Yes')]


def reminder_kind(due_date, today):
    """'before', 'overdue' or False: which reminder (if any) is due today.

    - never on a Sunday;
    - 3 days and 1 day before the due date; a Sunday moves to the Saturday;
    - nothing on the due date itself;
    - after it, every alternate day counted from the due date (1, 3, 5 ...);
      a Sunday is skipped, the next alternate day goes as normal.
    """
    if not due_date or today.weekday() == SUNDAY:
        return False
    if today < due_date:
        for days in DAYS_BEFORE_DUE:
            day = due_date - timedelta(days=days)
            if day.weekday() == SUNDAY:
                day -= timedelta(days=1)
            if day == today:
                return 'before'
        return False
    if today > due_date and (today - due_date).days % 2 == 1:
        return 'overdue'
    return False


def format_indian_amount(amount, currency, env):
    """Rupees with Indian grouping (₹1,23,456.00); other currencies as Odoo shows them."""
    if currency.name != 'INR':
        return format_amount(env, amount, currency)
    sign = '-' if amount < 0 else ''
    whole, decimals = f'{abs(currency.round(amount)):.2f}'.split('.')
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    whole = ','.join(groups + [tail])
    return f'{sign}₹{whole}.{decimals}'


class FtPaymentReminderMixin(models.AbstractModel):
    _name = 'ft.payment.reminder.mixin'
    _description = 'Payment Reminder Mixin'

    ft_stop_reminder = fields.Selection(
        STOP_SELECTION, string='Stop Reminder', default='no', required=True, copy=False,
        help='Yes: no automatic payment reminders are sent for this document.')
    ft_reminder_last_date = fields.Date(string='Last Reminder', copy=False, readonly=True)
    ft_reminder_last_status = fields.Char(string='Last Reminder Result', copy=False, readonly=True)

    # ---- hooks implemented by account.move / sale.order -----------------
    _ft_reminder_label = ''
    _ft_reminder_templates = {}

    @api.model
    def _ft_reminder_domain(self):
        raise NotImplementedError

    def _ft_reminder_partner(self):
        raise NotImplementedError

    def _ft_reminder_salesperson(self):
        raise NotImplementedError

    def _ft_reminder_due_date(self):
        raise NotImplementedError

    def _ft_reminder_amount(self):
        raise NotImplementedError

    # ---- helpers used by the mail templates ------------------------------
    def _ft_reminder_amount_text(self):
        self.ensure_one()
        return format_indian_amount(self._ft_reminder_amount(), self.currency_id, self.env)

    def _ft_reminder_due_text(self):
        self.ensure_one()
        due = self._ft_reminder_due_date()
        return due.strftime('%d-%b-%Y') if due else ''

    # ---- sending ----------------------------------------------------------
    @api.model
    def _ft_india_today(self):
        return datetime.now(pytz.utc).astimezone(INDIA_TZ).date()

    def _ft_reminder_stopped(self):
        self.ensure_one()
        partner = self._ft_reminder_partner()
        return 'yes' in (self.ft_stop_reminder, partner.ft_stop_reminder,
                         partner.commercial_partner_id.ft_stop_reminder)

    def _ft_reminder_kind_today(self, today):
        self.ensure_one()
        if self._ft_reminder_stopped() or self.ft_reminder_last_date == today:
            return False
        if self.currency_id.compare_amounts(self._ft_reminder_amount(), 0) <= 0:
            return False
        return reminder_kind(self._ft_reminder_due_date(), today)

    def _ft_send_reminder(self, kind, today):
        """Queue the reminder email of `kind` for this document; record the result."""
        self.ensure_one()
        partner = self._ft_reminder_partner()
        if not partner.email:
            self.ft_reminder_last_status = 'Not sent: customer has no email'
            return False
        template = self.env.ref(self._ft_reminder_templates[kind])
        salesperson = self._ft_reminder_salesperson()
        cc = salesperson.email_formatted if salesperson.email else False
        template.with_company(self.company_id).send_mail(
            self.id, email_values={'email_cc': cc} if cc else None)
        label = 'before due date' if kind == 'before' else 'overdue'
        to_text = partner.email + (f' (cc {salesperson.email})' if cc else '')
        self.ft_reminder_last_date = today
        self.ft_reminder_last_status = f'Sent ({label}) to {to_text}'
        self.message_post(
            body=f'Payment reminder ({label}) emailed to {to_text}: '
                 f'{self._ft_reminder_amount_text()}, due {self._ft_reminder_due_text()}.',
            message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    @api.model
    def _ft_run_reminders(self, today=None):
        today = today or self._ft_india_today()
        sent = 0
        if today.weekday() == SUNDAY:
            return sent
        for record in self.sudo().search(self._ft_reminder_domain(), order='id'):
            try:
                with self.env.cr.savepoint():
                    kind = record._ft_reminder_kind_today(today)
                    if kind and record._ft_send_reminder(kind, today):
                        sent += 1
            except Exception:
                _logger.exception('Payment reminder failed for %s', record)
        return sent

    @api.model
    def _cron_send_payment_reminders(self):
        today = self._ft_india_today()
        invoices = self.env['account.move']._ft_run_reminders(today)
        proformas = self.env['sale.order']._ft_run_reminders(today)
        _logger.info('Payment reminders %s: %s invoice(s), %s pro forma(s) queued',
                     today, invoices, proformas)
