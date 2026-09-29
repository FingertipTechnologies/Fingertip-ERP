# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    ftp_tds_auto_enabled = fields.Boolean(
        string='Automatic TDS Computation', default=True,
        help="Work out each employee's monthly TDS from projected annual "
             "gross pay, new regime. Switch off to go back to entering TDS "
             "by hand for everyone.")
