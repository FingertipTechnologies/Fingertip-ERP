from odoo import fields, models


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    ft_fnf_settlement_id = fields.Many2one('ft.fnf.settlement', 'Full & Final Settlement',
                                           readonly=True, copy=False, index='btree_not_null')

    def _ft_is_fnf(self):
        return self.struct_id == self.env.ref('ft_full_final_settlement.fnf_structure', raise_if_not_found=False)

    def _salary_advance_due_installments(self):
        """The settlement payslip recovers every installment no monthly payslip
        has taken, whatever its due date: the employee is leaving."""
        if not self._ft_is_fnf():
            return super()._salary_advance_due_installments()
        return self.ft_fnf_settlement_id._ft_outstanding_installments() if self.ft_fnf_settlement_id else \
            self.env['hr.salary.advance.installment']

    def write(self, vals):
        result = super().write(vals)
        if 'state' in vals:
            self.ft_fnf_settlement_id._ft_sync_state_from_payslip()
        return result

    def action_ft_release_salary(self):
        """A leaver's held payslips (last month and settlement) are released together."""
        others = self.search([('employee_id', 'in', self.employee_id.ids), ('ft_salary_hold', '=', True),
                              ('state', '=', 'validated'), ('id', 'not in', self.ids)])
        return super(HrPayslip, self | others).action_ft_release_salary()
