import logging
from collections import defaultdict

import pytz
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize, format_amount, format_date

_logger = logging.getLogger(__name__)

RECENT_PAYMENTS = 20
SOURCE_LABELS = {'payment': 'Payment', 'bank': 'Bank'}


class ResCompany(models.Model):
    _inherit = 'res.company'

    daily_outstanding_enabled = fields.Boolean(string='Daily Outstanding Report')
    daily_outstanding_partner_ids = fields.Many2many(
        'res.partner', 'ft_outstanding_company_partner_rel', 'company_id', 'partner_id',
        string='Report Recipients',
        help='Send the daily outstanding report to these contacts’ email addresses.')
    daily_outstanding_last_date = fields.Date(copy=False, readonly=True)

    @api.constrains('daily_outstanding_enabled', 'daily_outstanding_partner_ids')
    def _check_daily_outstanding_recipient(self):
        for company in self:
            if not company.daily_outstanding_enabled:
                continue
            if not company.daily_outstanding_partner_ids:
                raise ValidationError(_('Select at least one report recipient.'))
            invalid = company.daily_outstanding_partner_ids.filtered(
                lambda partner: not email_normalize(partner.email or ''))
            if invalid:
                raise ValidationError(_(
                    'Enter one valid address in the Email field of these contacts: %(contacts)s',
                    contacts=', '.join(invalid.mapped('display_name'))))

    def _outstanding_rows(self, model, domain, balance_field):
        self.ensure_one()
        totals = defaultdict(lambda: [0.0, 0.0])
        records = self.env[model].sudo().with_company(self).search(
            [('company_id', '=', self.id)] + domain)
        for record in records:
            balance = record[balance_field]
            if record.currency_id.compare_amounts(balance, 0) <= 0:
                continue
            key = (record.partner_id.commercial_partner_id, record.currency_id)
            totals[key][0] += record.amount_total
            totals[key][1] += balance
        return [dict(partner=partner, currency=currency, total=amounts[0],
                     outstanding=amounts[1])
                for (partner, currency), amounts in sorted(
                    totals.items(), key=lambda item: (
                        -item[1][1], item[0][0].name or '',
                        item[0][0].id, item[0][1].id))]

    def _recent_payment_rows(self, limit=RECENT_PAYMENTS):
        """Newest confirmed customer payments of this company, most recent first."""
        self.ensure_one()
        payments = self.env['account.payment'].sudo().with_company(self).search([
            ('company_id', '=', self.id),
            ('partner_type', '=', 'customer'),
            ('payment_type', '=', 'inbound'),
            ('state', 'in', ['in_process', 'paid']),
        ], order='date desc, id desc', limit=limit)
        return [dict(source='payment', date=payment.date, create_date=payment.create_date,
                     name=payment.name or '',
                     partner=payment.partner_id.commercial_partner_id,
                     partner_name=payment.partner_id.commercial_partner_id.name or '',
                     memo=payment.memo or '', amount=payment.amount,
                     currency=payment.currency_id)
                for payment in payments]

    @api.model
    def _bank_line_is_customer_receipt(self, line):
        """True for money in that is booked to a receivable or still unreconciled."""
        journal = line.journal_id
        accounts = line.move_id.line_ids.account_id - journal.default_account_id
        return journal.suspense_account_id in accounts or any(
            account.account_type == 'asset_receivable' for account in accounts)

    def _recent_bank_rows(self, limit=RECENT_PAYMENTS):
        """Newest incoming bank transactions that are customer receipts, most recent first.

        A transaction qualifies when its own journal entry carries a receivable
        line (matched to an invoice, or booked as an advance) or still sits on
        the journal's suspense account (not reconciled yet). Money booked
        elsewhere is left out: bank interest, transfers, and transactions
        matched to a registered payment, whose counterpart is the outstanding
        receipts account. That payment is listed by _recent_payment_rows, so a
        receipt never shows twice.
        """
        self.ensure_one()
        StatementLine = self.env['account.bank.statement.line'].sudo().with_company(self)
        domain = [('company_id', '=', self.id), ('amount', '>', 0), ('state', '=', 'posted')]
        rows, offset, page = [], 0, 100
        while len(rows) < limit:
            lines = StatementLine.search(domain, order='internal_index desc', limit=page, offset=offset)
            if not lines:
                break
            offset += page
            for line in lines:
                if not self._bank_line_is_customer_receipt(line):
                    continue
                partner = line.partner_id.commercial_partner_id
                rows.append(dict(source='bank', date=line.date, create_date=line.create_date,
                                 name=line.move_id.name or '', partner=partner,
                                 partner_name=partner.name or line.partner_name or '',
                                 memo=line.payment_ref or '', amount=line.amount,
                                 currency=line.currency_id or self.currency_id))
                if len(rows) == limit:
                    break
        return rows

    def _recent_receipt_rows(self, limit=RECENT_PAYMENTS):
        """Registered payments and incoming bank transactions together, newest first."""
        rows = self._recent_payment_rows(limit) + self._recent_bank_rows(limit)
        rows.sort(key=lambda row: (row['date'], row['create_date']), reverse=True)
        return rows[:limit]

    def _daily_outstanding_body(self, report_date):
        self.ensure_one()
        sections = [
            ('Pro Forma', self._outstanding_rows('sale.order',
                [('state', 'in', ['draft', 'sent', 'sale'])], 'balance_amount')),
            ('Invoices', self._outstanding_rows('account.move',
                [('state', '=', 'posted'), ('move_type', '=', 'out_invoice'),
                 ('amount_residual', '>', 0)], 'amount_residual')),
        ]
        body = Markup('<h2>Daily Outstanding Report</h2><p>%s — %s (India time)</p>') % (
            self.name, str(report_date))
        for title, rows in sections:
            body += Markup('<h3>%s</h3><table border="1" cellpadding="8" '
                           'cellspacing="0" style="border-collapse:collapse;width:100%%;table-layout:fixed">'
                           '<tr><th style="width:40%%;text-align:left">Customer Name</th>'
                           '<th style="width:30%%">Total Amount</th>'
                           '<th style="width:30%%">Outstanding Amount</th></tr>') % title
            totals = defaultdict(lambda: [0.0, 0.0])
            for row in rows:
                currency = row['currency']
                body += Markup('<tr><td style="overflow-wrap:anywhere;word-wrap:break-word">%s</td>'
                               '<td align="right">%s</td>'
                               '<td align="right">%s</td></tr>') % (
                    row['partner'].name,
                    format_amount(self.env, row['total'], currency),
                    format_amount(self.env, row['outstanding'], currency))
                totals[currency][0] += row['total']
                totals[currency][1] += row['outstanding']
            for currency, amounts in totals.items():
                body += Markup('<tr><th style="text-align:left">%s</th><th>%s</th><th>%s</th></tr>') % (
                    ('Total (%s)' % currency.name) if len(totals) > 1 else 'Total',
                    format_amount(self.env, amounts[0], currency),
                    format_amount(self.env, amounts[1], currency))
            if not rows:
                body += Markup('<tr><td colspan="3">No outstanding amounts.</td></tr>')
            body += Markup('</table>')
        receipts = self._recent_receipt_rows()
        body += Markup('<h3>Recent Payments</h3><table border="1" cellpadding="8" '
                       'cellspacing="0" style="border-collapse:collapse;width:100%;table-layout:fixed">'
                       '<tr><th style="width:12%;text-align:left">Date</th>'
                       '<th style="width:10%;text-align:left">Source</th>'
                       '<th style="width:16%;text-align:left">Number</th>'
                       '<th style="width:26%;text-align:left">Customer Name</th>'
                       '<th style="width:20%;text-align:left">Memo</th>'
                       '<th style="width:16%">Amount</th></tr>')
        for row in receipts:
            body += Markup('<tr><td>%s</td><td>%s</td>'
                           '<td style="overflow-wrap:anywhere;word-wrap:break-word">%s</td>'
                           '<td style="overflow-wrap:anywhere;word-wrap:break-word">%s</td>'
                           '<td style="overflow-wrap:anywhere;word-wrap:break-word">%s</td>'
                           '<td align="right">%s</td></tr>') % (
                format_date(self.env, row['date']), SOURCE_LABELS[row['source']], row['name'],
                row['partner_name'], row['memo'],
                format_amount(self.env, row['amount'], row['currency']))
        if not receipts:
            body += Markup('<tr><td colspan="6">No payments recorded.</td></tr>')
        body += Markup('</table>')
        return body + Markup('<p>Totals include only documents with a positive outstanding '
                             'balance. Pro forma: Total / ProForma Balance; '
                             'posted customer invoices: Total / Amount Due. '
                             'Recent Payments: the %s most recent customer receipts, newest '
                             'first: registered payments and incoming bank transactions that '
                             'are matched to invoices or still awaiting reconciliation. A bank '
                             'transaction matched to a registered payment is listed once, as '
                             'the payment; interest and other non-customer credits are left '
                             'out.</p>') % RECENT_PAYMENTS

    @api.model
    def _cron_daily_outstanding_report(self):
        now = fields.Datetime.now().replace(tzinfo=pytz.UTC).astimezone(
            pytz.timezone('Asia/Kolkata'))
        if now.hour < 8:
            return
        for company in self.sudo().search([('daily_outstanding_enabled', '=', True)]):
            # Serialize manual and scheduled runs; mail and date commit together.
            self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE',
                                [company.id])
            company.invalidate_recordset(['daily_outstanding_last_date'])
            if company.daily_outstanding_last_date == now.date():
                continue
            recipients = company.daily_outstanding_partner_ids
            if not recipients or any(not email_normalize(p.email or '') for p in recipients):
                _logger.warning('Daily outstanding report skipped: company %s has missing or invalid recipients', company.id)
                continue
            # One queued message for the company, with each address listed once.
            addresses = list(dict.fromkeys(
                email_normalize(recipient.email)
                for recipient in recipients.sorted('id')
            ))
            report_company = company.with_company(company).with_context(
                lang=company.partner_id.lang or 'en_US')
            self.env['mail.mail'].sudo().create({
                # Allow authorized administrators to persist the sent status.
                'model': 'res.company',
                'res_id': company.id,
                'subject': _('Daily Outstanding Report - %(company)s - %(date)s',
                             company=company.name, date=now.date()),
                'body_html': report_company._daily_outstanding_body(now.date()),
                'email_from': 'support@fingertipplus.com',
                'email_to': ', '.join(addresses),
                'auto_delete': False,
            })
            company.daily_outstanding_last_date = now.date()
