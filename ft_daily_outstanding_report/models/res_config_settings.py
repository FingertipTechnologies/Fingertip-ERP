from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Save these together in set_values: separate related inverses validate the
    # enabled flag before the newly selected recipients reach the company.
    daily_outstanding_enabled = fields.Boolean(string='Daily Outstanding Report')
    daily_outstanding_partner_ids = fields.Many2many(
        'res.partner', string='Report Recipients')

    @api.model
    def get_values(self):
        values = super().get_values()
        company = self.env.company
        values.update(
            daily_outstanding_enabled=company.daily_outstanding_enabled,
            daily_outstanding_partner_ids=[fields.Command.set(company.daily_outstanding_partner_ids.ids)],
        )
        return values

    @api.onchange('company_id')
    def _onchange_daily_outstanding_company(self):
        self.daily_outstanding_enabled = self.company_id.daily_outstanding_enabled
        self.daily_outstanding_partner_ids = self.company_id.daily_outstanding_partner_ids

    def set_values(self):
        super().set_values()
        self.company_id.write({
            'daily_outstanding_enabled': self.daily_outstanding_enabled,
            'daily_outstanding_partner_ids': [fields.Command.set(self.daily_outstanding_partner_ids.ids)],
        })
