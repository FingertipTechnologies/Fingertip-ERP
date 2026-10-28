"""Payslips paid in greytHR before Odoo payroll started.

They carry greytHR's salary statement as payslip inputs (see
data/history_structure.xml), so year-to-date gross and TDS -- and the income
tax projection built on them -- include those months. Nothing is
recalculated from today's salary, and nothing is ever posted to accounting.
"""
from odoo import models

HISTORY_STRUCTURE = 'ft_greythr_migration.greythr_history_structure'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _ft_is_history(self):
        self.ensure_one()
        return self.struct_id == self.env.ref(HISTORY_STRUCTURE, raise_if_not_found=False)

    def _greythr_days(self):
        if not self._ft_is_history():
            return super()._greythr_days()
        # As greytHR reported them: its effective days also cover joining
        # mid-month, which no work entry exists for here.
        inputs = {line.code: line.amount for line in self.input_line_ids}
        return inputs.get('HIST_DAYS', 0), inputs.get('HIST_EFFECTIVE', 0), inputs.get('HIST_LOP', 0)

    def _compute_ft_non_taxable_allowance(self):
        # greytHR's figure is the HIST_NTA input; today's monthly amount is not
        # what was paid then.
        history = self.filtered(lambda slip: slip.struct_id and slip._ft_is_history())
        history.ft_non_taxable_allowance = 0
        super(HrPayslip, self - history)._compute_ft_non_taxable_allowance()

    def _action_create_account_move(self):
        # Already in the accounts from greytHR: posting again would double the
        # salary expense. The structure may still carry the default journal,
        # which Odoo copies onto every new structure.
        return super(HrPayslip, self.filtered(lambda slip: not slip._ft_is_history()))._action_create_account_move()

    def _get_warnings_by_slip(self):
        warnings_by_slip = super()._get_warnings_by_slip()
        for slip in self.filtered(lambda slip: slip.struct_id and slip._ft_is_history()):
            # Never posted, so a missing salary journal is not a problem here.
            warnings_by_slip[slip] = [
                warning for warning in warnings_by_slip.get(slip, [])
                if (warning.get('action') or {}).get('res_model') != 'hr.payroll.structure']
        return warnings_by_slip
