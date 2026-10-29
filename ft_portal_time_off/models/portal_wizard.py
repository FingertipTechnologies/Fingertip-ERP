# -*- coding: utf-8 -*-
from odoo import models


class PortalWizardUser(models.TransientModel):
    _inherit = 'portal.wizard.user'

    def action_grant_access(self):
        action = super().action_grant_access()
        # A login given back to a former portal user is reactivated, not created.
        self.partner_id.sudo().with_context(active_test=False).user_ids._ft_link_employees()
        return action
