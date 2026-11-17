from odoo import api, models


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'ft.payment.reminder.mixin']

    _ft_reminder_label = 'Invoice'
    _ft_reminder_templates = {
        'before': 'ft_payment_reminder.mail_template_invoice_before_due',
        'overdue': 'ft_payment_reminder.mail_template_invoice_overdue',
    }

    @api.model
    def _ft_reminder_domain(self):
        return [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('ft_stop_reminder', '=', 'no')]

    def _ft_reminder_partner(self):
        return self.partner_id

    def _ft_reminder_salesperson(self):
        return self.invoice_user_id

    def _ft_reminder_due_date(self):
        return self.invoice_date_due or self.invoice_date

    def _ft_reminder_amount(self):
        return self.amount_residual
