from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


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
}
EXTRA_EARNINGS = (
    'full_medical_allowance', 'full_consultancy_fees',
    'full_attire_allowance', 'full_book_and_periodicals',
)
EARNINGS = tuple(n for n in NATIVE_COMPONENTS if n != 'full_gratuity') + EXTRA_EARNINGS


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
            # Target only. It is never paid monthly: payout happens through
            # hr.variable.pay, one approved amount per quarter.
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
        return True

    def write(self, vals):
        # Changes to payroll inputs must be reapplied and reviewed. Source history
        # already used for confirmed payslips must remain reproducible.
        sensitive = set(EARNINGS) | {'full_gratuity', 'full_employer_esic', 'monthly_gross',
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

    @api.depends('greythr_ctc_id', 'greythr_ctc_id.full_special_allowance')
    def _compute_l10n_in_fixed_allowance(self):
        super()._compute_l10n_in_fixed_allowance()
        for version in self.filtered('greythr_ctc_id'):
            # Native residual includes meal/phone/conveyance already paid by other rules.
            version.l10n_in_fixed_allowance = version.greythr_ctc_id.full_special_allowance


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


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

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

    def _greythr_factor(self):
        self.ensure_one()
        return self.paid_amount / self.version_id.wage if self.version_id.wage else 0

    def _greythr_component(self, source):
        ctc = self._greythr_ctc()
        if source not in EARNINGS + ('full_gratuity', 'full_employer_esic', 'gross_difference'):
            raise UserError(self.env._('Unknown greytHR salary component.'))
        amount = self.version_id[NATIVE_COMPONENTS[source]] if source in NATIVE_COMPONENTS else ctc[source]
        return self.currency_id.round(amount * self._greythr_factor())

    def _greythr_pf(self):
        ctc = self._greythr_ctc()
        if not ctc.eligible_for_pf or ctc.payroll_pf_mode in ('none', 'pending'):
            return 0
        base = ctc.master_pf_basic or ctc.full_basic
        if ctc.payroll_pf_mode == 'capped':
            base = min(base, ctc.pf_base_limit)
        return self.currency_id.round(base * self._rule_parameter('l10n_in_pf_percent') * self._greythr_factor())

    def action_payslip_done(self):
        for slip in self.filtered(lambda p: p.struct_id == self.env.ref('ft_greythr_migration.greythr_structure')):
            ctc = slip._greythr_ctc()
            if not ctc.payroll_reviewed or ctc.payroll_pf_mode == 'pending':
                raise UserError(self.env._('Review the CTC reconciliation, PF, ESIC, PT and TDS, then mark Payroll Setup Reviewed on the applied CTC before confirming this payslip.'))
        return super().action_payslip_done()
