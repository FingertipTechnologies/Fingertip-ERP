from odoo import api, fields, models
from odoo.tools import format_date


class FtSalesForecast(models.Model):
    _name = 'ft.sales.forecast'
    _description = 'Sales Forecast'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, index=True,
        ondelete='restrict', tracking=True, check_company=True,
    )
    date = fields.Date(required=True, index=True, tracking=True)
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    description = fields.Text(tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency', store=True,
    )

    _amount_positive = models.Constraint(
        'CHECK(amount > 0)',
        'The forecast amount must be greater than zero.',
    )

    @api.depends('partner_id', 'date')
    def _compute_display_name(self):
        for forecast in self:
            forecast.display_name = ' - '.join(filter(None, [
                forecast.partner_id.display_name,
                forecast.date and format_date(self.env, forecast.date),
            ])) or self.env._('New Forecast')
