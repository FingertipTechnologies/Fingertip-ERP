from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Indian financial year: 1 April to 31 March. The annual variable pay target is
# measured against what was paid on payslips inside one financial year.
FY_START_MONTH = 4

# Payslips in these states have actually paid their variable pay.
PAID_PAYSLIP_STATES = ('validated', 'paid')


def financial_year_bounds(on_date):
    """First and last day of the financial year containing on_date."""
    year = on_date.year if on_date.month >= FY_START_MONTH else on_date.year - 1
    return date(year, FY_START_MONTH, 1), date(year + 1, FY_START_MONTH, 1) - timedelta(days=1)


class HrVersion(models.Model):
    """Annual variable pay target, held on the employment version.

    Odoo 19 has no hr.contract: hr.employee ``_inherits`` hr.version, so the
    version IS the contract and is where salary figures belong.
    """
    _inherit = 'hr.version'

    ft_annual_variable_pay = fields.Monetary(
        'Annual Variable Pay', tracking=True,
        groups='hr_payroll.group_hr_payroll_user',
        help='Full-year variable pay target. HR pays it on payslips, in the months '
             'and amounts decided on performance, up to this total per financial year.')

    @api.constrains('ft_annual_variable_pay')
    def _check_ft_annual_variable_pay(self):
        for version in self:
            if version.ft_annual_variable_pay < 0:
                raise ValidationError(self.env._('Annual variable pay cannot be negative.'))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # inherited=True is required for a _inherits field carrying its own `groups`,
    # otherwise the delegation is not linked and the field is unreadable from the
    # employee (see the note above contract_date_start in hr/models/hr_employee.py).
    ft_annual_variable_pay = fields.Monetary(
        related='version_id.ft_annual_variable_pay', inherited=True, readonly=False,
        groups='hr_payroll.group_hr_payroll_user')
    ft_variable_pay_paid_fy = fields.Monetary(
        'Variable Pay Paid This FY', compute='_compute_ft_variable_pay_fy',
        groups='hr_payroll.group_hr_payroll_user',
        help='Variable pay on confirmed payslips in the current financial year (Apr-Mar).')
    ft_variable_pay_remaining = fields.Monetary(
        'Variable Pay Remaining This FY', compute='_compute_ft_variable_pay_fy',
        groups='hr_payroll.group_hr_payroll_user')

    def _compute_ft_variable_pay_fy(self):
        start, end = financial_year_bounds(fields.Date.context_today(self))
        for employee in self:
            paid = employee._ft_variable_pay_paid(start, end)
            employee.ft_variable_pay_paid_fy = paid
            employee.ft_variable_pay_remaining = employee.ft_annual_variable_pay - paid

    def _ft_variable_pay_paid(self, start, end, exclude=None):
        """Variable pay on this employee's confirmed payslips starting in [start, end]."""
        self.ensure_one()
        domain = [('employee_id', '=', self.id), ('state', 'in', PAID_PAYSLIP_STATES),
                  ('date_from', '>=', start), ('date_from', '<=', end)]
        if exclude:
            domain.append(('id', 'not in', exclude.ids))
        return sum(self.env['hr.payslip'].sudo().search(domain).mapped('ft_variable_pay_amount'))


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    # Typed by HR on the draft payslip, after it is generated, based on
    # performance. Paid through the VAR_PAY salary rule.
    ft_variable_pay_amount = fields.Monetary(
        'Pay This Month', copy=False, tracking=True,
        help='Variable pay for this payslip, decided on performance. Added to gross '
             'and net pay. Leave 0 when no variable pay is due.')
    ft_variable_pay_target = fields.Monetary(
        'Annual Target', related='version_id.ft_annual_variable_pay')
    ft_variable_pay_paid_fy = fields.Monetary(
        'Paid This FY', compute='_compute_ft_variable_pay_fy',
        help='Variable pay on the other confirmed payslips of this financial year (Apr-Mar).')
    ft_variable_pay_remaining = fields.Monetary(
        'Remaining', compute='_compute_ft_variable_pay_fy',
        help='Annual target less what this financial year has already paid.')

    @api.depends('employee_id', 'date_from', 'version_id.ft_annual_variable_pay')
    def _compute_ft_variable_pay_fy(self):
        for slip in self:
            paid = 0.0
            if slip.employee_id and slip.date_from:
                start, end = financial_year_bounds(slip.date_from)
                paid = slip.employee_id._ft_variable_pay_paid(start, end, exclude=slip._origin)
            slip.ft_variable_pay_paid_fy = paid
            slip.ft_variable_pay_remaining = slip.version_id.sudo().ft_annual_variable_pay - paid

    @api.constrains('ft_variable_pay_amount', 'state')
    def _check_ft_variable_pay_amount(self):
        """Never more than the annual target per financial year."""
        for slip in self.filtered(lambda s: s.state != 'cancel'):
            amount = slip.ft_variable_pay_amount
            if slip.currency_id.compare_amounts(amount, 0) < 0:
                raise ValidationError(self.env._('Variable pay cannot be negative.'))
            if slip.currency_id.is_zero(amount):
                continue
            # Fresh figures: another payslip may have been confirmed since these
            # were first computed.
            slip.invalidate_recordset(['ft_variable_pay_paid_fy', 'ft_variable_pay_remaining'])
            if slip.currency_id.compare_amounts(amount, slip.ft_variable_pay_remaining) > 0:
                raise ValidationError(self.env._(
                    '%(employee)s: variable pay of %(amount)s is more than the %(remaining)s '
                    'left of the annual target (%(target)s, of which %(paid)s is already '
                    'paid this financial year).',
                    employee=slip.employee_id.name, amount=amount,
                    remaining=max(slip.ft_variable_pay_remaining, 0),
                    target=slip.ft_variable_pay_target, paid=slip.ft_variable_pay_paid_fy))
