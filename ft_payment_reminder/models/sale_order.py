import pytz

from odoo import api, models

from .payment_reminder_mixin import INDIA_TZ


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'ft.payment.reminder.mixin']

    _ft_reminder_label = 'Proforma'
    _ft_reminder_templates = {
        'before': 'ft_payment_reminder.mail_template_proforma_before_due',
        'overdue': 'ft_payment_reminder.mail_template_proforma_overdue',
    }

    @api.model
    def _ft_reminder_domain(self):
        # confirmed orders only; ProForma Balance = not invoiced yet (net of advances)
        return [('state', '=', 'sale'), ('balance_amount', '>', 0),
                ('ft_stop_reminder', '=', 'no')]

    def _ft_reminder_partner(self):
        return self.partner_invoice_id or self.partner_id

    def _ft_reminder_salesperson(self):
        return self.user_id

    def _ft_reminder_order_date(self):
        """Order date on the India calendar."""
        if not self.date_order:
            return False
        return pytz.utc.localize(self.date_order).astimezone(INDIA_TZ).date()

    def _ft_reminder_due_date(self):
        """Order date + payment terms (the last instalment's date, as on an
        invoice); no payment terms = due on the order date."""
        order_date = self._ft_reminder_order_date()
        if not order_date:
            return False
        lines = self.payment_term_id.line_ids
        if not lines:
            return order_date
        return max(line._get_due_date(order_date) for line in lines)

    def _ft_reminder_amount(self):
        return self.balance_amount
