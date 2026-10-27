import calendar

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round


# Existing localization fields stay visible in the standard Salary tab.
NATIVE_COMPONENTS = {
    'full_basic': 'l10n_in_basic_salary_amount',
    'full_hra': 'l10n_in_hra',
    'full_special_allowance': 'l10n_in_fixed_allowance',
    'full_leave_travel_allowance': 'l10n_in_leave_travel_allowance',
    'full_meal_allowance': 'l10n_in_meal_voucher_amount',
    'full_telephone_charges': 'l10n_in_phone_subscription',
    'full_conveyance': 'l10n_in_company_transport',
    'full_gratuity': 'l10n_in_gratuity',
    # No l10n_in field exists for this one, so it is backed by a field of our
    # own. It behaves like the native components in every other way: applying a
    # CTC writes it, the payslip rule reads it, and it counts in gross.
    'full_children_education_allowance': 'ft_children_education_allowance',
    # Paid after gross, straight into net pay: outside CTC, PT, ESI, PF and TDS.
    'full_non_taxable_allowance': 'ft_non_taxable_allowance',
}
# Components that are applied and checked like the others but are not part of
# the monthly gross.
NOT_IN_GROSS = ('full_gratuity', 'full_non_taxable_allowance')
EXTRA_EARNINGS = (
    'full_medical_allowance', 'full_consultancy_fees',
    'full_attire_allowance', 'full_book_and_periodicals',
)
EARNINGS = tuple(n for n in NATIVE_COMPONENTS if n not in NOT_IN_GROSS) + EXTRA_EARNINGS


class GreythrCTC(models.Model):
    _inherit = 'ft.greythr.ctc'

    payroll_reviewed = fields.Boolean('Payroll Setup Reviewed', copy=False,
        help='Confirm the component treatment, reconciliation differences, PF, ESIC, PT and TDS before validating payslips.')
    payroll_pf_mode = fields.Selection([
        ('pending', 'Pending Confirmation'), ('capped', 'Capped PF'), ('actual', 'Actual PF Base'),
        ('none', 'Not Applicable')], default='pending', required=True, string='PF Treatment')
    gross_difference = fields.Monetary('Source Gross Reconciliation', compute='_compute_gross_difference',
        help='Source gross less mapped earnings, paid as a reconciliation line. A gap under one rupee is rounding from annual CTC / 12 and is not paid.')

    @api.depends('monthly_gross', 'currency_id', *EARNINGS)
    def _compute_gross_difference(self):
        for record in self:
            difference = record.monthly_gross - sum(record[n] for n in EARNINGS)
            record.gross_difference = difference if record.currency_id.compare_amounts(abs(difference), 1) >= 0 else 0

    def _payroll_gross(self):
        self.ensure_one()
        return sum(self[n] for n in EARNINGS) + self.gross_difference

    def _check_payroll_manager(self):
        if not self.env.su and not self.env.user.has_group('hr_payroll.group_hr_payroll_manager'):
            raise UserError(self.env._('Only Payroll administrators can apply a CTC record.'))

    def action_apply_to_payroll(self):
        self._check_payroll_manager()
        self.ensure_one()
        if self.company_id.country_id.code != 'IN' or self.currency_id.name != 'INR':
            raise UserError(self.env._('This salary structure is for India companies using INR.'))
        if self.monthly_gross <= 0 or self.full_basic <= 0:
            raise UserError(self.env._('Provide positive monthly gross and basic salary.'))
        if self.epf_excess_contribution:
            raise UserError(self.env._('Excess PF needs an explicit payout policy before applying this CTC.'))
        if self.annual_variable_pay < 0:
            raise UserError(self.env._('Annual variable pay cannot be negative.'))
        if any(self[n] < 0 for n in EARNINGS):
            raise UserError(self.env._('Source earnings must not be negative.'))
        if self.payroll_pf_mode in ('capped', 'actual') and not self.eligible_for_pf:
            raise UserError(self.env._('PF treatment conflicts with source eligibility.'))
        if self.payroll_pf_mode == 'capped' and self.pf_base_limit <= 0:
            raise UserError(self.env._('Provide the PF base limit for capped PF.'))
        Employee = self.employee_id.with_context(tracking_disable=True)
        version = Employee.version_ids.filtered(lambda v: v.date_version == self.effective_date)
        if len(version) > 1:
            raise UserError(self.env._('Resolve duplicate employment versions first.'))
        if not version:
            previous = Employee._get_version(self.effective_date)
            if not previous:
                raise UserError(self.env._('Create an employment version covering the CTC effective date first.'))
            version = previous.copy({'date_version': self.effective_date})
        if self.env['hr.payslip'].search_count([
            ('version_id', '=', version.id), ('state', 'not in', ['draft', 'cancel'])]):
            raise UserError(self.env._('This employment version already has confirmed payslips. Use a new effective date.'))
        vals = {
            'greythr_ctc_id': self.id,
            'structure_type_id': self.env.ref('ft_greythr_migration.greythr_structure_type').id,
            'wage': self._payroll_gross(),
            # Target only. It is never paid monthly: HR types the payout on the
            # payslip (Variable Pay tab), up to this total per financial year.
            'ft_annual_variable_pay': self.annual_variable_pay,
            'l10n_in_standard_allowance': 0,
            'l10n_in_performance_bonus': 0,
            'l10n_in_internet_subscription': 0,
        }
        vals.update({field: self[source] for source, field in NATIVE_COMPONENTS.items()})
        # One write keeps the native allowance constraints and inverse percentages consistent.
        version.write(vals)
        version.write({
            'l10n_in_pf_employee_type': 'calculate' if self.payroll_pf_mode == 'actual' else 'fixed',
            'l10n_in_pf_employer_type': 'calculate' if self.payroll_pf_mode == 'actual' else 'fixed',
        })
        # The native compute shows 12% of Basic; show the amount the payslip deducts.
        pf_percent = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_in_pf_percent', self.effective_date)
        pf = self.currency_id.round(self._greythr_pf_base() * pf_percent)
        version.write({'l10n_in_pf_employee_amount': pf, 'l10n_in_pf_employer_amount': pf})
        return True

    def _greythr_pf_base(self, factor=1):
        # Like greytHR, the cap applies to the earned PF wage: a part month
        # still deducts the full 1,800 while earned basic stays above the cap.
        self.ensure_one()
        if not self.eligible_for_pf or self.payroll_pf_mode in ('none', 'pending'):
            return 0
        base = (self.master_pf_basic or self.full_basic) * factor
        if self.payroll_pf_mode == 'capped':
            base = min(base, self.pf_base_limit)
        return base

    def write(self, vals):
        # Changes to payroll inputs must be reapplied and reviewed. Source history
        # already used for confirmed payslips must remain reproducible.
        sensitive = set(EARNINGS) | set(NOT_IN_GROSS) | {'full_employer_esic', 'monthly_gross',
            'monthly_ctc', 'annual_ctc', 'annual_variable_pay', 'eligible_for_pf',
            'master_pf_basic', 'pf_base_limit', 'epf_excess_contribution', 'payroll_pf_mode',
            'effective_date', 'employee_id'}
        if sensitive.intersection(vals):
            versions = self.env['hr.version'].search([('greythr_ctc_id', 'in', self.ids)])
            if versions and self.env['hr.payslip'].search_count([
                ('version_id', 'in', versions.ids), ('state', 'not in', ['draft', 'cancel'])]):
                raise UserError(self.env._('Create a new dated CTC record; this one has confirmed payslips.'))
            vals = dict(vals, payroll_reviewed=False)
        return super().write(vals)


class HrVersion(models.Model):
    _inherit = 'hr.version'

    greythr_ctc_id = fields.Many2one('ft.greythr.ctc', string='Applied greytHR CTC',
        groups='hr_payroll.group_hr_payroll_user', ondelete='restrict', check_company=True)

    @api.constrains('greythr_ctc_id', 'employee_id')
    def _check_greythr_employee(self):
        for version in self:
            if version.greythr_ctc_id and version.greythr_ctc_id.employee_id != version.employee_id:
                raise ValidationError(self.env._('The applied CTC must belong to this employee.'))

    @api.depends('greythr_ctc_id', 'greythr_ctc_id.full_special_allowance',
                 'l10n_in_meal_voucher_amount', 'l10n_in_phone_subscription',
                 'l10n_in_internet_subscription', 'l10n_in_company_transport')
    def _compute_l10n_in_fixed_allowance(self):
        """Make the monthly wage the whole fixed gross.

        l10n_in works the special allowance out as a residual of the wage, but
        only against basic, HRA, standard allowance, bonus and LTA. Meal,
        phone, internet and transport are then *added on top* when it sums the
        gross, so Fixed Pay comes out as wage + those four -- for an employee
        on a 2,200 meal allowance, 2,200 more than the agreed salary.

        A Fingertip CTC sheet treats the monthly figure as the entire fixed
        gross with those components inside it, so they are taken out of the
        residual here and Fixed Pay equals the wage exactly. Without this the
        figure is also unstable: anyone who corrects it by hand has their
        correction silently undone the next time the residual recomputes.
        """
        super()._compute_l10n_in_fixed_allowance()
        for version in self:
            if version.greythr_ctc_id:
                # Native residual includes meal/phone/conveyance already paid
                # by other rules; the CTC record is the source of truth here.
                version.l10n_in_fixed_allowance = version.greythr_ctc_id.full_special_allowance
            elif version.country_code == 'IN' and version.l10n_in_basic_salary_amount:
                version.l10n_in_fixed_allowance -= sum([
                    version.l10n_in_phone_subscription,
                    version.l10n_in_internet_subscription,
                    version.l10n_in_meal_voucher_amount,
                    version.l10n_in_company_transport,
                ])


    ft_non_taxable_allowance = fields.Monetary(
        string='Non-Taxable Allowance', tracking=True,
        groups='hr_payroll.group_hr_payroll_user',
        help='Monthly non-taxable allowance. Paid after gross, straight into net '
             'pay: not part of CTC, and no PT, ESI, PF or TDS on it. Pro-rated '
             'for days without pay and editable on each payslip.')
    ft_children_education_allowance = fields.Monetary(
        string='Children Education Allowance', tracking=True,
        groups='hr_payroll.group_hr_payroll_user',
        help='Monthly children education allowance. Paid by the Children '
             'Education Allowance rule on the payslip and counted in gross '
             'salary, so it carries ESI and the professional tax slab with it.')

    @api.depends('ft_children_education_allowance',
                 'greythr_ctc_id', 'greythr_ctc_id.gross_difference',
                 *('greythr_ctc_id.' + name for name in EXTRA_EARNINGS))
    def _compute_l10n_in_gross_salary(self):
        # Odoo merges @api.depends down the MRO, so only the dependencies added
        # here need declaring; l10n_in's own list still applies.
        super()._compute_l10n_in_gross_salary()
        for version in self:
            # l10n_in's gross sums its own ten fields and cannot see ours.
            if version.country_code == 'IN':
                version.l10n_in_gross_salary += version.ft_children_education_allowance
        for version in self.filtered('greythr_ctc_id'):
            ctc = version.greythr_ctc_id
            version.l10n_in_gross_salary += sum(ctc[name] for name in EXTRA_EARNINGS) + ctc.gross_difference


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    greythr_applied_ctc_id = fields.Many2one(related='version_id.greythr_ctc_id',
        groups='hr_payroll.group_hr_payroll_user', string='Applied greytHR CTC')
    ft_children_education_allowance = fields.Monetary(
        related='version_id.ft_children_education_allowance', readonly=False,
        inherited=True, groups='hr_payroll.group_hr_payroll_user')
    ft_non_taxable_allowance = fields.Monetary(
        related='version_id.ft_non_taxable_allowance', readonly=False,
        inherited=True, groups='hr_payroll.group_hr_payroll_user')

    def action_greythr_apply_ctc(self):
        """Apply to Payroll for many employees at once, after a bulk import.

        Applies every CTC not yet marked reviewed, oldest first, so a salary
        history builds its versions in order. Reviewed CTCs are left alone.
        One employee failing does not undo the others; the failures are listed.
        """
        self.env['ft.greythr.ctc']._check_payroll_manager()
        applied, failed = 0, []
        for employee in self:
            ctcs = employee.greythr_ctc_ids.filtered(lambda c: not c.payroll_reviewed)
            for ctc in ctcs.sorted('effective_date'):
                try:
                    with self.env.cr.savepoint():
                        ctc.action_apply_to_payroll()
                    applied += 1
                except UserError as error:
                    failed.append('%s (%s): %s' % (employee.name, ctc.effective_date, error.args[0]))
        return self._greythr_bulk_result(self.env._('%s CTC applied to payroll.', applied), failed)

    def action_greythr_mark_reviewed(self):
        """Tick Payroll Setup Reviewed on the CTC applied to each employee."""
        self.env['ft.greythr.ctc']._check_payroll_manager()
        ctcs = self.mapped('version_id.greythr_ctc_id').filtered(lambda c: not c.payroll_reviewed)
        ctcs.write({'payroll_reviewed': True})
        missing = [employee.name for employee in self if not employee.version_id.greythr_ctc_id]
        failed = [self.env._('%s: no CTC applied yet', name) for name in missing]
        return self._greythr_bulk_result(self.env._('%s CTC marked reviewed.', len(ctcs)), failed)

    def _greythr_bulk_result(self, message, failed):
        if failed:
            message += '\n' + self.env._('Not done:') + '\n' + '\n'.join(failed)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'message': message, 'type': 'warning' if failed else 'success',
                       'sticky': bool(failed), 'next': {'type': 'ir.actions.act_window_close'}},
        }


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    ft_non_taxable_allowance_monthly = fields.Monetary(
        'Monthly Amount', related='version_id.ft_non_taxable_allowance')
    ft_non_taxable_allowance = fields.Monetary(
        'Pay This Month', compute='_compute_ft_non_taxable_allowance',
        store=True, readonly=False, copy=False,
        help='Starts from the monthly amount, pro-rated for days without pay. '
             'Can be changed for this payslip. Added to net pay after gross.')

    @api.depends('version_id.ft_non_taxable_allowance', 'worked_days_line_ids.number_of_days',
                 'worked_days_line_ids.amount', 'date_from', 'date_to')
    def _compute_ft_non_taxable_allowance(self):
        for slip in self:
            if slip.state != 'draft' or not slip.version_id or not slip.version_id.wage:
                slip.ft_non_taxable_allowance = slip.ft_non_taxable_allowance
                continue
            factor = slip.paid_amount / slip.version_id.wage
            slip.ft_non_taxable_allowance = slip._greythr_round(
                slip.version_id.ft_non_taxable_allowance * factor)

    def _greythr_ctc(self):
        self.ensure_one()
        ctc = self.version_id.greythr_ctc_id
        if not ctc or ctc.employee_id != self.employee_id:
            raise UserError(self.env._('Apply a dated greytHR CTC record to this employment version first.'))
        if ctc.effective_date > self.date_from:
            raise UserError(self.env._('The CTC effective date is after the payslip start date. Split the payslip at the effective date.'))
        later = self.employee_id.version_ids.filtered(lambda v: self.date_from < v.date_version <= self.date_to)
        if later:
            raise UserError(self.env._('Split this payslip at the employment version change.'))
        if self.version_id.wage_type != 'monthly' or self.version_id.schedule_pay != 'monthly':
            raise UserError(self.env._('The greytHR structure supports monthly fixed wages only.'))
        # Prevent stale standard fields being silently used after a source edit.
        values = {'wage': ctc._payroll_gross(), **{f: ctc[s] for s, f in NATIVE_COMPONENTS.items()}}
        if any(not self.currency_id.is_zero(self.version_id[f] - amount) for f, amount in values.items()):
            raise UserError(self.env._('Salary fields differ from the applied CTC. Reapply the CTC before computing.'))
        return ctc

    def _greythr_days(self):
        """(days in month, effective days, LOP days), the way greytHR counts them.

        greytHR pays calendar days: Aug with 1.5 days loss of pay is paid for
        29.5 of 31 days, not for the working days of the office calendar.
        Days before joining or after leaving are not effective days.
        """
        self.ensure_one()
        version = self.version_id
        days_in_month = calendar.monthrange(self.date_from.year, self.date_from.month)[1]
        start = max(self.date_from, version.contract_date_start or self.date_from)
        end = min(self.date_to, version.contract_date_end or self.date_to)
        days = max((end - start).days + 1, 0)
        lop = sum(self.worked_days_line_ids.filtered(
            lambda line: not line.is_paid and line.code != 'OUT').mapped('number_of_days'))
        return days_in_month, max(days - lop, 0), lop

    def _get_paid_amount(self):
        self.ensure_one()
        structure = self.env.ref('ft_greythr_migration.greythr_structure', raise_if_not_found=False)
        if (self.struct_id != structure or not self.struct_id.use_worked_day_lines
                or self.env.context.get('no_paid_amount') or self.env.context.get('salary_simulation')):
            return super()._get_paid_amount()
        # No paid day at all in the period: nothing is due.
        if not any(line.is_paid and line.number_of_days for line in self.worked_days_line_ids):
            return 0.0
        days_in_month, effective, _lop = self._greythr_days()
        return self.version_id.wage * effective / days_in_month

    def _greythr_factor(self):
        self.ensure_one()
        return self.paid_amount / self.version_id.wage if self.version_id.wage else 0

    def _greythr_component(self, source):
        ctc = self._greythr_ctc()
        if source not in EARNINGS + NOT_IN_GROSS + ('full_employer_esic', 'gross_difference'):
            raise UserError(self.env._('Unknown greytHR salary component.'))
        amount = self.version_id[NATIVE_COMPONENTS[source]] if source in NATIVE_COMPONENTS else ctc[source]
        return self._greythr_round(amount * self._greythr_factor())

    def _greythr_round(self, amount, rounding_method='HALF-UP'):
        # greytHR pays whole rupees, rounding each component on its own.
        return float_round(amount, precision_digits=0, rounding_method=rounding_method)

    def _greythr_pf(self):
        base = self._greythr_ctc()._greythr_pf_base(self._greythr_factor())
        return self._greythr_round(base * self._rule_parameter('l10n_in_pf_percent'))

    def _greythr_esic_employee(self, gross):
        # ESI contributions are rounded up to the next rupee.
        rate = self.version_id.l10n_in_esic_employee_percentage
        return self._greythr_round(gross * rate, rounding_method='UP')

    def action_payslip_done(self):
        for slip in self.filtered(lambda p: p.struct_id == self.env.ref('ft_greythr_migration.greythr_structure')):
            ctc = slip._greythr_ctc()
            if not ctc.payroll_reviewed or ctc.payroll_pf_mode == 'pending':
                raise UserError(self.env._('Review the CTC reconciliation, PF, ESIC, PT and TDS, then mark Payroll Setup Reviewed on the applied CTC before confirming this payslip.'))
        return super().action_payslip_done()
