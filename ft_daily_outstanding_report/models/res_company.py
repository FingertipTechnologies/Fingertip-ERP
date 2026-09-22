import logging
from collections import defaultdict

import pytz
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize, format_amount

_logger = logging.getLogger(__name__)


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
                        item[0][0].name or '', item[0][0].id, item[0][1].id))]

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
                           'cellspacing="0" style="border-collapse:collapse;width:100%%">'
                           '<tr><th>Customer Name</th><th>Currency</th>'
                           '<th>Total Amount</th><th>Outstanding Amount</th></tr>') % title
            totals = defaultdict(lambda: [0.0, 0.0])
            for row in rows:
                currency = row['currency']
                body += Markup('<tr><td>%s</td><td>%s</td><td align="right">%s</td>'
                               '<td align="right">%s</td></tr>') % (
                    row['partner'].name, currency.name,
                    format_amount(self.env, row['total'], currency),
                    format_amount(self.env, row['outstanding'], currency))
                totals[currency][0] += row['total']
                totals[currency][1] += row['outstanding']
            for currency, amounts in totals.items():
                body += Markup('<tr><th>Total</th><th>%s</th><th>%s</th><th>%s</th></tr>') % (
                    currency.name, format_amount(self.env, amounts[0], currency),
                    format_amount(self.env, amounts[1], currency))
            if not rows:
                body += Markup('<tr><td colspan="4">No outstanding amounts.</td></tr>')
            body += Markup('</table>')
        return body + Markup('<p>Totals include only documents with a positive outstanding '
                             'balance. Pro forma: Total / ProForma Balance; '
                             'posted customer invoices: Total / Amount Due.</p>')

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
            addresses = set()
            for recipient in recipients.sorted('id'):
                address = email_normalize(recipient.email)
                if address in addresses:
                    continue
                addresses.add(address)
                localized_company = company.with_company(company).with_context(lang=recipient.lang or 'en_US')
                self.env['mail.mail'].sudo().create({
                    # Give message writes the company's normal access rules.
                    # Otherwise a non-author cannot persist message_id after SMTP delivery.
                    'model': 'res.company',
                    'res_id': company.id,
                    'subject': _('Daily Outstanding Report - %(company)s - %(date)s',
                                 company=company.name, date=now.date()),
                    'body_html': localized_company._daily_outstanding_body(now.date()),
                    'email_from': 'support@fingertipplus.com',
                    'email_to': recipient.email_formatted,
                    'auto_delete': False,
                })
            company.daily_outstanding_last_date = now.date()
