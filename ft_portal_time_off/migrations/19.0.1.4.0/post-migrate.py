# -*- coding: utf-8 -*-
"""Leavers archived before 1.4.0 kept an open portal login: close it."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee'].search([('active', '=', False), ('user_id.active', '=', True)])._ft_sync_portal_users_active()
