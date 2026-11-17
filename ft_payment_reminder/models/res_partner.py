from odoo import fields, models

from .payment_reminder_mixin import STOP_SELECTION


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ft_stop_reminder = fields.Selection(
        STOP_SELECTION, string='Stop Reminder', default='no', required=True,
        help='Yes: no automatic payment reminders for any invoice or pro forma of this customer.')
