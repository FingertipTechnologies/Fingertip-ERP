"""Payslips paid in greytHR before Odoo payroll started.

They carry greytHR's salary statement as payslip inputs (see
data/history_structure.xml), so year-to-date gross and TDS -- and the income
tax projection built on them -- include those months. Nothing is
recalculated from today's salary, and nothing is ever posted to accounting.
"""
import math

from odoo import models

HISTORY_STRUCTURE = 'ft_greythr_migration.greythr_history_structure'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _ft_is_history(self):
        self.ensure_one()
        return self.struct_id == self.env.ref(HISTORY_STRUCTURE, raise_if_not_found=False)

    def _greythr_history_employer_ctc(self, gross):
        """Cost to company of a greytHR month: gross + employer PF + employer ESI.

        The statement only has the employee side. Employer PF matches the employee PF
        (12% of the same capped wage); employer ESI is 3.25% of gross, rounded up like
        greytHR's ESI, and only where greytHR deducted employee ESI.
        """
        self.ensure_one()
        amounts = {line.code: line.amount for line in self.input_line_ids}
        pf = amounts.get('HIST_PF', 0.0)
        esi = math.ceil(gross * 0.0325) if amounts.get('HIST_ESI') else 0.0
        return gross + pf + esi

    def _ft_backfill_employer_cost(self):
        """Give confirmed greytHR history payslips their CTC_TOTAL line, then refresh
        employer_cost on these payslips from the rules counted as employer cost.
        Confirmed payslips are never recomputed, so the line is added directly."""
        rule = self.env.ref('ft_greythr_migration.greythr_history_rule_ctc_total', raise_if_not_found=False)
        history = self.env.ref(HISTORY_STRUCTURE, raise_if_not_found=False)
        added = 0
        if rule and history:
            for slip in self.filtered(lambda s: s.struct_id == history and s.state != 'cancel'):
                if slip.line_ids.filtered(lambda l: l.code == 'CTC_TOTAL'):
                    continue
                gross = sum(slip.line_ids.filtered(lambda l: l.code == 'GROSS').mapped('total'))
                amount = slip._greythr_history_employer_ctc(gross)
                self.env['hr.payslip.line'].sudo().create({
                    'slip_id': slip.id, 'salary_rule_id': rule.id, 'name': rule.name, 'code': rule.code,
                    'category_id': rule.category_id.id, 'sequence': rule.sequence,
                    'employee_id': slip.employee_id.id, 'version_id': slip.version_id.id,
                    'amount': amount, 'quantity': 1.0, 'rate': 100.0, 'total': amount,
                })
                added += 1
        self.env.flush_all()
        if self:
            self.env.cr.execute("""
                UPDATE hr_payslip p
                   SET employer_cost = COALESCE((
                        SELECT SUM(l.total) FROM hr_payslip_line l
                          JOIN hr_salary_rule r ON r.id = l.salary_rule_id
                         WHERE l.slip_id = p.id AND r.appears_on_employee_cost_dashboard), 0)
                 WHERE p.id = ANY(%s)
            """, [self.ids])
            self.invalidate_recordset(['employer_cost'])
        return added

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
