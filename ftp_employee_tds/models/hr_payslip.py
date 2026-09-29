from odoo import models


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _get_payslip_lines(self):
        # Work one slip at a time: historical slips can share a version but
        # require different tax dates. Never rewrite validated payroll lines.
        result = []
        regular = self.env.ref('l10n_in_hr_payroll.hr_payroll_structure_in_employee_salary')
        for slip in self:
            if slip.state == 'draft' and slip.struct_id == regular:
                slip.version_id._ftp_apply_tds(slip.date_from)
            result.extend(super(HrPayslip, slip)._get_payslip_lines())
        return result
