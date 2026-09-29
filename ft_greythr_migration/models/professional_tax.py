from odoo import api, fields, models

# Karnataka professional tax starts at a monthly wage of 25,000. Above this limit
# the slab is filled in automatically; at or below it the slab is left empty.
PT_WAGE_LIMIT = 24999
PT_SLAB_XMLID = 'l10n_in_hr_payroll.l10n_in_rule_parameter_pt_karnataka'


class HrVersion(models.Model):
    _inherit = 'hr.version'

    pt_rule_parameter_id = fields.Many2one(
        compute='_compute_ft_pt_rule_parameter', store=True, readonly=False)

    @api.depends('wage')
    def _compute_ft_pt_rule_parameter(self):
        """Pick the Karnataka slab from the wage; the field stays editable.

        Runs only when the wage changes, so a slab chosen or cleared by hand is
        kept until the next wage change.
        """
        karnataka = self.env.ref(PT_SLAB_XMLID, raise_if_not_found=False)
        for version in self:
            if version.country_code != 'IN':
                version.pt_rule_parameter_id = version.pt_rule_parameter_id
            elif version.wage > PT_WAGE_LIMIT:
                version.pt_rule_parameter_id = karnataka
            else:
                version.pt_rule_parameter_id = False
