from odoo import fields, models
from odoo.fields import Domain


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    # The native field captures its domain method as a callable. Rebind it so
    # this override is used by the form's Template selector as well.
    report_id = fields.Many2one(domain=lambda self: self._get_domain_report())

    def _get_domain_report(self):
        return list(Domain.OR([
            super()._get_domain_report(),
            [
                ('model', '=', 'hr.payslip'),
                ('report_type', '=', 'qweb-pdf'),
                ('report_name', '=', 'ft_greythr_migration.report_fingertip_payslip'),
            ],
        ]))
