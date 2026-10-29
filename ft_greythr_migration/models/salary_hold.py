"""Final salary of a leaver is held until the exit is closed.

The payslip of the month an employee leaves in is confirmed with its pay run,
so the salary is booked as payable, but it is kept out of every payment (Mark
as Paid, Pay, bank file, Payment Advice) until Payroll releases it. Release
needs both: the release date reached (departure date + the company's hold
days, 45 by default, changeable per payslip) and HR's exit clearance on the
employee, which is given only once the Offboarding checklist is done.
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date

OFFBOARDING_PLAN = 'hr.offboarding_plan'


class ResCompany(models.Model):
    _inherit = 'res.company'

    ft_salary_hold_days = fields.Integer('Leaver Salary Hold (Days)', default=45)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ft_salary_hold_days = fields.Integer(related='company_id.ft_salary_hold_days', readonly=False)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ft_exit_cleared_date = fields.Date('Exit Clearance Done On', readonly=True, copy=False,
                                       groups='hr.group_hr_user', tracking=True)
    ft_exit_cleared_by = fields.Many2one('res.users', 'Exit Cleared By', readonly=True, copy=False,
                                         groups='hr.group_hr_user')

    def _ft_open_offboarding_activities(self):
        plan = self.env.ref(OFFBOARDING_PLAN, raise_if_not_found=False)
        summaries = plan.template_ids.mapped('summary') if plan else []
        return self.activity_ids.filtered(lambda activity: activity.summary in summaries)

    def action_ft_exit_clearance(self):
        for employee in self:
            if not employee.departure_date:
                raise UserError(self.env._('%s has no departure registered. Archive the employee '
                                           'through the Departure wizard first.', employee.name))
            pending = employee._ft_open_offboarding_activities()
            if pending:
                raise UserError(self.env._('Finish the Offboarding checklist of %(name)s first:\n%(steps)s',
                                           name=employee.name, steps='\n'.join(pending.mapped('summary'))))
        self.write({'ft_exit_cleared_date': fields.Date.context_today(self),
                    'ft_exit_cleared_by': self.env.user.id})

    def action_ft_undo_exit_clearance(self):
        self.write({'ft_exit_cleared_date': False, 'ft_exit_cleared_by': False})


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    ft_departure_date = fields.Date(related='employee_id.departure_date', string='Departure Date')
    ft_salary_hold = fields.Boolean(
        'Salary on Hold', compute='_compute_ft_salary_hold', store=True, readonly=False, copy=False,
        help='Set on the payslip of the month the employee leaves in. Held payslips are '
             'confirmed with the pay run but cannot be paid until released.')
    ft_hold_release_date = fields.Date(
        'Hold Until', compute='_compute_ft_hold_release_date', store=True, readonly=False, copy=False)
    ft_exit_cleared_date = fields.Date(related='employee_id.ft_exit_cleared_date')
    ft_salary_released_date = fields.Date('Salary Released On', readonly=True, copy=False)
    ft_salary_released_by = fields.Many2one('res.users', 'Salary Released By', readonly=True, copy=False)

    @api.depends('employee_id.departure_date', 'date_from', 'date_to')
    def _compute_ft_salary_hold(self):
        for slip in self:
            # Paid, cancelled or already released payslips keep what they have.
            if slip.state in ('paid', 'cancel') or slip.ft_salary_released_date:
                continue
            departure = slip.employee_id.departure_date
            slip.ft_salary_hold = bool(departure and slip.date_from <= departure <= slip.date_to)

    @api.depends('ft_salary_hold', 'employee_id.departure_date', 'company_id.ft_salary_hold_days')
    def _compute_ft_hold_release_date(self):
        for slip in self:
            departure = slip.employee_id.departure_date
            if slip.ft_salary_hold and departure:
                slip.ft_hold_release_date = departure + timedelta(days=slip.company_id.ft_salary_hold_days)
            elif not slip.ft_salary_hold:
                slip.ft_hold_release_date = False

    def _ft_check_not_held(self):
        held = self.filtered('ft_salary_hold')
        if held:
            raise UserError(self.env._(
                'Salary on hold, release it first: %s',
                ', '.join('%s (until %s)' % (slip.employee_id.name, format_date(self.env, slip.ft_hold_release_date))
                          for slip in held)))

    def action_ft_release_salary(self):
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise UserError(self.env._('Only Payroll administrators can release a held salary.'))
        today = fields.Date.context_today(self)
        for slip in self.filtered('ft_salary_hold'):
            if slip.ft_hold_release_date and slip.ft_hold_release_date > today:
                raise UserError(self.env._('The salary of %(name)s is held until %(date)s.',
                                           name=slip.employee_id.name,
                                           date=format_date(self.env, slip.ft_hold_release_date)))
            if not slip.employee_id.ft_exit_cleared_date:
                raise UserError(self.env._('Exit clearance of %s is not done yet. Complete it on the '
                                           'employee (Departure section) first.', slip.employee_id.name))
            slip.write({'ft_salary_hold': False, 'ft_salary_released_date': today,
                        'ft_salary_released_by': self.env.user.id})
            slip.message_post(body=self.env._('Held salary released for payment.'))

    def action_payslip_paid(self):
        if self.env.context.get('ft_skip_held'):
            # A pay run pays everyone else; held payslips simply stay confirmed.
            return super(HrPayslip, self.filtered(lambda slip: not slip.ft_salary_hold)).action_payslip_paid()
        self._ft_check_not_held()
        return super().action_payslip_paid()

    def action_register_payment(self):
        self._ft_check_not_held()
        return super().action_register_payment()

    def action_payslip_payment_report(self, export_format='csv'):
        self._ft_check_not_held()
        return super().action_payslip_payment_report(export_format)


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    @api.depends('slip_ids.ft_salary_hold')
    def _compute_state(self):
        super()._compute_state()
        # A run whose only unpaid payslips are held ones is paid.
        for run in self.filtered(lambda run: run.state == '02_close'):
            slips = run.slip_ids.filtered(lambda slip: slip.state != 'cancel')
            unpaid = slips.filtered(lambda slip: slip.state != 'paid')
            if unpaid and len(unpaid) < len(slips) and all(
                    slip.state == 'validated' and slip.ft_salary_hold for slip in unpaid):
                run.state = '03_paid'

    def action_paid(self):
        return super(HrPayslipRun, self.with_context(ft_skip_held=True)).action_paid()

    def action_unpaid(self):
        # Held payslips were never paid; revert only the others.
        held = self.slip_ids.filtered(lambda slip: slip.state == 'validated' and slip.ft_salary_hold)
        if not held:
            return super().action_unpaid()
        (self.slip_ids - held).filtered(lambda slip: slip.state == 'paid').action_payslip_unpaid()


class HrPayrollPaymentReportWizard(models.TransientModel):
    _inherit = 'hr.payroll.payment.report.wizard'

    def _perform_checks(self):
        # Every bank file and Payment Advice goes through here: leave held salaries out.
        self.payslip_ids = self.payslip_ids.filtered(lambda slip: not slip.ft_salary_hold)
        return super()._perform_checks()
