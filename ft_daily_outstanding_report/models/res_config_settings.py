from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    daily_outstanding_enabled = fields.Boolean(
        related='company_id.daily_outstanding_enabled', readonly=False)
    daily_outstanding_partner_id = fields.Many2one(
        related='company_id.daily_outstanding_partner_id', readonly=False)
