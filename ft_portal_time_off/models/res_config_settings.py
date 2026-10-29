# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ft_time_off_hr_ids = fields.Many2many(related='company_id.ft_time_off_hr_ids', readonly=False)
    ft_time_off_email_from = fields.Char(related='company_id.ft_time_off_email_from', readonly=False)
