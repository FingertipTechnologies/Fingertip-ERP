# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ftp_tds_auto_enabled = fields.Boolean(
        related='company_id.ftp_tds_auto_enabled', readonly=False)

    def action_ftp_recompute_all_tds(self):
        self.ensure_one()
        count = self.env['hr.version']._cron_update_tds()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': self.env._("TDS updated for %(count)s employee(s).",
                                      count=count),
                'sticky': False,
            },
        }
