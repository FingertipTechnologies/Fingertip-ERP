# -*- coding: utf-8 -*-
"""Portal users given access from Contacts were never linked to their employee."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.users'].search([('share', '=', True)])._ft_link_employees()
