"""Salary revisions entered on the employee's Payroll tab.

HR edits the salary directly on the Payroll tab. To change it from a date, HR
first adds a version from that date on the version timeline at the top of the
employee form; editing without a new version corrects the current revision.
Every save keeps the greytHR CTC record behind that version in step (one row
per version in the greytHR Migration tab), already applied and reviewed, so
the payslip reads exactly what the Payroll tab shows.

Agreed with HR (25-Nov-2026):
- Special Allowance is the balance of the monthly wage.
- Changing the wage leaves Basic, HRA, LTA and the other amounts as typed;
  only Special Allowance moves.
- Gratuity follows a tick: 4.81% of Basic, in whole rupees, or nothing.
- Saving from the Payroll tab counts as reviewed.
- The revision list in the greytHR Migration tab is view only.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

from .payroll import EXTRA_EARNINGS

GRATUITY_RATE = 0.0481
ESI_EMPLOYER_ROUNDING = 'HALF-UP'

# Version fields that make up the salary: a change to any of them is a revision.
SALARY_FIELDS = (
    'wage', 'l10n_in_basic_salary_amount', 'l10n_in_hra', 'l10n_in_leave_travel_allowance',
    'l10n_in_meal_voucher_amount', 'l10n_in_phone_subscription', 'l10n_in_company_transport',
    'ft_children_education_allowance', 'ft_non_taxable_allowance', 'ft_annual_variable_pay',
    'ft_gratuity_eligible', 'l10n_in_standard_allowance', 'l10n_in_performance_bonus',
    'l10n_in_internet_subscription', 'l10n_in_esic_employee_percentage',
    'l10n_in_esic_employer_percentage', 'l10n_in_esic_employee_amount', 'l10n_in_esic_employer_amount',
)
# Paid by l10n_in's own structure but not by the Fingertip one.
NOT_PAID = {
    'l10n_in_standard_allowance': 'Standard Allowance',
    'l10n_in_performance_bonus': 'Performance Bonus',
    'l10n_in_internet_subscription': 'Internet Subscription',
}


def _rupees(amount, rounding_method='HALF-UP'):
    return float_round(amount, precision_digits=0, rounding_method=rounding_method)


class HrVersion(models.Model):
    _inherit = 'hr.version'

    ft_gratuity_eligible = fields.Boolean(
        'Gratuity Eligible', groups='hr_payroll.group_hr_payroll_user', tracking=True,
        help='Gratuity is provided for at 4.81% of Basic every month and counts in CTC.')

    # Amounts stay as typed when the wage changes: only their own percentage
    # (hidden on the Payroll tab) moves them, never the wage. l10n_in would
    # otherwise rescale every component with the wage.
    l10n_in_basic_salary_amount = fields.Monetary(compute='_ft_compute_basic_amount')
    l10n_in_hra = fields.Monetary(compute='_ft_compute_hra')
    l10n_in_leave_travel_allowance = fields.Monetary(compute='_ft_compute_lta')
    l10n_in_standard_allowance = fields.Monetary(compute='_ft_compute_standard_allowance')
    l10n_in_performance_bonus = fields.Monetary(compute='_ft_compute_performance_bonus')
    l10n_in_gratuity = fields.Monetary(compute='_ft_compute_gratuity')

    # Their percentage follows only the amount: a new Basic must not turn into
    # a new HRA or LTA through a recomputed percentage.
    l10n_in_hra_percentage = fields.Float(compute='_ft_compute_hra_percentage')
    l10n_in_leave_travel_percentage = fields.Float(compute='_ft_compute_lta_percentage')
    l10n_in_standard_allowance_percentage = fields.Float(compute='_ft_compute_standard_allowance_percentage')
    l10n_in_performance_bonus_percentage = fields.Float(compute='_ft_compute_performance_bonus_percentage')

    def _ft_percentage_of_basic(self, amount_field, percentage_field):
        for version in self:
            basic = version.l10n_in_basic_salary_amount
            version[percentage_field] = (version[amount_field] / basic
                                         if version.country_code == 'IN' and basic else 0.0)

    @api.depends('l10n_in_hra')
    def _ft_compute_hra_percentage(self):
        self._ft_percentage_of_basic('l10n_in_hra', 'l10n_in_hra_percentage')

    @api.depends('l10n_in_leave_travel_allowance')
    def _ft_compute_lta_percentage(self):
        self._ft_percentage_of_basic('l10n_in_leave_travel_allowance', 'l10n_in_leave_travel_percentage')

    @api.depends('l10n_in_standard_allowance')
    def _ft_compute_standard_allowance_percentage(self):
        self._ft_percentage_of_basic('l10n_in_standard_allowance', 'l10n_in_standard_allowance_percentage')

    @api.depends('l10n_in_performance_bonus')
    def _ft_compute_performance_bonus_percentage(self):
        self._ft_percentage_of_basic('l10n_in_performance_bonus', 'l10n_in_performance_bonus_percentage')

    @api.depends('l10n_in_basic_percentage')
    def _ft_compute_basic_amount(self):
        self.env.remove_to_compute(self._fields['l10n_in_basic_percentage'], self)
        for version in self:
            version.l10n_in_basic_salary_amount = (
                version._l10n_in_get_montly_wage() * version.l10n_in_basic_percentage
                if version.country_code == 'IN' else 0.0)

    def _ft_amount_of_basic(self, amount_field, percentage_field):
        self.env.remove_to_compute(self._fields[percentage_field], self)
        for version in self:
            version[amount_field] = (version.l10n_in_basic_salary_amount * version[percentage_field]
                                     if version.country_code == 'IN' else 0.0)

    @api.depends('l10n_in_hra_percentage')
    def _ft_compute_hra(self):
        self._ft_amount_of_basic('l10n_in_hra', 'l10n_in_hra_percentage')

    @api.depends('l10n_in_leave_travel_percentage')
    def _ft_compute_lta(self):
        self._ft_amount_of_basic('l10n_in_leave_travel_allowance', 'l10n_in_leave_travel_percentage')

    @api.depends('l10n_in_standard_allowance_percentage')
    def _ft_compute_standard_allowance(self):
        self._ft_amount_of_basic('l10n_in_standard_allowance', 'l10n_in_standard_allowance_percentage')

    @api.depends('l10n_in_performance_bonus_percentage')
    def _ft_compute_performance_bonus(self):
        self._ft_amount_of_basic('l10n_in_performance_bonus', 'l10n_in_performance_bonus_percentage')

    @api.depends('l10n_in_basic_salary_amount', 'ft_gratuity_eligible')
    def _ft_compute_gratuity(self):
        for version in self:
            version.l10n_in_gratuity = (
                _rupees(version.l10n_in_basic_salary_amount * GRATUITY_RATE)
                if version.country_code == 'IN' and version.ft_gratuity_eligible else 0.0)

    @api.depends('wage', 'l10n_in_basic_salary_amount', 'l10n_in_hra', 'l10n_in_standard_allowance',
                 'l10n_in_performance_bonus', 'l10n_in_leave_travel_allowance',
                 'l10n_in_meal_voucher_amount', 'l10n_in_phone_subscription',
                 'l10n_in_internet_subscription', 'l10n_in_company_transport',
                 'ft_children_education_allowance',
                 *('greythr_ctc_id.' + name for name in EXTRA_EARNINGS), 'greythr_ctc_id.gross_difference')
    def _compute_l10n_in_fixed_allowance(self):
        """Special Allowance is the balance of the wage, so gross always equals the wage."""
        super()._compute_l10n_in_fixed_allowance()
        for version in self.filtered(lambda v: v.country_code == 'IN'):
            ctc = version.greythr_ctc_id
            version.l10n_in_fixed_allowance = version._l10n_in_get_montly_wage() - sum([
                version.l10n_in_basic_salary_amount, version.l10n_in_hra,
                version.l10n_in_standard_allowance, version.l10n_in_performance_bonus,
                version.l10n_in_leave_travel_allowance, version.l10n_in_meal_voucher_amount,
                version.l10n_in_phone_subscription, version.l10n_in_internet_subscription,
                version.l10n_in_company_transport, version.ft_children_education_allowance,
                *(ctc[name] for name in EXTRA_EARNINGS), ctc.gross_difference,
            ])

    @api.depends('wage', 'date_version', 'employee_id.greythr_pf_eligible')
    def _compute_l10n_in_pf_employee_amount(self):
        super()._compute_l10n_in_pf_employee_amount()
        for version in self.filtered(lambda v: v.country_code == 'IN'):
            version.l10n_in_pf_employee_amount = version._ft_pf_amount(version.l10n_in_pf_employee_amount)

    @api.depends('wage', 'date_version', 'employee_id.greythr_pf_eligible')
    def _compute_l10n_in_pf_employer_amount(self):
        super()._compute_l10n_in_pf_employer_amount()
        for version in self.filtered(lambda v: v.country_code == 'IN'):
            version.l10n_in_pf_employer_amount = version._ft_pf_amount(version.l10n_in_pf_employer_amount)

    def _ft_pf_amount(self, native):
        """PF as the payslip deducts it: 12% of gross on at most 25,000 from
        September 2026, nothing when the employee is not PF eligible."""
        self.ensure_one()
        if not self.employee_id.greythr_pf_eligible:
            return 0.0
        on_date = max(self.date_version or fields.Date.context_today(self), fields.Date.context_today(self))
        params = self.env['hr.rule.parameter']
        ceiling = params._get_parameter_from_code('ft_pf_gross_ceiling', on_date, raise_if_not_found=False)
        if not ceiling:
            return native
        percent = params._get_parameter_from_code('l10n_in_pf_percent', on_date)
        return _rupees(min(_rupees(self.wage), ceiling) * percent)

    # --- keeping the revision row in step ------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        versions = super().create(vals_list)
        if not self.env.context.get('ft_salary_sync'):
            # A version copied from the timeline keeps the revision it was copied
            # from until its salary is edited; a new employee's first version
            # starts a revision straight away.
            versions.filtered(lambda v: not v.greythr_ctc_id)._ft_sync_salary_revision()
        return versions

    def write(self, vals):
        if self.env.context.get('ft_salary_sync') or not set(SALARY_FIELDS).intersection(vals):
            return super().write(vals)
        self._ft_check_salary_editable()
        result = super().write(vals)
        self._ft_sync_salary_revision()
        return result

    def _ft_check_salary_editable(self):
        for version in self.filtered('greythr_ctc_id'):
            if (version.greythr_ctc_id.effective_date == version.date_version
                    and self.env['hr.payslip'].search_count([
                        ('version_id', '=', version.id), ('state', 'not in', ['draft', 'cancel'])])):
                raise UserError(self.env._(
                    'The salary from %(date)s is already in confirmed payslips of %(employee)s, so it '
                    'cannot be changed. To change the salary from a later date, add a new version '
                    'from that date on the timeline at the top of the employee form, then edit the '
                    'salary there.', date=version.date_version.strftime('%d-%m-%Y'),
                    employee=version.employee_id.name))

    def _ft_sync_salary_revision(self):
        structure_type = self.env.ref('ft_greythr_migration.greythr_structure_type', raise_if_not_found=False)
        for version in self.sudo().with_context(ft_salary_sync=True, tracking_disable=True):
            if (not version.employee_id or version.country_code != 'IN' or version.wage_type != 'monthly'
                    or version.wage <= 0
                    or version.l10n_in_basic_salary_amount <= 0 or not structure_type):
                continue
            not_paid = [label for name, label in NOT_PAID.items() if version[name]]
            if not_paid:
                raise UserError(self.env._(
                    '%(fields)s are not paid by the Fingertip salary structure. Set them to 0 and '
                    'include the amount in another component.', fields=', '.join(not_paid)))
            vals = version._ft_revision_values()
            ctc = version.greythr_ctc_id
            if ctc and ctc.effective_date == version.date_version:
                ctc.write(vals)
            else:
                ctc = ctc.create(dict(vals, employee_id=version.employee_id.id,
                                      effective_date=version.date_version,
                                      remarks=self.env._('Salary revision from %s, entered on the Payroll tab.',
                                                         version.date_version.strftime('%d-%m-%Y'))))
            version.write({'greythr_ctc_id': ctc.id, 'structure_type_id': structure_type.id})
            ctc._greythr_write_contract_pf(version)

    @api.model
    def _ft_revision_fields(self):
        return ['full_basic', 'full_hra', 'full_special_allowance', 'full_leave_travel_allowance',
                'full_meal_allowance', 'full_telephone_charges', 'full_conveyance',
                'full_children_education_allowance', 'full_non_taxable_allowance', 'full_gratuity',
                'full_employer_esic', 'monthly_gross', 'monthly_ctc', 'annual_ctc', 'annual_variable_pay',
                'annual_fixed_pay', 'annual_pf_employer', 'annual_esic_employer', 'annual_gratuity',
                'eligible_for_pf', 'master_pf_basic', 'pf_base_limit']

    def _ft_revision_values(self):
        """The revision row as the Payroll tab shows it."""
        self.ensure_one()
        employer_esi = _rupees(self.wage * self.l10n_in_esic_employer_percentage, ESI_EMPLOYER_ROUNDING)
        pf_eligible = self.employee_id.greythr_pf_eligible
        monthly_ctc = (self.wage + self.l10n_in_pf_employer_amount + employer_esi + self.l10n_in_gratuity
                       + (self.ft_annual_variable_pay or 0.0) / 12)
        return {
            'full_basic': self.l10n_in_basic_salary_amount,
            'full_hra': self.l10n_in_hra,
            'full_special_allowance': self.l10n_in_fixed_allowance,
            'full_leave_travel_allowance': self.l10n_in_leave_travel_allowance,
            'full_meal_allowance': self.l10n_in_meal_voucher_amount,
            'full_telephone_charges': self.l10n_in_phone_subscription,
            'full_conveyance': self.l10n_in_company_transport,
            'full_children_education_allowance': self.ft_children_education_allowance,
            'full_non_taxable_allowance': self.ft_non_taxable_allowance,
            'full_gratuity': self.l10n_in_gratuity,
            'full_employer_esic': employer_esi,
            'monthly_gross': self.wage,
            'monthly_ctc': float_round(monthly_ctc, precision_digits=2),
            'annual_ctc': float_round(monthly_ctc * 12, precision_digits=2),
            'annual_variable_pay': self.ft_annual_variable_pay or 0.0,
            'annual_fixed_pay': 0.0, 'annual_pf_employer': 0.0,
            'annual_esic_employer': 0.0, 'annual_gratuity': 0.0,
            'eligible_for_pf': pf_eligible,
            'payroll_pf_mode': 'capped' if pf_eligible else 'none',
            'pf_base_limit': 15000,
            'master_pf_basic': self.l10n_in_basic_salary_amount,
            'payroll_reviewed': True,
        }


class GreythrCTC(models.Model):
    _inherit = 'ft.greythr.ctc'

    @api.model_create_multi
    def create(self, vals_list):
        """An imported row for a date that already has a revision (a new joiner
        saved on the Payroll tab, then imported) takes that revision over
        instead of clashing with it."""
        if self.env.context.get('ft_salary_sync'):
            return super().create(vals_list)
        taken_over, new_vals = self.browse(), []
        blank = dict.fromkeys(self.env['hr.version']._ft_revision_fields(), False)
        for vals in vals_list:
            existing = vals.get('employee_id') and vals.get('effective_date') and self.search([
                ('employee_id', '=', vals['employee_id']), ('effective_date', '=', vals['effective_date'])])
            if existing:
                existing.write({**blank, 'remarks': False, **vals})
                if 'payroll_reviewed' in vals:
                    existing.with_context(ft_salary_sync=True).write({'payroll_reviewed': vals['payroll_reviewed']})
                taken_over |= existing
            else:
                new_vals.append(vals)
        return taken_over | super().create(new_vals)

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get('ft_salary_sync') and 'payroll_reviewed' in vals:
            # The base write clears the tick on every pay change; a save from the
            # Payroll tab is HR's review.
            super().write({'payroll_reviewed': vals['payroll_reviewed']})
        return result


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    ft_gratuity_eligible = fields.Boolean(
        related='version_id.ft_gratuity_eligible', inherited=True, readonly=False,
        groups='hr_payroll.group_hr_payroll_user')

    @api.model_create_multi
    def create(self, vals_list):
        # The first version exists before its employee does, so its revision
        # can only be started once the employee is there.
        employees = super().create(vals_list)
        if not self.env.context.get('ft_salary_sync'):
            employees.version_id.filtered(lambda v: not v.greythr_ctc_id)._ft_sync_salary_revision()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if 'greythr_pf_eligible' in vals and not self.env.context.get('ft_salary_sync'):
            versions = self.version_id
            versions._ft_check_salary_editable()
            versions._ft_sync_salary_revision()
        return result
